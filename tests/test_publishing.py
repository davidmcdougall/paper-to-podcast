import xml.etree.ElementTree as ET
import pytest


def test_rss_escaping_and_draft_exclusion(appmod,episode,monkeypatch):
    monkeypatch.setattr(appmod,'PODCAST_TITLE','A & B <show>')
    assert not ET.fromstring(appmod.build_rss([episode])).findall('./channel/item')
    ep=dict(episode,title='A < B',show_notes='x & y <z>',r2_url='https://example.test/a.mp3?x=1&y=2',file_size=10)
    rss=ET.fromstring(appmod.build_rss([ep]))
    assert rss.findtext('./channel/title')=='A & B <show>'
    assert rss.findtext('./channel/item/title')=='A < B'
    assert rss.findtext('./channel/item/description')=='x & y <z>'
    assert rss.find('./channel/link') is not None


def test_retry_publish_does_not_generate(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    monkeypatch.setattr(appmod,'R2_PUBLIC_URL','https://example.test')
    path=appmod.AUDIO_DIR/'test-id.mp3';path.write_bytes(b'audio')
    appmod.storage.update(appmod.EPISODES_FILE,'test-id',{'file_size':5,'audio_url':'/static/audio/test-id.mp3'})
    monkeypatch.setattr(appmod,'text_to_speech',lambda *a:pytest.fail('repeated TTS'))
    monkeypatch.setattr(appmod,'upload_to_r2',lambda *a,**k:'https://example.test/audio/test-id.mp3')
    monkeypatch.setattr(appmod,'publish_feed',lambda *a,**kw:None)
    r=client.post('/publish/test-id')
    assert r.status_code==200 and r.json['feed_published']


def test_failed_remote_delete_keeps_record(appmod,client,episode,monkeypatch):
    monkeypatch.setattr(appmod,'R2_ENABLED',True)
    monkeypatch.setattr(appmod,'R2_PUBLIC_URL','https://example.test')
    appmod.storage.update(appmod.EPISODES_FILE,'test-id',{'r2_url':'https://example.test/audio/test-id.mp3','file_size':10})
    monkeypatch.setattr(appmod,'publish_feed',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError()))
    assert client.post('/delete/test-id').status_code==502
    assert appmod.find_episode('test-id')


def test_obsidian_frontmatter_escapes(appmod,episode,monkeypatch,tmp_path):
    monkeypatch.setattr(appmod,'OBSIDIAN_VAULT_PATH',str(tmp_path))
    ep=dict(episode,title='"\nmalicious: value',authors=['a"\nb'],topics=['x\ny'])
    assert appmod.save_to_obsidian(ep)
    note=(tmp_path/appmod.find_episode('test-id')['obsidian_file']).read_text(encoding='utf-8')
    assert '\nmalicious:' not in note and '\\nmalicious:' in note
