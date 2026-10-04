import io
import json
from pathlib import Path
from types import SimpleNamespace as N
import pytest
import storage
from prompts import PromptStore, PromptError, REQUIRED, SAMPLE, digest, validate, AttemptJournal


@pytest.fixture
def store(tmp_path):
    return PromptStore(tmp_path)


def test_shipped_requests_match_pre_extraction_fixture(store):
    expected = json.loads((Path(__file__).parent/'fixtures/rendered_prompts.json').read_text(encoding='utf-8'))
    for name, template in store.snapshot().items():
        assert template.render(**{k:SAMPLE[k] for k in REQUIRED[name]}) == expected[name]
        assert store.historical(name, template.sha256) == template.raw


@pytest.mark.parametrize('invalid', [
    'Source {source} followed by instructions', '{source}{source}',
    '{source.__class__}', '{source!r}', '{source:>10}', '{{source}}', '{unknown}{source}',
    '{source}\x00', '{source', '}', '',
])
def test_invalid_save_preserves_edit_and_history(store, invalid):
    original = store.snapshot()['metadata']
    before = store.history('metadata')
    with pytest.raises(PromptError):
        store.save('metadata', invalid)
    assert store.snapshot()['metadata'] == original
    assert store.history('metadata') == before


@pytest.mark.parametrize('name', list(REQUIRED))
def test_each_required_field_is_required(store, name):
    original = store.snapshot()[name].raw
    for field in REQUIRED[name]:
        with pytest.raises(PromptError):
            validate(name, original.replace(('{'+field+'}').encode(), b''))


def test_utf8_size_and_unknown_names(store):
    for raw in [b'\xff{source}', b'x'*32001+b'{source}']:
        with pytest.raises(PromptError):validate('metadata', raw)
    for name in ['../metadata', 'other']:
        with pytest.raises(PromptError):store.save(name, '{source}')
        with pytest.raises(PromptError):store.history(name)


def test_inputs_with_braces_are_literal(store):
    template = store.snapshot()['show_notes']
    text = template.render(title='{source.__class__}', authors='{title}', source='{authors}')
    assert 'Paper: {source.__class__} by {title}' in text
    assert text.endswith('{authors}')


def test_edit_history_reset_and_upgrade_preserve_bytes(store, tmp_path):
    original = store.snapshot()['metadata']
    edited = 'Custom metadata instructions\r\n{source}'
    sha = store.save('metadata', edited)
    assert store.historical('metadata', sha) == edited.encode()
    shipped = tmp_path/'new-release'; shipped.mkdir()
    for name in REQUIRED:
        (shipped/(name+'.md')).write_bytes(store._default(name))
    (shipped/'metadata.md').write_bytes(b'Upgraded default\n{source}')
    upgraded = PromptStore(tmp_path, shipped)
    assert upgraded.snapshot()['metadata'].raw == edited.encode()
    upgraded.reset('metadata')
    assert upgraded.snapshot()['metadata'].raw == b'Upgraded default\n{source}'
    assert upgraded.historical('metadata', original.sha256) == original.raw
    assert upgraded.historical('metadata', sha) == edited.encode()


@pytest.mark.parametrize('damaged', [None, b'{unknown}', b'\xff', b'x'*33000],
                         ids=['missing','unknown-placeholder','invalid-utf8','oversized'])
def test_missing_invalid_external_edits_warn_without_repair(store, damaged):
    original = store.snapshot()['summary']
    path = store.root/'summary.md'
    if damaged is None:path.unlink()
    else:path.write_bytes(damaged)
    fallback = store.snapshot()['summary']
    assert fallback.raw == original.raw and fallback.warning
    if damaged is None:assert not path.exists()
    else:assert path.read_bytes() == damaged
    assert store.snapshot()['summary'].warning


def test_corrupt_archived_template_refuses_overwrite(store):
    template = store.snapshot()['metadata']
    path = store.history_root/'metadata'/(template.sha256+'.md')
    path.write_bytes(b'corrupt')
    snapshot=store.snapshot()
    assert snapshot['metadata'].error
    with pytest.raises(PromptError,match='history is corrupt'):
        snapshot['metadata'].render(source='Paper')
    assert snapshot['summary'].render(title='Paper',source='Source')
    assert path.read_bytes() == b'corrupt'


