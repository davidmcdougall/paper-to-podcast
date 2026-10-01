import json
from concurrent.futures import ThreadPoolExecutor
import pytest
import storage


def test_concurrent_inserts_keep_both(tmp_path):
    path=tmp_path/'episodes.json'
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i:storage.insert(path,{'slug':str(i)}), range(20)))
    assert len(storage.load(path)) == 20


def test_corruption_preserved(tmp_path):
    path=tmp_path/'episodes.json';path.write_text('{broken',encoding='utf-8')
    with pytest.raises(storage.StoreError):storage.insert(path,{'slug':'new'})
    assert path.read_text() == '{broken'


def test_atomic_replace_failure_preserves_original(tmp_path,monkeypatch):
    path=tmp_path/'episodes.json';storage.insert(path,{'slug':'old'})
    before=path.read_bytes()
    monkeypatch.setattr(storage.os,'replace',lambda *a: (_ for _ in ()).throw(OSError('full disk')))
    with pytest.raises(OSError):storage.insert(path,{'slug':'new'})
    assert path.read_bytes() == before


def test_rename_does_not_change_id_or_assets(appmod,client,episode):
    other=dict(episode,slug='other',title='Taken')
    storage.insert(appmod.EPISODES_FILE,other)
    audio=appmod.AUDIO_DIR/'test-id.mp3';audio.write_bytes(b'original')
    response=client.post('/rename/test-id',json={'title':'Taken'})
    assert response.status_code==200
    assert response.json['new_slug']=='test-id'
    assert len({e['slug'] for e in appmod.load_episodes()})==2
    assert audio.read_bytes()==b'original'
    assert client.post('/rename/test-id',json={'title':'!!!'}).status_code==200


def test_operation_lock(client,appmod,episode):
    from filelock import FileLock
    # Separate process-style lock object deliberately held during the request.
    with FileLock(str(appmod.EPISODES_FILE)+'.operation.lock'):
        assert client.post('/delete/test-id').status_code == 409


def test_separate_processes_preserve_updates(tmp_path):
    import subprocess, sys
    from pathlib import Path
    path=tmp_path/'episodes.json'
    script='import storage,sys; [storage.insert(sys.argv[1], {"slug":sys.argv[2]+str(i)}) for i in range(10)]'
    procs=[subprocess.Popen([sys.executable,'-c',script,str(path),prefix],cwd=Path(storage.__file__).parent) for prefix in ['a','b']]
    assert all(p.wait(timeout=20)==0 for p in procs)
    assert len(storage.load(path))==20
