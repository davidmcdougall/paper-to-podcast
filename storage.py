"""Small, cross-process-safe JSON store. Never recover corruption by erasing it."""
import json
import os
import re
import tempfile
from pathlib import Path
from filelock import FileLock


class StoreError(RuntimeError):
    pass


def valid_id(value):
    # Includes safe legacy title slugs. New IDs are UUID hex strings.
    return (isinstance(value, str) and re.fullmatch(r'[\w-]{1,80}', value) is not None
            and value.upper() not in {'CON', 'PRN', 'AUX', 'NUL',
                                    *('COM'+str(i) for i in range(1,10)),
                                    *('LPT'+str(i) for i in range(1,10))})


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    except (ValueError, OSError) as exc:
        raise StoreError('Cannot read episode library; restore a backup or repair it. Original file preserved.') from exc
    if (not isinstance(data, list) or any(not isinstance(ep, dict) or not valid_id(ep.get('slug')) for ep in data)
            or len({ep['slug'] for ep in data}) != len(data)):
        raise StoreError('Invalid or duplicate episode IDs; library preserved for repair.')
    return data


def mutate(path, callback):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path)+'.lock', timeout=10):
        data = load(path)
        result = callback(data)
        encoded = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
        if path.exists():
            atomic_write(path.with_suffix('.json.bak'), path.read_bytes())
        atomic_write(path, encoded)
        return result


def insert(path, episode):
    if not valid_id(episode.get('slug')):
        raise StoreError('Invalid episode ID')
    def change(data):
        if any(e['slug'] == episode['slug'] for e in data):
            raise StoreError('Episode already exists; original preserved.')
        data.insert(0, episode)
    mutate(path, change)


def update(path, slug, changes):
    def change(data):
        episode = next((e for e in data if e['slug'] == slug), None)
        if episode is None:
            raise StoreError('Episode no longer exists.')
        episode.update(changes)
        return dict(episode)
    return mutate(path, change)
