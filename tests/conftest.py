import io
import sys
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as application


@pytest.fixture
def appmod(tmp_path, monkeypatch):
    a = application
    monkeypatch.setattr(a, 'AUDIO_DIR', tmp_path/'audio'); a.AUDIO_DIR.mkdir()
    monkeypatch.setattr(a, 'PDF_DIR', tmp_path/'pdf'); a.PDF_DIR.mkdir()
    monkeypatch.setattr(a, 'EPISODES_FILE', tmp_path/'episodes.json')
    monkeypatch.setattr(a, 'BASE_DIR', Path(a.__file__).resolve().parent)
    monkeypatch.setattr(a, 'ANTHROPIC_API_KEY', 'test-anthropic-key')
    monkeypatch.setattr(a, 'ELEVENLABS_API_KEY', 'test-eleven-key')
    monkeypatch.setattr(a, 'OBSIDIAN_VAULT_PATH', '')
    monkeypatch.setattr(a, 'get_voice_id', lambda client: 'test-voice')
    monkeypatch.setattr(a, 'R2_ENABLED', False)
    monkeypatch.setattr(a, 'R2_CONFIG_ERROR', False)
    monkeypatch.setattr(a, '_MODEL_CACHE', {'until':0, 'ids':[], 'error':None})
    for key in ['TEXT_MODEL','FAST_MODEL','TEXT_MODEL_OPTIONS']:
        monkeypatch.delenv(key, raising=False)
    a.app.config['TESTING'] = True
    return a


@pytest.fixture
def client(appmod):
    c = appmod.app.test_client()
    c.get('/')
    with c.session_transaction() as session:
        token = session['csrf_token']
    c.environ_base['HTTP_X_CSRF_TOKEN'] = token
    return c


@pytest.fixture
def episode(appmod):
    ep = dict(slug='test-id', title='Original', script='A complete script.', summary='A summary',
              pdf_name='source.pdf', pdf_url='/static/pdfs/test-id.pdf', authors=[], topics=[],
              show_notes='Notes', word_count=3, date='2026-10-01T12:00:00+00:00',
              audio_url='', r2_url=None, file_size=0, duration=0, tts_model='eleven_turbo_v2_5')
    appmod.storage.insert(appmod.EPISODES_FILE, ep)
    return ep


@pytest.fixture
def pdf():
    writer = PdfWriter(); page = writer.add_blank_page(width=600,height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 700 Td ('+b'Research evidence and limitations. '*20+b') Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    out=io.BytesIO();writer.write(out);return out.getvalue()


@pytest.fixture
def fake_generation(appmod, monkeypatch):
    monkeypatch.setattr(appmod,'resolve_models',lambda form: ('writing-model','fast-model'))
    monkeypatch.setattr(appmod,'generate_podcast_script',lambda *a,**k:'A complete spoken script. '*30)
    monkeypatch.setattr(appmod,'generate_summary',lambda *a:'Summary')
    monkeypatch.setattr(appmod,'extract_metadata',lambda *a:{'authors':['Author'], 'topics':['Topic']})
    monkeypatch.setattr(appmod,'generate_show_notes',lambda *a:'Show notes')
