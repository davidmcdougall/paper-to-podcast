"""Reproductions from the independent PR review, including failure boundaries."""
import json
import os
from types import SimpleNamespace as N
import pytest
import storage


def test_default_discovery_and_explicit_pins(appmod, monkeypatch):
    from test_models import FakeClient
    api=FakeClient([N(id='claude-opus-9'),N(id='claude-sonnet-9'),N(id='claude-haiku-9')])
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:api)
    assert appmod.resolve_models({})==('claude-sonnet-9','claude-haiku-9')
    monkeypatch.setenv('TEXT_MODEL','claude-sonnet-fixed')
    assert appmod.resolve_models({})==('claude-sonnet-fixed','claude-haiku-9')


def test_migrate_empty_reserved_duplicate_with_assets(appmod, client):
    slugs=['','con','same','same']
    original=json.dumps([{'slug':s,'title':'Legacy','audio_url':f'/static/audio/{s}.mp3',
                          'pdf_url':f'/static/pdfs/{s}.pdf','file_size':5} for s in slugs])
    appmod.EPISODES_FILE.write_text(original,encoding='utf-8')
    for slug in set(slugs):
        if os.name=='nt' and not storage.valid_id(slug):continue
        (appmod.AUDIO_DIR/(slug+'.mp3')).write_bytes(b'audio')
        (appmod.PDF_DIR/(slug+'.pdf')).write_bytes(b'%PDF-test')
    response=client.get('/episodes.json')
    assert response.status_code==200
    episodes=response.json
    assert len({e['slug'] for e in episodes})==4
    assert all(storage.valid_id(e['slug']) for e in episodes)
    for ep in episodes:
        if 'legacy_slug' not in ep:continue
        assert ep['legacy_files']['audio_url'].endswith(ep['legacy_slug']+'.mp3')
        if os.name!='nt' or storage.valid_id(ep['legacy_slug']):
            assert (appmod.AUDIO_DIR/ep['local_audio']).read_bytes()==b'audio'
            assert (appmod.PDF_DIR/(ep['slug']+'.pdf')).read_bytes()==b'%PDF-test'
    assert appmod.EPISODES_FILE.with_suffix('.json.migration.bak').read_text(encoding='utf-8')==original
    assert client.get('/episodes.json').json==episodes
    assert (appmod.AUDIO_DIR/'same.mp3').exists()


def test_migration_does_not_follow_traversal_or_symlinks(appmod,tmp_path):
    outside=tmp_path/'outside.mp3';outside.write_bytes(b'private')
    appmod.EPISODES_FILE.write_text(json.dumps([{'slug':'../outside'}]),encoding='utf-8')
    ep=appmod.load_episodes()[0]
    assert ep['audio_url']=='' and not ep['audio_ready']
    assert outside.read_bytes()==b'private'


def test_migration_commit_failure_preserves_json(appmod,monkeypatch):
    original='[{"slug":""}]'
    appmod.EPISODES_FILE.write_text(original,encoding='utf-8')
    monkeypatch.setattr(storage,'atomic_write',lambda *a:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):appmod.load_episodes()
    assert appmod.EPISODES_FILE.read_text(encoding='utf-8')==original


def test_transient_windows_replace_error_retries(tmp_path,monkeypatch):
    real=storage.os.replace;calls=[]
    def replace(*args):
        calls.append(1)
        if len(calls)<3:raise PermissionError('reader open')
        real(*args)
    monkeypatch.setattr(storage.os,'replace',replace)
    path=tmp_path/'file';storage.atomic_write(path,b'complete')
    assert path.read_bytes()==b'complete' and len(calls)==3


