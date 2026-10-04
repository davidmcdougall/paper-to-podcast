import io
from types import SimpleNamespace as N
import pytest
from pypdf import PdfWriter


def test_real_pdf_extraction(appmod,pdf):
    assert 'Research evidence' in appmod.extract_text_from_pdf(pdf)


def test_bad_and_scanned_pdf(appmod):
    with pytest.raises(appmod.UserError):appmod.extract_text_from_pdf(b'bad')
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);b=io.BytesIO();writer.write(b)
    with pytest.raises(appmod.UserError):appmod.extract_text_from_pdf(b.getvalue())


def test_missing_keys_before_spending(appmod,client,pdf,monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY','')
    monkeypatch.setattr(appmod,'_prepare_episode',lambda *a:pytest.fail('must not spend'))
    assert client.post('/generate',data={'pdf':(io.BytesIO(pdf),'paper.pdf')}).status_code==400


def test_script_only_and_same_title_do_not_overwrite(appmod,client,pdf,fake_generation):
    for _ in range(2):
        r=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf'),'custom_title':'Same'})
        assert r.status_code==200
    assert len(appmod.load_episodes())==2
    assert len({e['slug'] for e in appmod.load_episodes()})==2


def test_tts_failure_returns_saved_draft(appmod,client,pdf,fake_generation,monkeypatch):
    monkeypatch.setattr(appmod,'text_to_speech',lambda *a:(_ for _ in ()).throw(RuntimeError('provider down')))
    r=client.post('/generate',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert r.status_code==502
    assert r.json['draft']['script']
    assert appmod.load_episodes()[0]['file_size']==0


def test_failed_stream_keeps_old_audio(appmod,monkeypatch):
    path=appmod.AUDIO_DIR/'existing.mp3';path.write_bytes(b'original')
    def broken(**kwargs):
        yield b'partial'
        raise RuntimeError('connection lost')
    monkeypatch.setattr(appmod,'get_voice_id',lambda c:'voice')
    monkeypatch.setattr(appmod,'ElevenLabs',lambda **k:N(text_to_speech=N(convert=broken)))
    with pytest.raises(RuntimeError):appmod.text_to_speech('text','existing.mp3')
    assert path.read_bytes()==b'original'
    assert list(appmod.AUDIO_DIR.iterdir())==[path]


def test_tts_limit_before_provider_call(appmod,monkeypatch):
    monkeypatch.setattr(appmod,'ElevenLabs',lambda **kw:pytest.fail('must not call provider'))
    with pytest.raises(appmod.UserError):appmod.text_to_speech('x'*10001,'new.mp3','eleven_multilingual_v2')


def test_failed_metadata_commit_keeps_old_audio(appmod,episode,monkeypatch):
    original=appmod.AUDIO_DIR/'test-id.mp3';original.write_bytes(b'original')
    def tts(script,filename,model):
        p=appmod.AUDIO_DIR/filename;p.write_bytes(b'new');return p
    monkeypatch.setattr(appmod,'text_to_speech',tts)
    monkeypatch.setattr(appmod,'get_audio_duration',lambda p:10)
    monkeypatch.setattr(appmod.storage,'update',lambda *a:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):appmod.voice_episode(episode,'eleven_turbo_v2_5')
    assert list(appmod.AUDIO_DIR.iterdir())==[original]
    assert appmod.find_episode('test-id')['audio_url']==''


def test_successful_full_generation(appmod,client,pdf,fake_generation,monkeypatch):
    def tts(script,filename,model):
        p=appmod.AUDIO_DIR/filename;p.write_bytes(b'audio');return p
    monkeypatch.setattr(appmod,'text_to_speech',tts)
    monkeypatch.setattr(appmod,'get_audio_duration',lambda p:9.5)
    r=client.post('/generate',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert r.status_code==200
    assert r.json['audio_ready'] and r.json['duration']==9.5
    assert len(appmod.load_episodes())==1


def test_optional_failure_is_visible(appmod,client,pdf,fake_generation,monkeypatch):
    monkeypatch.setattr(appmod,'generate_summary',lambda *a:(_ for _ in ()).throw(RuntimeError()))
    r=client.post('/generate-script',data={'pdf':(io.BytesIO(pdf),'paper.pdf')})
    assert r.status_code==200
    assert any('Summary failed' in w for w in r.json['warnings'])
    assert appmod.load_episodes()[0]['script']


def test_tinytag_duration_reader(appmod,tmp_path):
    # Synthetic MPEG-1 Layer III frames, 128 kbps / 44.1 kHz, test metadata only.
    p=tmp_path/'test.mp3'
    p.write_bytes((b'\xff\xfb\x90\x00'+bytes(413))*40)
    assert .5 < appmod.get_audio_duration(p) < 2
