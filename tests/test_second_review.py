"""Regression cases from the second independent review."""
import io
import json
from types import SimpleNamespace as N
import xml.etree.ElementTree as ET
import pytest
import storage


@pytest.mark.parametrize('remote,reported_size',[(b'wrong',5),(b'different-size',14)])
def test_adoption_rejects_wrong_audio_and_never_adopts_or_deletes(appmod,client,episode,monkeypatch,remote,reported_size):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_url':'https://old.test/audio/test-id.mp3','file_size':5})
    (appmod.AUDIO_DIR/'test-id.mp3').write_bytes(b'audio')
    body=io.BytesIO(remote)
    api=N(head_object=lambda **kw:{'ContentLength':reported_size},
          get_object=lambda **kw:{'ContentLength':reported_size,'Body':body},
          delete_object=lambda **kw:pytest.fail('must not delete during verification'))
    monkeypatch.setattr(appmod,'get_r2_client',lambda:api)
    response=client.post('/adopt-r2/test-id')
    assert response.status_code==400
    assert not appmod.find_episode('test-id').get('r2_location')
    if reported_size==5:assert body.closed
    assert client.post('/delete/test-id').status_code==400


def test_adoption_refuses_missing_local_original(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_url':'https://old.test/audio/test-id.mp3','file_size':5})
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(head_object=lambda **kw:pytest.fail('no original')))
    assert client.post('/adopt-r2/test-id').status_code==400
    assert not appmod.find_episode('test-id').get('r2_location')


def test_adoption_verifies_every_retained_key_before_saving(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    storage.update(appmod.EPISODES_FILE,'test-id',{'r2_url':'https://old.test/audio/test-id.mp3','file_size':5,
        'remote_keys':['audio/older.mp3','audio/test-id.mp3']})
    (appmod.AUDIO_DIR/'test-id.mp3').write_bytes(b'audio')
    (appmod.AUDIO_DIR/'older.mp3').write_bytes(b'older')
    def get(**kw):return {'ContentLength':5,'Body':io.BytesIO(b'wrong' if 'older' in kw['Key'] else b'audio')}
    monkeypatch.setattr(appmod,'get_r2_client',lambda:N(head_object=lambda **kw:{'ContentLength':5},get_object=get))
    assert client.post('/adopt-r2/test-id').status_code==400
    assert not appmod.find_episode('test-id').get('r2_location')


@pytest.mark.parametrize('target,cap',[(450,12000),(None,15000),(6000,36000)])
def test_source_cost_cap_preserves_original_middle_and_one_warning(appmod,monkeypatch,target,cap):
    from test_models import FakeClient
    calls=[]
    def create(**kw):
        calls.append(kw['messages'][0]['content'])
        return N(content=[N(type='text',text='Complete script')],stop_reason='end_turn',usage=N(input_tokens=1,output_tokens=1))
    api=FakeClient([])
    api.messages=N(count_tokens=lambda **kw:N(input_tokens=len(kw['messages'][0]['content'])//2),create=create)
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:api)
    source='START '+('research '*20000)+'MIDDLE '+('evidence '*20000)+'END'
    warnings=[]
    appmod.generate_podcast_script(source,target_words=target,model='writing',fast='fast',warnings=warnings)
    sampled=calls[0].split('Paper source:\n',1)[1]
    assert len(sampled.split())<=cap+2  # Two omission markers.
    assert 'START' in sampled and 'MIDDLE' in sampled and 'END' in sampled
    assert len([w for w in warnings if 'sample' in w.lower()])==1


def test_copy_failure_keeps_library_usable_and_removes_partial_target(appmod,monkeypatch):
    appmod.EPISODES_FILE.write_text('[{"slug":"legacy"},{"slug":"legacy"},{"slug":"healthy"}]',encoding='utf-8')
    (appmod.AUDIO_DIR/'legacy.mp3').write_bytes(b'original')
    def fail_copy(source,target):
        target.write_bytes(b'partial')
        raise PermissionError('locked')
    monkeypatch.setattr(storage.shutil,'copyfile',fail_copy)
    data=appmod.load_episodes()
    migrated=next(ep for ep in data if ep.get('legacy_slug')=='legacy')
    assert migrated['audio_url']=='' and migrated['file_size']==0
    assert any('copy failed' in w for w in migrated['warnings'])
    assert not (appmod.AUDIO_DIR/(migrated['slug']+'.mp3')).exists()
    assert (appmod.AUDIO_DIR/'legacy.mp3').read_bytes()==b'original'
    assert appmod.load_episodes()==data
    storage.insert(appmod.EPISODES_FILE,{'slug':'new'})
    assert len(appmod.load_episodes())==4


def test_every_migration_has_its_own_snapshot(appmod):
    snapshots=[]
    for slug in ['', 'con']:
        before=json.dumps([{'slug':slug}])
        appmod.EPISODES_FILE.write_text(before,encoding='utf-8')
        appmod.load_episodes();snapshots.append(before)
    backups=list(appmod.EPISODES_FILE.parent.glob('episodes.json.migration.*.bak'))
    assert len(backups)==2
    assert sorted(p.read_text(encoding='utf-8') for p in backups)==sorted(snapshots)


def test_unique_legacy_guid_is_retained_and_duplicate_guids_are_unique(appmod,episode):
    records=[dict(episode,slug=slug,r2_url='https://example.test/audio/source.mp3',file_size=5) for slug in ['con','dup','dup','']]
    appmod.EPISODES_FILE.write_text(json.dumps(records),encoding='utf-8')
    migrated=appmod.load_episodes()
    guids=[node.text for node in ET.fromstring(appmod.build_rss(migrated)).findall('./channel/item/guid')]
    assert 'con' in guids and len(guids)==len(set(guids))==4


def test_legacy_obsidian_names_do_not_collide_or_overwrite_old_notes(appmod,episode,monkeypatch,tmp_path):
    monkeypatch.setattr(appmod,'OBSIDIAN_VAULT_PATH',str(tmp_path))
    old=tmp_path/'sameprefix-first.md';old.write_text('Hand edited v1 note',encoding='utf-8')
    for slug in ['sameprefix-first','sameprefix-second']:
        ep=dict(episode,slug=slug,title='Same title')
        storage.insert(appmod.EPISODES_FILE,ep)
        appmod.save_to_obsidian(ep)
    files=[appmod.find_episode(slug)['obsidian_file'] for slug in ['sameprefix-first','sameprefix-second']]
    assert len(set(files))==2 and all((tmp_path/name).is_file() for name in files)
    assert old.read_text(encoding='utf-8')=='Hand edited v1 note'


def test_obsidian_refuses_another_episodes_assigned_name(appmod,episode,monkeypatch,tmp_path):
    monkeypatch.setattr(appmod,'OBSIDIAN_VAULT_PATH',str(tmp_path))
    storage.update(appmod.EPISODES_FILE,episode['slug'],{'obsidian_file':'shared.md'})
    storage.insert(appmod.EPISODES_FILE,dict(episode,slug='other',obsidian_file='shared.md'))
    (tmp_path/'shared.md').write_text('Original',encoding='utf-8')
    with pytest.raises(appmod.UserError):appmod.save_to_obsidian(appmod.find_episode(episode['slug']))
    assert (tmp_path/'shared.md').read_text(encoding='utf-8')=='Original'
