import io
import pytest


def test_pages_and_csrf(appmod, client, episode):
    assert client.get('/').status_code == 200
    assert client.get('/library').status_code == 200
    naked = appmod.app.test_client()
    assert naked.post('/delete/test-id').status_code == 403
    assert client.post('/delete/test-id',headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/delete/test-id',headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.get('/',headers={'Host':'evil.example'}).status_code == 400
    assert client.get('/',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code == 403
    assert len(appmod.load_episodes()) == 1


@pytest.mark.parametrize('slug',['..%5C..%5Cvictim','..%2Fvictim','%2e%2e','CON','%3Cscript%3E'])
def test_unsafe_ids(client,slug):
    assert client.post('/delete/'+slug).status_code in (400,404)


def test_stored_xss_escaped(appmod,client,episode):
    payload='<img src=x onerror="alert(1)">'
    appmod.storage.update(appmod.EPISODES_FILE,episode['slug'],dict(summary=payload,title=payload,topics=[payload]))
    html=client.get('/library').text
    assert payload not in html
    assert '&lt;img' in html


def test_traversal_downloads(client):
    for url in ['/static/audio/../../.env','/static/pdfs/../../app.py']:
        assert client.get(url).status_code == 404


def test_missing_episode_does_not_delete_file(appmod, client):
    p=appmod.AUDIO_DIR/'unknown.mp3';p.write_bytes(b'keep')
    assert client.post('/delete/unknown').status_code == 404
    assert p.exists()


def test_oversized_request_rejected(client):
    assert client.post('/generate-script',data=b'x'*(21*1024*1024),content_type='application/octet-stream').status_code == 413


def test_r2_example_is_disabled():
    from pathlib import Path
    from dotenv import dotenv_values
    config=dotenv_values(Path(__file__).resolve().parents[1]/'.env.example')
    assert all(not config[key] for key in ['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_KEY','R2_PUBLIC_URL'])
