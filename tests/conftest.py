import io
import os
import tempfile
from dataclasses import replace
import sys
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Never read a developer's .env/keychain or create their library during collection.
_test_home = tempfile.TemporaryDirectory(prefix='p2p-tests-')
os.environ['P2P_DATA_DIR'] = _test_home.name
import app as application
from configuration import Configuration, DEFAULTS, SECRET_NAMES


@pytest.fixture
def appmod(tmp_path, monkeypatch):
    a = application
    monkeypatch.setattr(a, 'AUDIO_DIR', tmp_path/'audio'); a.AUDIO_DIR.mkdir()
    monkeypatch.setattr(a, 'PDF_DIR', tmp_path/'pdfs'); a.PDF_DIR.mkdir()
    monkeypatch.setattr(a, 'EPISODES_FILE', tmp_path/'episodes.json')
    monkeypatch.setattr(a, 'BASE_DIR', Path(a.__file__).resolve().parent)
    for name in set(DEFAULTS) | SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('P2P_DATA_DIR', str(tmp_path/'config-home'))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-anthropic-key')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-eleven-key')
    config = Configuration(tmp_path/'empty-install')
    config.locations = replace(config.locations, library=tmp_path)
    monkeypatch.setattr(a, 'configuration', config)
    monkeypatch.setattr(a, 'setting', config.get)
    monkeypatch.setattr(a, 'credential', config.secret)
    monkeypatch.setattr(a, 'get_voice_id', lambda client: 'test-voice')
    monkeypatch.setattr(a, 'r2_enabled', lambda: False)
    monkeypatch.setattr(a, '_MODEL_INFO', {})
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
