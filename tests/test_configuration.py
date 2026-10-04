"""PR-A: isolated local configuration; never touch a real keychain or provider."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import configuration as module
from configuration import Configuration, ConfigurationError
from credential_store import KeychainUnavailable, endpoint_identity
from library_locations import manifest, move_library


class MemoryKeychain:
    def __init__(self):
        self.values = {}
        self.reads = 0
        self.offline = False

    def get_password(self, service, name):
        self.reads += 1
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        if self.offline:
            raise RuntimeError(value)
        self.values[service, name] = value


@pytest.fixture
def config(tmp_path):
    base = tmp_path/'install'; base.mkdir()
    dirs = SimpleNamespace(user_config_dir=tmp_path/'configuration', user_data_dir=tmp_path/'data')
    return Configuration(base, environ={}, dirs=dirs, keychain=MemoryKeychain())


def reload(config):
    return Configuration(config.base, environ=config.environ,
                         dirs=SimpleNamespace(user_config_dir=config.locations.config,
                                              user_data_dir=config.locations.data),
                         keychain=config.credentials._keychain)


def test_settings_precedence_and_env_does_not_get_mutated(config):
    config.locations.legacy_env.write_text('PODCAST_TITLE=Legacy\nTEXT_MODEL=legacy-model\n')
    config.save({'settings': {'podcast_title': 'Saved'}})
    assert config.get('PODCAST_TITLE') == 'Saved'
    assert config.get('TEXT_MODEL') == 'legacy-model'
    assert config.get('PODCAST_AUTHOR') == 'Saved'
    config.environ['PODCAST_TITLE'] = 'Environment'
    assert config.get('PODCAST_TITLE') == 'Environment'
    assert config.snapshot().sources['PODCAST_TITLE'] == 'environment'
    config.environ['PODCAST_TITLE'] = ''
    assert config.get('PODCAST_TITLE') == ''  # explicit blank overrides lower layers
    assert 'TEXT_MODEL' not in config.environ


@pytest.mark.parametrize('content', ['broken = [', 'schema_version = 2',
    'schema_version = true', 'schema_version = 1\n[settings]\npodcast_title = 3',
    'schema_version = 1\n[settings]\nanthropic_api_key="never-store-this"'])
def test_corrupt_unknown_or_newer_settings_never_overwritten(config, content):
    config.file.parent.mkdir()
    config.file.write_text(content)
    with pytest.raises(ConfigurationError):
        config.save({'settings': {'podcast_title': 'replacement'}})
    assert config.file.read_text() == content


def test_save_preserves_other_settings_and_last_good_backup(config):
    config.save({'settings': {'podcast_title': 'One'}})
    before = config.file.read_bytes()
    config.save({'settings': {'text_model': 'pinned'}})
    assert config.file.with_suffix('.toml.bak').read_bytes() == before
    assert config.get('PODCAST_TITLE') == 'One'
    assert config.get('TEXT_MODEL') == 'pinned'


def test_lazy_secrets_and_precedence(config):
    backend = config.credentials.backend()
    config.locations.legacy_env.write_text('ANTHROPIC_API_KEY=legacy-key\n')
    config.snapshot()
    assert backend.reads == 0
    assert config.secret('ANTHROPIC_API_KEY') == 'legacy-key'
    config.credentials.save('ANTHROPIC_API_KEY', 'keychain-key')
    assert config.secret('ANTHROPIC_API_KEY') == 'keychain-key'
    config.environ['ANTHROPIC_API_KEY'] = 'env-key'
    assert config.secret('ANTHROPIC_API_KEY') == 'env-key'
    config.environ['ANTHROPIC_API_KEY'] = ''
    assert config.secret('ANTHROPIC_API_KEY') == ''
    assert not config.file.exists()
    assert not config.credentials.file.exists()


def test_plaintext_requires_explicit_consent_and_private_mode(config):
    config.credentials.backend().offline = True
    with pytest.raises(KeychainUnavailable) as exc:
        config.credentials.save('ANTHROPIC_API_KEY', 'private-secret')
    assert 'private-secret' not in str(exc.value)
    assert not config.credentials.file.exists()
    config.credentials.save('ANTHROPIC_API_KEY', 'private-secret', allow_plaintext=True)
    assert config.secret('ANTHROPIC_API_KEY') == 'private-secret'
    if os.name == 'posix':
        assert config.credentials.file.stat().st_mode & 0o777 == 0o600
    assert 'private-secret' not in config.file.read_text()
    config.save({'plaintext_secrets': False})
    assert config.secret('ANTHROPIC_API_KEY') == ''


def test_corrupt_plaintext_file_is_not_replaced(config):
    config.credentials.backend().offline = True
    config.file.parent.mkdir()
    config.credentials.file.write_text('broken')
    with pytest.raises(ConfigurationError):
        config.credentials.save('ANTHROPIC_API_KEY', 'new', allow_plaintext=True)
    assert config.credentials.file.read_text() == 'broken'


def test_operation_snapshots_settings_and_lazily_resolves_credentials(config):
    config.environ.update(PODCAST_TITLE='Before', ANTHROPIC_API_KEY='before-key')
    backend = config.credentials.backend()
    with config.operation():
        assert backend.reads == 0
        assert config.secret('ANTHROPIC_API_KEY') == 'before-key'
        config.environ.update(PODCAST_TITLE='After', ANTHROPIC_API_KEY='after-key')
        assert config.get('PODCAST_TITLE') == 'Before'
        assert config.secret('ANTHROPIC_API_KEY') == 'before-key'
        with pytest.raises(ConfigurationError):
            config.save({'settings': {'podcast_title': 'Mid-operation'}})
        with pytest.raises(ConfigurationError):
            config.credentials.save('ANTHROPIC_API_KEY', 'Mid-operation')
    assert config.get('PODCAST_TITLE') == 'After'
    assert config.secret('ANTHROPIC_API_KEY') == 'after-key'
    assert config._operation.get() is None


def test_scope_includes_provider_host_and_base_path():
    a = endpoint_identity('test', 'https://EXAMPLE.test:443/v1/')
    assert a == endpoint_identity('test', 'https://example.test/v1')
    for provider, url in [('other','https://example.test/v1'),
                          ('test','https://other.test/v1'), ('test','https://example.test/v2')]:
        assert a != endpoint_identity(provider, url)
    with pytest.raises(ConfigurationError):
        endpoint_identity('test', 'http://remote.test/v1')
    assert endpoint_identity('local', 'http://127.0.0.1:1234/v1')


def test_r2_keys_are_bound_to_account_and_legacy_env_remains_unchanged(config):
    content = 'R2_ACCOUNT_ID=old-account\nR2_ACCESS_KEY_ID=old-id\nR2_SECRET_KEY=old-secret\n'
    config.locations.legacy_env.write_text(content)
    assert config.secret('R2_SECRET_KEY') == 'old-secret'
    config.save({'settings': {'r2_account_id': 'new-account'}})
    assert config.secret('R2_SECRET_KEY') == ''
    assert config.secret('R2_ACCESS_KEY_ID') == ''
    for name in ('R2_ACCESS_KEY_ID', 'R2_SECRET_KEY'):
        config.credentials.save(name, 'new-'+name)
        assert config.secret(name) == 'new-'+name
    config.save({'settings': {'r2_account_id': 'old-account'}})
    assert config.secret('R2_SECRET_KEY') == 'old-secret'
    assert config.locations.legacy_env.read_text() == content


def test_new_install_uses_user_dirs_without_writes_until_needed(config):
    assert config.locations.library == config.locations.data/'library'
    assert not config.locations.data.exists()
    assert not config.file.exists()
    config.prepare_library()
    assert (config.locations.library/'audio').is_dir()
    assert not (config.base/'static').exists()


@pytest.mark.parametrize('marker', ['.env', 'static/episodes.json', 'static/audio/old.mp3'])
def test_existing_install_keeps_its_location(config, marker):
    p=config.base/marker;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(b'unchanged')
    previous = p.read_bytes()
    new = reload(config)
    assert new.locations.library == config.base/'static'
    assert p.read_bytes() == previous
    assert not config.file.exists()


def test_explicit_data_override_and_registered_legacy_location(config, tmp_path):
    override = tmp_path/'override'
    new = Configuration(config.base, environ={'P2P_DATA_DIR': str(override)})
    assert new.locations.data == override
    assert new.locations.config == override/'config'
    assert new.locations.library == override/'library'
    with pytest.raises(ConfigurationError):
        Configuration(config.base, environ={'P2P_DATA_DIR':'relative'})
    old = tmp_path/'existing';old.mkdir()
    config.save({'paths': {'library_dir': str(old), 'legacy_env_path': str(config.base/'.env')}})
    assert reload(config).locations.library == old


def seed_library(config):
    config.prepare_library()
    source = config.locations.library
    (source/'episodes.json').write_text(json.dumps([{'slug':'stable-id','title':'Existing'}]))
    (source/'episodes.json.bak').write_bytes(b'old backup')
    (source/'audio'/'stable-id.mp3').write_bytes(b'audio')
    (source/'pdfs'/'stable-id.pdf').write_bytes(b'pdf')
    config.locations.legacy_env.write_text('ANTHROPIC_API_KEY=leave-alone\n')
    return source


def test_explicit_move_verifies_all_files_and_keeps_original(config, tmp_path):
    source = seed_library(config)
    before = manifest(source)
    env_before = config.locations.legacy_env.read_bytes()
    dest = tmp_path/'moved'
    result = move_library(config, dest)
    assert result['files'] == len(before)
    assert manifest(dest) == before == manifest(source) == manifest(Path(result['backup']))
    assert reload(config).locations.library == dest
    assert config.locations.legacy_env.read_bytes() == env_before
    assert isinstance(json.loads((dest/'episodes.json').read_text()), list)
    with pytest.raises(ConfigurationError, match='Restart'):
        config.check_location()


def test_failed_move_never_switches_or_changes_source(config, tmp_path, monkeypatch):
    import library_locations
    source = seed_library(config);before=manifest(source)
    def fail(*args):
        raise OSError('copy failed')
    monkeypatch.setattr(library_locations.shutil, 'copy2', fail)
    with pytest.raises(OSError):
        move_library(config, tmp_path/'destination')
    assert reload(config).locations.library == source
    assert manifest(source) == before


def test_move_rejects_busy_or_nonempty_destination(config, tmp_path):
    from filelock import FileLock
    source = seed_library(config)
    with FileLock(str(config.locations.episodes)+'.operation.lock'):
        with pytest.raises(ConfigurationError, match='busy'):
            move_library(config, tmp_path/'dest')
    with pytest.raises(ConfigurationError, match='empty'):
        move_library(config, source/'nested')


def test_cache_does_not_reuse_models_after_credential_rotation(appmod, monkeypatch):
    from test_models import FakeClient
    api = FakeClient([SimpleNamespace(id='claude-sonnet-one')])
    monkeypatch.setattr(appmod, 'claude_client', lambda **kw: api)
    assert appmod.available_models() == ['claude-sonnet-one']
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'rotated-key')
    api.items = [SimpleNamespace(id='claude-sonnet-two')]
    assert appmod.available_models() == ['claude-sonnet-two']
    assert api.calls == 2


def test_data_routes_use_selected_library(appmod, client):
    (appmod.AUDIO_DIR/'episode.mp3').write_bytes(b'local audio')
    (appmod.PDF_DIR/'episode.pdf').write_bytes(b'local pdf')
    assert client.get('/static/audio/episode.mp3').data == b'local audio'
    assert client.get('/static/pdfs/episode.pdf').data == b'local pdf'


def test_keychain_error_does_not_leak_to_logs(config, caplog):
    config.credentials.backend().offline = True
    with pytest.raises(KeychainUnavailable):
        config.credentials.save('ANTHROPIC_API_KEY', 'must-not-appear')
    assert 'must-not-appear' not in caplog.text


def test_settings_replace_failure_keeps_last_good(config, monkeypatch):
    config.save({'settings': {'podcast_title': 'Keep'}})
    before = config.file.read_bytes()
    replace = module.storage.atomic_write
    def fail(path, data):
        if path == config.file:
            raise OSError('replace failed')
        return replace(path, data)
    monkeypatch.setattr(module.storage, 'atomic_write', fail)
    with pytest.raises(OSError):
        config.save({'settings': {'podcast_title': 'Lost'}})
    assert config.file.read_bytes() == before


def test_move_copy_corruption_never_switches(config, tmp_path, monkeypatch):
    import library_locations
    source = seed_library(config);before = manifest(source)
    original = library_locations.shutil.copy2
    def corrupt(src, dest):
        original(src, dest)
        if Path(dest).parent == tmp_path/'target':
            Path(dest).write_bytes(b'corrupt')
    monkeypatch.setattr(library_locations.shutil, 'copy2', corrupt)
    with pytest.raises(ConfigurationError, match='verification'):
        move_library(config, tmp_path/'target')
    assert reload(config).locations.library == source
    assert manifest(source) == before


def test_missing_registered_library_never_becomes_empty(config, tmp_path):
    missing = tmp_path/'unmounted'
    config.save({'paths': {'library_dir': str(missing)}})
    with pytest.raises(ConfigurationError, match='missing'):
        reload(config)
    assert not missing.exists()


def test_config_and_secret_edits_refuse_running_operation(config):
    import threading
    failures = []
    def edit():
        for action in (lambda: config.save({'settings': {'podcast_title':'Race'}}),
                       lambda: config.credentials.save('ANTHROPIC_API_KEY','Race')):
            try:
                action()
            except ConfigurationError:
                failures.append(True)
    with config.operation():
        thread=threading.Thread(target=edit);thread.start();thread.join(timeout=2)
        assert not thread.is_alive()
    assert len(failures) == 2
    assert config.get('PODCAST_TITLE') != 'Race'


def test_zero_key_startup_and_pages_are_offline(tmp_path):
    import subprocess
    import sys
    environment = dict(os.environ)
    for name in set(module.DEFAULTS) | module.SECRET_NAMES:
        environment.pop(name, None)
    environment['P2P_DATA_DIR'] = str(tmp_path/'fresh')
    script = '''
import socket
import credential_store
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected network or keychain access')
socket.socket.connect = forbidden
socket.create_connection = forbidden
credential_store.native_keychain = forbidden
import app
client = app.app.test_client()
assert client.get('/').status_code == 200
assert client.get('/library').status_code == 200
assert client.get('/episodes.json').json == []
'''
    result = subprocess.run([sys.executable, '-c', script], env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_failed_rotation_cannot_be_hidden_by_plaintext_fallback(config):
    config.credentials.save('ANTHROPIC_API_KEY', 'old-key')
    config.credentials.backend().offline = True
    with pytest.raises(KeychainUnavailable, match='could not be replaced'):
        config.credentials.save('ANTHROPIC_API_KEY', 'new-key', allow_plaintext=True)
    assert not config.credentials.file.exists()
    assert config.secret('ANTHROPIC_API_KEY') == 'old-key'


def test_anthropic_sdk_cannot_forward_key_to_env_endpoint_or_redirect(appmod, monkeypatch):
    import httpx2
    calls = []
    def transport(request):
        calls.append(str(request.url))
        return httpx2.Response(302, headers={'Location':'https://different.test/models'})
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://different.test')
    monkeypatch.setattr(appmod.anthropic, 'DefaultHttpxClient',
                        lambda **kw: httpx2.Client(transport=httpx2.MockTransport(transport), **kw))
    with appmod.claude_client() as client:
        with pytest.raises(Exception):
            list(client.models.list())
    assert len(calls) == 1
    assert calls[0].startswith('https://api.anthropic.com/')


def test_invalid_optional_r2_config_keeps_library_usable(appmod, client, monkeypatch):
    monkeypatch.setenv('R2_ACCOUNT_ID', 'invalid/account')
    monkeypatch.setattr(appmod, 'r2_enabled', lambda: appmod.r2_state()[0])
    assert appmod.r2_state() == (False, True)
    assert client.get('/library').status_code == 200


def test_first_library_registration_survives_later_dotenv(config):
    config.environ['ANTHROPIC_API_KEY'] = 'environment-key'
    config.prepare_library()
    before = b'[{"slug":"existing","title":"Keep visible"}]'
    config.locations.episodes.write_bytes(before)
    config.locations.legacy_env.write_text('ANTHROPIC_API_KEY=later-env-key\n')
    restarted = reload(config)
    restarted.prepare_library()
    assert restarted.locations.library == config.locations.library
    assert restarted.locations.episodes.read_bytes() == before
    assert not (config.base/'static').exists()
    assert restarted.read()['paths']['library_dir'] == str(config.locations.library)


def test_unregistered_ambiguous_libraries_are_not_guessed(config):
    for root in (config.base/'static', config.locations.data/'library'):
        root.mkdir(parents=True)
        (root/'episodes.json').write_bytes(b'[]')
    with pytest.raises(ConfigurationError, match='Two libraries'):
        reload(config)
    assert not config.file.exists()


def test_unregistered_user_library_beats_later_dotenv(config):
    config.locations.library.mkdir(parents=True)
    config.locations.episodes.write_bytes(b'[]')
    config.locations.legacy_env.write_text('PODCAST_TITLE=Later')
    assert reload(config).locations.library == config.locations.library


@pytest.mark.parametrize('plaintext', [False, True])
def test_keychain_read_error_never_falls_through(config, monkeypatch, plaintext):
    config.locations.legacy_env.write_text('ANTHROPIC_API_KEY=retired-key\n')
    config.credentials.save('ANTHROPIC_API_KEY', 'current-key')
    if plaintext:
        config.save({'plaintext_secrets': True})
    def locked(*args):
        raise RuntimeError('sensitive backend text')
    monkeypatch.setattr(config.credentials.backend(), 'get_password', locked)
    monkeypatch.setattr(config.credentials, 'local', lambda: pytest.fail('must not try plaintext'))
    monkeypatch.setattr(config, 'legacy', lambda: pytest.fail('must not try legacy'))
    with pytest.raises(KeychainUnavailable, match='Unlock the keychain') as exc:
        config.secret('ANTHROPIC_API_KEY')
    assert 'sensitive' not in str(exc.value)


@pytest.mark.parametrize('status', [403, None, 'secret-status'])
def test_safe_failure_log_contains_diagnostics_without_bodies(appmod, caplog, status):
    class ProviderFailure(Exception):
        status_code = status
    try:
        raise ProviderFailure('SECRET BODY WITH API KEY')
    except ProviderFailure:
        appmod.log_failure('%s generation failed', 'Script')
    assert 'exception=ProviderFailure' in caplog.text
    assert f'http_status={status if type(status) is int else None}' in caplog.text
    assert 'SECRET BODY' not in caplog.text
    assert 'secret-status' not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
