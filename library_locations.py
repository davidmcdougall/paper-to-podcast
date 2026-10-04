"""Explicit, local-only library relocation backend; no UI until PR-F."""
import hashlib
import shutil
import uuid
from pathlib import Path
from filelock import FileLock, Timeout
from configuration import ConfigurationError


def manifest(root):
    """Hash only managed library files, never packaged JS or an adjacent .env."""
    files = []
    if any((root/name).is_symlink() for name in ('audio', 'pdfs')):
        raise ConfigurationError('Library contains symlinks; original preserved.')
    for pattern in ('episodes.json*', 'feed.xml', 'logo.png', 'audio/**/*', 'pdfs/**/*'):
        files.extend(root.glob(pattern))
    result = {}
    for path in sorted(set(files)):
        if path.name.endswith('.lock'):
            continue
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise ConfigurationError('Library contains symlinks; original preserved.')
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        result[str(path.relative_to(root))] = (path.stat().st_size, digest.hexdigest())
    return result


def move_library(config, destination):
    """Explicit opt-in: copy/verify/switch. Source is never removed.

    Caller must restart the application after success. Failures may leave a
    partial destination and a backup; neither is treated as an active library.
    """
    source = config.locations.library.resolve()
    target = Path(destination).expanduser()
    if not target.is_absolute():
        raise ConfigurationError('Library destination must be an absolute path.')
    target = target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ConfigurationError('Choose a separate empty library directory.')
    if config.environ.get('P2P_DATA_DIR'):
        raise ConfigurationError('Remove P2P_DATA_DIR and restart before moving the library.')
    if not source.is_dir():
        raise ConfigurationError('Original library directory is missing.')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ConfigurationError('Library destination must be empty.')
    try:
        with config.edit():
            with FileLock(str(config.locations.episodes)+'.lock', timeout=10):
                before = manifest(source)
                backup = config.locations.data/'backups'/('library-move-'+uuid.uuid4().hex)
                # Copy only the fixed manifest, never the backup directory itself.
                backup.mkdir(parents=True)
                target.mkdir(parents=True, exist_ok=True)
                for relative in before:
                    for root in (backup, target):
                        dest = root/relative
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source/relative, dest)
                if manifest(target) != before or manifest(backup) != before or manifest(source) != before:
                    raise ConfigurationError('Library verification failed; original location retained.')
                config.save({'paths': {'library_dir': str(target),
                                       'legacy_env_path': str(config.locations.legacy_env)}})
                return {'files': len(before), 'backup': str(backup), 'restart_required': True}
    except Timeout:
        raise ConfigurationError('Library is busy; wait for the current operation.') from None
