"""Small, cross-process-safe JSON store. Never recover corruption by erasing it."""
import json
import os
import re
import tempfile
import time
import uuid
import shutil
import datetime
from collections import Counter
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
        # Windows can briefly deny replacement while a reader has the file open.
        for attempt in range(6):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        Path(name).unlink(missing_ok=True)


def _load_unlocked(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    except (ValueError, OSError) as exc:
        raise StoreError('Cannot read episode library; restore a backup or repair it. Original file preserved.') from exc
    if not isinstance(data, list) or any(not isinstance(ep, dict) or not isinstance(ep.get('slug'), str) for ep in data):
        raise StoreError('Invalid episode records; library preserved for repair.')
    original_ids = Counter(ep['slug'] for ep in data)
    original_guids = Counter(ep.get('feed_guid') or ep['slug'] for ep in data)
    seen = set()
    changed = False
    for ep in data:
        old = ep['slug']
        if valid_id(old) and old not in seen:
            seen.add(old)
            continue
        # v1 allowed empty/reserved/duplicate slugs. Copy assets, never move them:
        # duplicate entries can share a file and the original remains recoverable.
        new = uuid.uuid4().hex
        while new in seen or any(e['slug'] == new for e in data):
            new = uuid.uuid4().hex
        ep.update(slug=new, legacy_slug=old)
        ep['feed_guid'] = old if old and original_ids[old] == 1 and original_guids[old] == 1 else new
        ep['legacy_files'] = {field: ep.get(field) for field in ('audio_url', 'pdf_url', 'local_audio')}
        warnings = list(ep.get('warnings', []))
        warnings.append('Legacy episode ID migrated. Original files retained; review this episode before publishing.')
        ep['warnings'] = warnings
        for folder, ext, field in [('audio', '.mp3', 'audio_url'), ('pdfs', '.pdf', 'pdf_url')]:
            name = (ep.get('local_audio') if folder == 'audio' else None) or old+ext
            # Only v1 basename characters, never paths or Windows devices.
            safe = re.fullmatch(r'[\w-]*'+re.escape(ext), name) is not None
            safe = safe and len(name.encode('utf-8')) <= 240
            safe = safe and (os.name != 'nt' or valid_id(Path(name).stem))
            source = Path(path).parent/folder/name
            target = Path(path).parent/folder/(new+ext)
            copied = False
            try:
                if safe and source.is_file() and not source.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    copied = True
            except OSError:
                # One locked/unreadable asset must not prevent the library opening.
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass  # Any orphan is unreferenced; original media is untouched.
                warnings.append('Legacy '+folder+' copy failed; original retained. Restore it before reusing this asset.')
            if copied:
                ep[field] = '/static/'+folder+'/'+target.name
                if folder == 'audio':
                    ep['local_audio'] = target.name
            else:
                ep[field] = ''
                if folder == 'audio':
                    if ep.get('r2_url') and ep.get('file_size') and not ep.get('published'):
                        ep['published'] = {k: ep.get(k) for k in ('r2_url', 'file_size', 'duration')}
                    ep.pop('local_audio', None)
                    ep.update(file_size=0, audio_ready=False)
        seen.add(new)
        changed = True
    if changed:
        path = Path(path)
        backup = path.with_suffix('.json.migration.bak')
        before = path.read_bytes()
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        atomic_write(path.with_name(path.name+'.migration.'+timestamp+'-'+uuid.uuid4().hex[:8]+'.bak'), before)
        if not backup.exists():
            atomic_write(backup, before)
        atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
    return data


def load(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path)+'.lock', timeout=10):
        return _load_unlocked(path)


def mutate(path, callback):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path)+'.lock', timeout=10):
        data = _load_unlocked(path)
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