def test_snapshot_is_immutable_and_new_operations_pick_up_changes(appmod):
    store = PromptStore(appmod.configuration.locations.data)
    with appmod.configuration.operation():
        first = appmod.prompt_snapshot()['metadata']
        store.save('metadata', 'Updated instructions\n{source}')
        assert appmod.prompt_snapshot()['metadata'] == first
        with pytest.raises(TypeError):appmod.prompt_snapshot()['metadata'] = first
    with appmod.configuration.operation():
        assert appmod.prompt_snapshot()['metadata'].raw == b'Updated instructions\n{source}'


def test_preview_has_no_provider_call(store, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a,**k:pytest.fail('offline preview'))
    for name in REQUIRED:
        result=store.preview(name)
        assert result['estimated_tokens'] > 0 and 'estimate' in result['estimate_label']
    assert store.preview('metadata', 'Draft\n{source}')['text'].startswith('Draft\n')


class FakeClaude:
    def __init__(self, responses, calls):
        self.responses = iter(responses); self.calls=calls; self.messages=self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def count_tokens(self, **kwargs):return N(input_tokens=100)
    def create(self, **kwargs):
        self.calls.append(kwargs)
        result=next(self.responses)
        if isinstance(result, Exception):raise result
        return N(stop_reason='end_turn', content=[N(type='text',text=result)],
                 usage=N(input_tokens=100,output_tokens=20))


def mock_claude(appmod, monkeypatch, responses):
    calls=[]; fake=FakeClaude(responses,calls)
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:fake)
    monkeypatch.setattr(appmod,'resolve_models',lambda form:('writing','fast'))
    return calls


def test_full_generation_attempts_and_rendered_requests(appmod, client, pdf, monkeypatch):
    calls=mock_claude(appmod, monkeypatch, ['First draft', 'Edited script', 'Summary',
                      '{"authors":["Jane Smith"],"topics":["research"]}', 'Show notes'])
    result=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf'),'custom_title':'Sample paper'})
    assert result.status_code == 200
    ep=result.json
    assert [a['step'] for a in ep['generation_attempts']] == ['script','voice_edit','summary','metadata','show_notes']
    assert all(a['status']=='succeeded' for a in ep['generation_attempts'])
    assert len(calls)==5 and len(ep['usage'])==5
    journal=AttemptJournal(appmod.configuration.locations.data)
    for attempt in ep['generation_attempts']:
        persisted=json.loads((journal.root/(attempt['id']+'.json')).read_text(encoding='utf-8'))
        assert persisted == attempt
        assert attempt['template_hash'] in PromptStore(appmod.configuration.locations.data).history(attempt['step'])
        for ref in attempt['inputs'].values():
            raw=(appmod.configuration.locations.data/ref['reference']).read_bytes()
            assert digest(raw)==ref['sha256']
        assert 'test-anthropic-key' not in json.dumps(attempt)
    assert ep['source_hash']==ep['generation_attempts'][0]['inputs']['source']['sha256']


def test_failed_voice_and_metadata_are_recorded_and_paid_draft_survives(appmod, client, pdf, monkeypatch):
    mock_claude(appmod, monkeypatch, ['First draft', RuntimeError('secret provider diagnostics'),
                'Summary', '{"authors":"invalid list","topics":[]}', 'Show notes'])
    result=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert result.status_code==200
    ep=result.json
    assert ep['script']=='First draft' and ep['review_required']
    assert [a['status'] for a in ep['generation_attempts']] == ['succeeded','failed','succeeded','failed','succeeded']
    assert 'secret provider diagnostics' not in json.dumps(ep)
    assert ep['generation_attempts'][3]['usage']['output_tokens']==20


def test_failed_script_retained_in_journal_retry_takes_new_snapshot(appmod, client, pdf, monkeypatch):
    mock_claude(appmod, monkeypatch, [RuntimeError('private')])
    assert client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')}).status_code==502
    root=AttemptJournal(appmod.configuration.locations.data).root
    failed=[json.loads(p.read_text(encoding='utf-8')) for p in root.glob('*.json')]
    assert len(failed)==1 and failed[0]['status']=='failed'
    store=PromptStore(appmod.configuration.locations.data)
    original=store.snapshot()['script']
    new_sha=store.save('script','Updated wording\n'+original.raw.decode())
    mock_claude(appmod, monkeypatch, ['Draft','Edited','Summary','{"authors":[],"topics":[]}','Notes'])
    response=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert response.status_code==200
    assert response.json['generation_attempts'][0]['template_hash']==new_sha
    assert json.loads((root/(failed[0]['id']+'.json')).read_text(encoding='utf-8'))==failed[0]


