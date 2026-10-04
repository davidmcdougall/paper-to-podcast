"""Local configuration. Reads never rewrite legacy files or contact providers."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from dotenv import dotenv_values
from filelock import FileLock, Timeout
from platformdirs import PlatformDirs
import tomli
import tomli_w
import storage

DEFAULTS = {
    'ELEVENLABS_VOICE_ID': '', 'OBSIDIAN_VAULT_PATH': '',
    'PODCAST_TITLE': 'Paper to Podcast',
    'PODCAST_DESCRIPTION': 'Academic papers turned into podcast episodes.',
    'PODCAST_AUTHOR': '', 'R2_ACCOUNT_ID': '', 'R2_BUCKET': 'paper-to-podcast',
    'R2_PUBLIC_URL': '', 'TEXT_MODEL': 'auto', 'FAST_MODEL': 'auto',
    'TEXT_MODEL_OPTIONS': '', 'TEXT_MODEL_FAMILY': 'sonnet',
    'FAST_MODEL_FAMILY': 'haiku', 'FLASK_DEBUG': '0',
}
SECRET_NAMES = frozenset({'ANTHROPIC_API_KEY', 'ELEVENLABS_API_KEY',
                          'R2_ACCESS_KEY_ID', 'R2_SECRET_KEY'})


class ConfigurationError(ValueError):
    """Safe, app-authored message; never include values or parser diagnostics."""


@dataclass(frozen=True)
class Locations:
    config: Path
    data: Path
    library: Path
    legacy_env: Path

    @property
    def episodes(self):
        return self.library / 'episodes.json'


@dataclass(frozen=True)
class Settings:
    values: Mapping[str, str]
    sources: Mapping[str, str]

    def get(self, name):
        return self.values[name]


@dataclass
class Operation:
    settings: Settings
    # Resolved lazily; never serialized, logged or included in repr.
    secrets: dict = field(default_factory=dict, repr=False)


def _absolute(value, label):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f'{label} must be an absolute path.')
    return path.resolve()


class Configuration:
    def __init__(self, base_dir, *, environ=None, dirs=None, keychain=None):
        self.base = Path(base_dir).resolve()
        self.environ = os.environ if environ is None else environ
        dirs = dirs or PlatformDirs('paper-to-podcast', appauthor=False)
        override = self.environ.get('P2P_DATA_DIR')
        data = _absolute(override, 'P2P_DATA_DIR') if override else Path(dirs.user_data_dir)
        config = data / 'config' if override else Path(dirs.user_config_dir)
        self.file = config / 'settings.toml'
        saved = self.read()
        paths = saved.get('paths', {})
        legacy = self.base / 'static'
        user_library = data / 'library'
        if ('library_dir' not in paths and (legacy / 'episodes.json').exists()
                and (user_library / 'episodes.json').exists() and legacy != user_library):
            raise ConfigurationError('Two libraries found (static and user data). Set [paths].library_dir in settings.toml to the intended library; neither was changed.')
        existing = ((self.base / '.env').exists() or (legacy / 'episodes.json').exists()
                    or any(p.exists() and any(p.iterdir()) for p in
                           (legacy / 'audio', legacy / 'pdfs')))
        library = (_absolute(paths['library_dir'], 'library_dir') if 'library_dir' in paths
                   else user_library if (user_library / 'episodes.json').exists()
                   else legacy if existing and not override else user_library)
        legacy_env = _absolute(paths.get('legacy_env_path', str(self.base / '.env')), 'legacy_env_path')
        if 'library_dir' in paths and not library.is_dir():
            raise ConfigurationError('Registered library is missing; restore its location before starting.')
        self.locations = Locations(config, data, library, legacy_env)
        self._operation = ContextVar(f'p2p_operation_{id(self)}', default=None)
        from credential_store import CredentialStore
        self.credentials = CredentialStore(self, keychain=keychain)

    def read(self):
        try:
            with self.file.open('rb') as stream:
                data = tomli.load(stream)
        except FileNotFoundError:
            return {'schema_version': 1}
        except (OSError, ValueError):
            raise ConfigurationError('Cannot read settings.toml; original preserved.') from None
        self.validate(data)
        return data

    @staticmethod
    def validate(data):
        if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ConfigurationError('Unsupported settings schema version; use a compatible app. Original preserved.')
        if set(data) - {'schema_version', 'settings', 'paths', 'plaintext_secrets'}:
            raise ConfigurationError('Unknown settings.toml section; original preserved.')
        for section, names in [('settings', {n.lower() for n in DEFAULTS}),
                               ('paths', {'library_dir', 'legacy_env_path'})]:
            values = data.get(section, {})
            if not isinstance(values, dict) or set(values) - names:
                raise ConfigurationError(f'Invalid {section} section; original preserved.')
            if any(not isinstance(v, str) or '\x00' in v for v in values.values()):
                raise ConfigurationError(f'{section} values must be strings without NUL characters.')
        if type(data.get('plaintext_secrets', False)) is not bool:
            raise ConfigurationError('plaintext_secrets must be true or false.')
        for name, value in data.get('paths', {}).items():
            _absolute(value, name)

    @contextmanager
    def edit(self):
        if self._operation.get() is not None:
            raise ConfigurationError('Wait for the current operation before changing configuration.')
        self.locations.library.mkdir(parents=True, exist_ok=True)
        # Keep one instance for reentrant credential/settings saves in this process.
        if not hasattr(self, '_edit_lock'):
            self._edit_lock = FileLock(str(self.locations.episodes) + '.operation.lock', timeout=0)
        try:
            with self._edit_lock:
                self.check_location()
                yield
        except Timeout:
            raise ConfigurationError('Library is busy; wait for the current operation.') from None

    def save(self, changes):
        with self.edit():
            self._save(changes)

    def _save(self, changes, *, register_location=False):
        """Merge validated non-secret settings atomically; UI arrives in PR-F."""
        if self._operation.get() is not None:
            raise ConfigurationError('Wait for the current operation before changing settings.')
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.file) + '.lock', timeout=10):
            data = self.read()
            if register_location:
                recorded = data.get('paths', {}).get('library_dir')
                if recorded:
                    if Path(recorded).resolve() != self.locations.library:
                        raise ConfigurationError('Library location changed. Restart the app before continuing.')
                    return
                changes = {'paths': {'library_dir': str(self.locations.library),
                                     'legacy_env_path': str(self.locations.legacy_env)}}
            for name, value in changes.items():
                if name in ('settings', 'paths') and isinstance(value, dict):
                    data[name] = {**data.get(name, {}), **value}
                else:
                    data[name] = value
            self.validate(data)
            # Do not import .env values (especially keys) into this file.
            if self.file.exists():
                storage.atomic_write(self.file.with_suffix('.toml.bak'), self.file.read_bytes())
            storage.atomic_write(self.file, tomli_w.dumps(data).encode('utf-8'))

    def legacy(self):
        try:
            if not self.locations.legacy_env.exists():
                return {}
            # Read legacy syntax/interpolation without mutating the process environment.
            return dotenv_values(self.locations.legacy_env)
        except (OSError, UnicodeError):
            raise ConfigurationError('Cannot read legacy .env; original preserved.') from None

    def snapshot(self):
        saved, legacy = self.read().get('settings', {}), self.legacy()
        values, sources = {}, {}
        for name, default in DEFAULTS.items():
            if name in self.environ:
                value, origin = self.environ[name], 'environment'
            elif name.lower() in saved:
                value, origin = saved[name.lower()], 'settings'
            elif legacy.get(name) is not None:
                value, origin = legacy[name], 'legacy .env'
            else:
                value, origin = default, 'default'
            values[name], sources[name] = value, origin
        values['R2_PUBLIC_URL'] = values['R2_PUBLIC_URL'].rstrip('/')
        if sources['PODCAST_AUTHOR'] == 'default':
            values['PODCAST_AUTHOR'] = values['PODCAST_TITLE']
        return Settings(MappingProxyType(values), MappingProxyType(sources))

    def get(self, name):
        operation = self._operation.get()
        return (operation.settings if operation else self.snapshot()).get(name)

    def secret(self, name):
        if name not in SECRET_NAMES:
            raise ConfigurationError('Unknown credential name.')
        operation = self._operation.get()
        if operation is None:
            return self.credentials.resolve(name)
        if name not in operation.secrets:
            operation.secrets[name] = self.credentials.resolve(name)
        return operation.secrets[name]

    @contextmanager
    def operation(self):
        if self._operation.get() is not None:
            yield
            return
        self.locations.library.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.locations.episodes) + '.operation.lock', timeout=0):
            self.check_location()
            state = Operation(self.snapshot())
            token = self._operation.set(state)
            try:
                yield
            finally:
                state.secrets.clear()
                self._operation.reset(token)

    def check_location(self):
        selected = self.read().get('paths', {}).get('library_dir')
        if selected and Path(selected).resolve() != self.locations.library:
            raise ConfigurationError('Library location changed. Restart the app before continuing.')

    def prepare_library(self):
        # Pin the choice before creating media or accepting requests. Later .env
        # creation cannot silently redirect this installation to another library.
        with self.edit():
            self._save({}, register_location=True)
            for folder in ('audio', 'pdfs'):
                (self.locations.library / folder).mkdir(parents=True, exist_ok=True)