@pytest.mark.parametrize('minutes',[30,40])
def test_long_source_fits_character_and_measured_token_budgets(appmod,monkeypatch,minutes):
    from test_models import FakeClient
    calls=[];counts=[]
    def count(**kw):
        prompt=kw['messages'][0]['content'];counts.append(len(prompt))
        # Deliberately token-dense: sampling must respond to measured counts.
        return N(input_tokens=len(prompt)//2)
    def create(**kw):
        prompt=kw['messages'][0]['content'];calls.append(prompt)
        assert len(prompt)<=appmod.MAX_PROMPT_CHARS
        assert len(prompt)//2+kw['max_tokens']<=appmod.MAX_INPUT_TOKENS
        return N(content=[N(type='text',text='Complete spoken script')],stop_reason='end_turn',usage=N(input_tokens=1,output_tokens=1))
    api=FakeClient([]);api.messages=N(count_tokens=count,create=create)
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:api)
    source='BEGIN '+('research '*20000)+' MIDDLE '+('evidence '*20000)+' END'
    warnings=[]
    assert appmod.generate_podcast_script(source,target_words=minutes*150,model='writer',fast='fast',warnings=warnings)
    assert 'BEGIN' in calls[0] and 'MIDDLE' in calls[0] and 'END' in calls[0]
    assert len(counts)>len(calls) and any('sample' in w for w in warnings)


def test_foreign_flask_session_cookie_does_not_break_csrf(client,episode):
    client.set_cookie('session','another-flask-app')
    assert client.post('/rename/test-id',json={'title':'New title'}).status_code==200


def test_r2_domain_change_keeps_ownership(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    monkeypatch.setattr(appmod,'R2_PUBLIC_URL','https://custom.test')
    path=appmod.AUDIO_DIR/'test-id.mp3';path.write_bytes(b'audio')
    storage.update(appmod.EPISODES_FILE,'test-id',{'file_size':5,'r2_url':'https://old.r2.dev/audio/test-id.mp3',
        'r2_key':'audio/test-id.mp3','r2_location':appmod.r2_location()})
    monkeypatch.setattr(appmod,'upload_to_r2',lambda path,key,**kw:appmod.R2_PUBLIC_URL+'/'+key)
    monkeypatch.setattr(appmod,'publish_feed',lambda *a,**kw:None)
    deleted=[]
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(delete_object=lambda **kw:deleted.append(kw['Key'])))
    assert client.post('/publish/test-id').status_code==200
    assert appmod.find_episode('test-id')['r2_url'].startswith('https://custom.test/')
    assert client.post('/delete/test-id').status_code==200
    assert deleted==['audio/test-id.mp3']


@pytest.mark.parametrize('problem',['disabled','bucket','legacy-host'])
def test_r2_preflight_failure_does_not_mark_pending(appmod,client,episode,monkeypatch,problem):
    monkeypatch.setattr(appmod,'R2_ENABLED',problem!='disabled')
    ep={'r2_url':'https://old.test/audio/test-id.mp3'}
    if problem=='bucket':ep['r2_location']={'account':'other','bucket':'other'}
    storage.update(appmod.EPISODES_FILE,'test-id',ep)
    monkeypatch.setattr(appmod,'publish_feed',lambda *a,**kw:pytest.fail('remote mutation'))
    assert client.post('/delete/test-id').status_code==400
    assert not appmod.find_episode('test-id').get('delete_pending')


def test_legacy_r2_adoption_requires_object_presence(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_url':'https://old.test/audio/test-id.mp3','file_size':5})
    (appmod.AUDIO_DIR/'test-id.mp3').write_bytes(b'audio')
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(head_object=lambda **kw:(_ for _ in ()).throw(RuntimeError('missing'))))
    assert client.post('/adopt-r2/test-id').status_code==500
    assert not appmod.find_episode('test-id').get('r2_location')
    import io
    seen=[]
    def head(**kw):
        seen.append(kw)
        return {'ContentLength':5}
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(head_object=head,
        get_object=lambda **kw:{'ContentLength':5,'Body':io.BytesIO(b'audio')}))
    assert client.post('/adopt-r2/test-id').status_code==200
    assert seen[0]['Key']=='audio/test-id.mp3'
    assert appmod.find_episode('test-id')['r2_location']==appmod.r2_location()