def test_audit_write_failure_after_call_does_not_lose_paid_response(appmod, monkeypatch):
    mock_claude(appmod, monkeypatch, ['Paid response'])
    template=PromptStore(appmod.configuration.locations.data).snapshot()['metadata']
    original=AttemptJournal.write
    def broken(self,record):
        if record['status']=='succeeded':raise OSError('disk error')
        return original(self,record)
    monkeypatch.setattr(AttemptJournal,'write',broken)
    warnings=[]
    with appmod.configuration.operation():
        assert appmod.complete_message('model',template.render(source='Paper'),600,[],
                     template=template,inputs={'source':'Paper'},warnings=warnings)=='Paid response'
        assert appmod.operation_attempts()[0]['journal_update_failed']
    assert warnings


def test_history_failure_before_call_spends_nothing(appmod, monkeypatch):
    template=PromptStore(appmod.configuration.locations.data).snapshot()['metadata']
    monkeypatch.setattr(AttemptJournal,'write',lambda *a:(_ for _ in ()).throw(OSError('disk error')))
    monkeypatch.setattr(appmod,'claude_client',lambda *a,**k:pytest.fail('must not spend'))
    with pytest.raises(OSError):appmod.complete_message('model',template.render(source='Paper'),600,[],
                                            template=template,inputs={'source':'Paper'})


@pytest.mark.parametrize('stop_reason,text', [('max_tokens','Truncated'),('end_turn','   ')])
def test_unfinished_or_empty_response_is_failed(appmod, monkeypatch, stop_reason, text):
    fake=FakeClaude([], [])
    fake.create=lambda **kw:N(stop_reason=stop_reason,content=[N(type='text',text=text)],
                             usage=N(input_tokens=100,output_tokens=20))
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:fake)
    with appmod.configuration.operation():
        template=appmod.prompt_snapshot()['summary']
        with pytest.raises(appmod.UserError):
            appmod.complete_message('model',template.render(title='Paper',source='Source'),100,[],
                                    template=template,inputs={'title':'Paper','source':'Source'})
        assert appmod.operation_attempts()[0]['status']=='failed'


def test_sampled_request_hash_matches_actual_provider_input(appmod, monkeypatch):
    calls=mock_claude(appmod,monkeypatch,['Draft','Edited'])
    source=' '.join('word'+str(i) for i in range(18000))
    warnings=[]
    with appmod.configuration.operation():
        appmod.generate_podcast_script(source,model='writing',fast='fast',usage=[],warnings=warnings)
        attempt=appmod.operation_attempts()[0]
    actual=calls[0]['messages'][0]['content']
    assert attempt['request']['sha256']==digest(actual.encode())
    sampled=attempt['sampled_source']
    raw=(appmod.configuration.locations.data/sampled['reference']).read_bytes()
    assert sampled['sha256']==digest(raw) and actual.endswith(raw.decode())
    assert sampled['sha256'] != attempt['inputs']['source']['sha256']
    assert warnings


def test_fallback_warning_reaches_saved_episode(appmod,client,pdf,monkeypatch):
    store=PromptStore(appmod.configuration.locations.data)
    store.snapshot()
    (store.root/'summary.md').write_bytes(b'Invalid external edit')
    mock_claude(appmod,monkeypatch,['Draft','Edited','Summary','{"authors":[],"topics":[]}','Notes'])
    response=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert response.status_code==200
    assert any('summary prompt missing or invalid' in w for w in response.json['warnings'])


def test_generation_uses_pre_extraction_requests(appmod,monkeypatch):
    expected=json.loads((Path(__file__).parent/'fixtures/rendered_prompts.json').read_text(encoding='utf-8'))
    calls=mock_claude(appmod,monkeypatch,['A spoken draft.','Edited','Summary','{"authors":[],"topics":[]}','Notes'])
    with appmod.configuration.operation():
        appmod.generate_podcast_script(SAMPLE['source'],SAMPLE['notes'],model='writing',fast='fast')
        appmod.generate_summary(SAMPLE['source'],SAMPLE['title'],'writing',[])
        appmod.extract_metadata(SAMPLE['source'],'fast',[])
        appmod.generate_show_notes(SAMPLE['source'],SAMPLE['title'],['Jane Smith','John Doe'],'fast',[])
    for call,name in zip(calls,['script','voice_edit','summary','metadata','show_notes']):
        assert call['messages'][0]['content']==expected[name]


