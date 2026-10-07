from types import SimpleNamespace as N
import pytest
from providers import cache_scope
from providers.anthropic import AnthropicText
from providers.elevenlabs import ElevenLabsSpeech, select_voice


def test_cache_identity_includes_endpoint_and_revision():
    scope = cache_scope('https://api.anthropic.com', 'synthetic')
    assert scope == cache_scope('https://API.ANTHROPIC.COM:443/', 'synthetic')
    assert scope != cache_scope('https://api.anthropic.com/other', 'synthetic')
    assert scope != cache_scope('https://api.anthropic.com', 'rotated')
    assert 'synthetic' not in str(scope)


def test_text_transport_preserves_request():
    requests = []
    def call(**kw):
        requests.append(kw)
        return N(input_tokens=7)
    provider = AnthropicText(N(messages=N(create=call, count_tokens=call)))
    request = dict(model='pinned', max_tokens=30, system='rules', messages=[dict(role='user', content='exact bytes\n')])
    provider.complete(**request)
    provider.count_tokens(**{k:v for k,v in request.items() if k != 'max_tokens'})
    assert requests[0] == request
    assert requests[1]['messages'] == request['messages']


def test_voice_listing_and_selection():
    voices = [N(voice_id='first')]
    checked = []
    client = N(voices=N(get_all=lambda:N(voices=voices), get=checked.append))
    assert ElevenLabsSpeech(client).list_voices() == voices
    assert select_voice(client, '') == 'first'
    assert select_voice(client, 'pin') == 'pin'
    assert checked == ['pin']


def test_failed_stream_removes_temporary(tmp_path):
    def chunks():
        yield b'partial'
        raise RuntimeError('stream failed')
    provider = ElevenLabsSpeech(N(text_to_speech=N(convert=lambda **kw:chunks())))
    with pytest.raises(RuntimeError):
        provider.synthesize('script', 'voice', 'eleven_flash_v2_5', tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_speech_returns_temporary_and_preserves_settings(tmp_path):
    requests = []
    def convert(**kw):
        requests.append(kw)
        return [b'a', b'', b'b']
    path = ElevenLabsSpeech(N(text_to_speech=N(convert=convert))).synthesize('script', 'voice', 'eleven_flash_v2_5', tmp_path)
    assert path.read_bytes() == b'ab'
    assert path.name.startswith('.pending-')
    assert requests[0]['output_format'] == 'mp3_44100_128'
    assert requests[0]['voice_settings'].speed == 1.15


def test_rotation_discards_discovery_and_model_limits(appmod, monkeypatch):
    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        models = N(list=lambda **kw: calls.append(1) or [N(id='claude-sonnet-test')])
    monkeypatch.setattr(appmod, 'claude_client', lambda **kw:Client())
    appmod.available_models()
    appmod._MODEL_INFO['old'] = N(max_tokens=1)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'rotated-synthetic')
    appmod.available_models()
    assert len(calls) == 2
    assert appmod._MODEL_INFO == {}


def test_text_client_security_defaults(monkeypatch):
    import providers.anthropic as adapter
    requests = []
    monkeypatch.setattr(adapter.anthropic, 'DefaultHttpxClient', lambda **kw:kw)
    monkeypatch.setattr(adapter.anthropic, 'Anthropic', lambda **kw:requests.append(kw))
    adapter.create_client('synthetic', discovery=True)
    adapter.create_client('synthetic')
    assert [r['timeout'] for r in requests] == [8.0, 120.0]
    assert all(r['max_retries'] == 0 and r['http_client']['follow_redirects'] is False for r in requests)
    assert all(r['base_url'] == adapter.ENDPOINT for r in requests)


def test_empty_voice_account():
    with pytest.raises(RuntimeError, match='No voices'):
        select_voice(N(voices=N(get_all=lambda:N(voices=[]))), '')