def test_obsidian_readable_stable_name_heading_link(appmod,episode,monkeypatch,tmp_path):
    monkeypatch.setattr(appmod,'OBSIDIAN_VAULT_PATH',str(tmp_path))
    ep=dict(episode,title='Readable title',r2_url='https://example.test/audio/episode.mp3')
    appmod.save_to_obsidian(ep)
    saved=appmod.find_episode(ep['slug']);name=saved['obsidian_file']
    assert name.startswith('Readable title-')
    note=(tmp_path/name).read_text(encoding='utf-8')
    assert '# Readable title' in note and '[Listen to episode](<https://example.test/audio/episode.mp3>)' in note
    saved.update(title='Changed title')
    appmod.save_to_obsidian(saved)
    assert len(list(tmp_path.glob('*.md')))==1
    assert '# Changed title' in (tmp_path/name).read_text(encoding='utf-8')


def test_fenced_metadata(appmod,monkeypatch):
    monkeypatch.setattr(appmod,'complete_message',lambda *a,**kw:'```json\n{"authors":["Author"],"topics":["Topic"]}\n```')
    assert appmod.extract_metadata('text','model',[])['authors']==['Author']


def test_delete_feed_preparation_failure_does_not_mark_pending(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_location':appmod.r2_location(),
        'r2_key':'audio/test-id.mp3','r2_url':'https://old.test/audio/test-id.mp3'})
    monkeypatch.setattr(appmod,'build_rss',lambda *a:(_ for _ in ()).throw(ValueError('bad feed')))
    assert client.post('/delete/test-id').status_code==502
    assert not appmod.find_episode('test-id').get('delete_pending')


def test_delete_upload_uncertainty_retains_pending_and_retry_works(appmod,client,episode,monkeypatch,tmp_path):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    monkeypatch.setattr(appmod,'BASE_DIR',tmp_path)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_location':appmod.r2_location(),
        'r2_key':'audio/test-id.mp3','r2_url':'https://old.test/audio/test-id.mp3'})
    monkeypatch.setattr(appmod,'upload_to_r2',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('unknown outcome')))
    assert client.post('/delete/test-id').status_code==502
    assert appmod.find_episode('test-id')['delete_pending']
    monkeypatch.setattr(appmod,'upload_to_r2',lambda *a,**kw:'https://example.test/feed.xml')
    deleted=[]
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(delete_object=lambda **kw:deleted.append(kw['Key'])))
    assert client.post('/delete/test-id').status_code==200
    assert deleted==['audio/test-id.mp3'] and not appmod.load_episodes()


def test_delete_preserves_shared_legacy_remote_audio(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    fields={'r2_location':appmod.r2_location(),'r2_key':'audio/shared.mp3','r2_url':'https://old.test/audio/shared.mp3'}
    storage.update(appmod.EPISODES_FILE,'test-id',fields)
    storage.insert(appmod.EPISODES_FILE,dict(episode,slug='other',**fields))
    monkeypatch.setattr(appmod,'publish_feed',lambda *a,**kw:None)
    monkeypatch.setattr(appmod,'get_r2_client',lambda:pytest.fail('must not delete shared remote media'))
    assert client.post('/delete/test-id').status_code==200
    assert appmod.find_episode('other')


def test_pdf_worker_keeps_specific_validation_message(appmod):
    import io
    from pypdf import PdfWriter
    writer=PdfWriter()
    for _ in range(101):writer.add_blank_page(width=100,height=100)
    data=io.BytesIO();writer.write(data)
    with pytest.raises(appmod.UserError,match='100 pages'):
        appmod.extract_text_from_pdf(data.getvalue())


def test_pdf_stream_bomb_still_bounded():
    import io, zlib
    import pdf_text
    from pypdf import PdfWriter, get_configuration
    from pypdf.generic import EncodedStreamObject, NameObject
    from pypdf.errors import LimitReachedError
    original = get_configuration()
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = EncodedStreamObject()
    stream._data = zlib.compress(b'x'*(pdf_text.MAX_STREAM_BYTES+1000))
    stream[NameObject('/Filter')] = NameObject('/FlateDecode')
    page[NameObject('/Contents')] = writer._add_object(stream)
    data = io.BytesIO(); writer.write(data)
    with pytest.raises(LimitReachedError):
        pdf_text.extract(data.getvalue())
    assert get_configuration() == original