def test_library_move_keeps_prompt_history_and_inputs(tmp_path):
    from configuration import Configuration
    from library_locations import move_library, manifest
    dirs=N(user_config_dir=tmp_path/'config',user_data_dir=tmp_path/'data')
    config=Configuration(tmp_path/'install',environ={},dirs=dirs)
    config.prepare_library()
    (config.locations.library/'episodes.json').write_bytes(b'[{"slug":"stable-id","script":"Saved draft"}]')
    (config.locations.library/'audio'/'stable-id.mp3').write_bytes(b'original audio')
    store=PromptStore(config.locations.data)
    store.snapshot(); store.save('metadata','Custom\r\n{source}')
    journal=AttemptJournal(config.locations.data)
    journal.archive_input('Original source')
    before={str(p.relative_to(config.locations.data)):digest(p.read_bytes())
            for root in (store.root,journal.root) for p in root.rglob('*')
            if p.is_file() and not p.name.endswith('.lock')}
    library_before=manifest(config.locations.library)
    destination=tmp_path/'moved'
    move_library(config,destination)
    restarted=Configuration(config.base,environ={},dirs=dirs)
    assert restarted.locations.library==destination
    assert manifest(destination)==library_before
    assert PromptStore(restarted.locations.data).snapshot()['metadata'].raw==b'Custom\r\n{source}'
    after={str(p.relative_to(config.locations.data)):digest(p.read_bytes())
           for root in (store.root,journal.root) for p in root.rglob('*')
           if p.is_file() and not p.name.endswith('.lock')}
    assert before==after


def test_external_edit_during_call_does_not_change_voice_snapshot(appmod,monkeypatch):
    store=PromptStore(appmod.configuration.locations.data)
    initial=store.snapshot()['voice_edit']
    calls=mock_claude(appmod,monkeypatch,['First draft','Edited'])
    original=appmod._complete_message
    def mutate_after_first(*args,**kwargs):
        result=original(*args,**kwargs)
        if kwargs['record']['step']=='script':
            (store.root/'voice_edit.md').write_bytes(b'New voice edit\n{script}')
        return result
    monkeypatch.setattr(appmod,'_complete_message',mutate_after_first)
    with appmod.configuration.operation():
        assert appmod.generate_podcast_script('Paper',model='writing',fast='fast')=='Edited'
        assert appmod.operation_attempts()[1]['template_hash']==initial.sha256
    assert calls[1]['messages'][0]['content']==initial.render(script='First draft')
    with appmod.configuration.operation():
        assert appmod.prompt_snapshot()['voice_edit'].raw==b'New voice edit\n{script}'


@pytest.mark.parametrize('ending',['\n','\r\n',' \t\n\n'])
def test_normal_editor_save_preserves_raw_but_renders_source_last(store,ending):
    original=store.snapshot()['script']
    edited='One-word-edit\n'+original.raw.decode()+ending
    sha=store.save('script',edited)
    template=store.snapshot()['script']
    assert template.warning==''
    assert store.historical('script',sha)==edited.encode()
    assert template.render(**{k:SAMPLE[k] for k in REQUIRED['script']}).endswith(SAMPLE['source'])
    assert template.prefix(length_rule='Short',notes='').endswith('Paper source:\n')


def test_corrupt_prompt_archive_does_not_block_delete(appmod,client,episode):
    store=PromptStore(appmod.configuration.locations.data)
    template=store.snapshot()['metadata']
    path=store.history_root/'metadata'/(template.sha256+'.md')
    path.write_bytes(b'corrupt')
    response=client.post('/delete/'+episode['slug'])
    assert response.status_code==200
    assert appmod.load_episodes()==[]
    assert path.read_bytes()==b'corrupt'


def test_untouched_seed_upgrades_and_archives_old_default(store,tmp_path):
    original=store.snapshot()['metadata']
    shipped=tmp_path/'new-release';shipped.mkdir()
    for name in REQUIRED:(shipped/(name+'.md')).write_bytes(store._default(name))
    (shipped/'metadata.md').write_bytes(b'Better shipped instructions\n{source}')
    upgraded=PromptStore(tmp_path,shipped)
    current=upgraded.snapshot()['metadata']
    assert current.raw==b'Better shipped instructions\n{source}'
    assert upgraded.historical('metadata',original.sha256)==original.raw
    marker=json.loads((store.root/'.seeded').read_text(encoding='utf-8'))
    assert marker['defaults']['metadata']==current.sha256


def test_external_editor_newline_keeps_custom_prompt(store):
    store.snapshot()
    raw=b'Custom instructions\n{source}\r\n'
    (store.root/'metadata.md').write_bytes(raw)
    template=store.snapshot()['metadata']
    assert template.raw==raw and not template.warning
    assert template.render(source='Paper')=='Custom instructions\nPaper'
    assert store.historical('metadata',template.sha256)==raw


@pytest.mark.parametrize('raw,reason',[(b'Custom {unknown}','literal placeholders'),
    (b'Custom {source} trailing instructions','exactly once'),(b'\xff{source}','UTF-8')])
def test_fallback_warning_explains_specific_invalid_edit(store,raw,reason):
    store.snapshot();(store.root/'metadata.md').write_bytes(raw)
    assert reason in store.snapshot()['metadata'].warning


def test_nontext_routes_do_not_snapshot_prompts(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(PromptStore,'snapshot',lambda *a:pytest.fail('non-text operation must not access prompts'))
    assert client.post('/rename/'+episode['slug'],json={'title':'Renamed'}).status_code==200
    assert client.post('/update-meta/'+episode['slug'],json={'authors':'Jane','topics':'research'}).status_code==200
    monkeypatch.setattr(appmod,'publish_episode',lambda ep:dict(ep,audio_url='local audio'))
    assert client.post('/publish/'+episode['slug']).status_code==200
    assert client.post('/delete/'+episode['slug']).status_code==200


def test_corrupt_metadata_archive_only_blocks_metadata_pass(appmod,client,pdf,monkeypatch):
    store=PromptStore(appmod.configuration.locations.data)
    metadata=store.snapshot()['metadata']
    path=store.history_root/'metadata'/(metadata.sha256+'.md')
    path.write_bytes(b'corrupt')
    calls=mock_claude(appmod,monkeypatch,['Draft','Edited','Summary','Notes'])
    result=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert result.status_code==200 and result.json['script']=='Edited'
    assert len(calls)==4
    assert any('Metadata failed' in warning for warning in result.json['warnings'])
    assert path.read_bytes()==b'corrupt'


def test_prompt_lock_timeout_gives_specific_error(store,monkeypatch):
    import prompts
    from filelock import Timeout
    class BusyLock:
        def __enter__(self):raise Timeout('test-prompt-lock')
        def __exit__(self,*args):pass
    monkeypatch.setattr(prompts,'FileLock',lambda *a,**k:BusyLock())
    for operation in (store.snapshot,lambda:store.save('metadata','Custom\n{source}')):
        with pytest.raises(PromptError,match='Prompt storage is busy'):operation()


def test_unknown_historical_hash_is_prompt_error(store):
    store.snapshot()
    with pytest.raises(PromptError,match='was not found'):
        store.historical('metadata','0'*64)


def test_metadata_tolerates_extra_fields_and_filters_nonstrings(appmod,monkeypatch):
    mock_claude(appmod,monkeypatch,['{"authors":["Jane",42],"topics":[null,"research"],"title":"Extra"}'])
    with appmod.configuration.operation():
        assert appmod.extract_metadata('Paper','fast',[])=={'authors':['Jane'],'topics':['research']}
        assert appmod.operation_attempts()[0]['status']=='succeeded'


def test_history_update_warning_is_shown_once(appmod,client,pdf,monkeypatch):
    mock_claude(appmod,monkeypatch,['Draft','Edited','Summary','{"authors":[],"topics":[]}','Notes'])
    original=AttemptJournal.write
    def failure(self,record):
        if record['step']=='script' and record['status']=='succeeded':raise OSError('audit disk error')
        return original(self,record)
    monkeypatch.setattr(AttemptJournal,'write',failure)
    response=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert response.status_code==200
    assert response.json['warnings'].count(appmod.HISTORY_UPDATE_WARNING)==1
    assert response.json['generation_attempts'][0]['journal_update_failed']


def test_legacy_seed_marker_migrates_conservatively(store,tmp_path):
    original=store.snapshot()
    (store.root/'metadata.md').write_bytes(b'Old custom or unknown default\n{source}')
    (store.root/'.seeded').write_bytes(b'1\n')
    migrated=store.snapshot()
    assert migrated['metadata'].raw==b'Old custom or unknown default\n{source}'
    marker=json.loads((store.root/'.seeded').read_text(encoding='utf-8'))
    assert marker['defaults']['metadata'] is None
    assert marker['defaults']['script']==original['script'].sha256
    store.reset('metadata')
    marker=json.loads((store.root/'.seeded').read_text(encoding='utf-8'))
    assert marker['defaults']['metadata']==original['metadata'].sha256


@pytest.mark.parametrize('content',[b'{broken',b'{"schema_version":2,"defaults":{}}',b'false'])
def test_corrupt_seed_marker_refuses_rewrite(store,content):
    store.snapshot();marker=store.root/'.seeded';marker.write_bytes(content)
    with pytest.raises(PromptError,match='corrupt or unsupported'):store.snapshot()
    assert marker.read_bytes()==content
