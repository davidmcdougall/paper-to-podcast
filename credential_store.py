"""Endpoint-bound credentials with an explicitly consented plaintext fallback."""
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlsplit
from filelock import FileLock
import storage
from configuration import ConfigurationError, SECRET_NAMES


class KeychainUnavailable(ConfigurationError):
    pass


def native_keychain():
    # Never auto-select third-party backends (which may store plaintext or use a network).
    try:
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
        elif sys.platform == 'win32':
            from keyring.backends.Windows import WinVaultKeyring as Keyring
        else:
            raise KeychainUnavailable('No supported OS keychain. Configure an explicit fallback.')
        return Keyring()
    except Exception:
        raise KeychainUnavailable('OS keychain unavailable. Configure an explicit fallback.') from None


def endpoint_identity(provider, endpoint):
    url = urlsplit(endpoint)
    try:
        port = url.port
    except ValueError:
        raise ConfigurationError('Invalid credential endpoint.') from None
    if (url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password
            or url.query or url.fragment or (url.scheme == 'http' and url.hostname not in
                                             ('localhost', '127.0.0.1', '::1'))):
        raise ConfigurationError('Credentials require HTTPS or an explicit loopback endpoint.')
    host = url.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    default_port = 443 if url.scheme == 'https' else 80
    authority = host + (f':{port}' if port and port != default_port else '')
    canonical = f'{url.scheme}://{authority}{url.path.rstrip("/")}'
    return 'paper-to-podcast:' + hashlib.sha256(f'{provider}\n{canonical}'.encode()).hexdigest()


class CredentialStore:
    def __init__(self, configuration, keychain=None):
        self.config = configuration
        self._keychain = keychain
        self.file = configuration.locations.config / 'secrets.json'

    def backend(self):
        return self._keychain if self._keychain is not None else native_keychain()

    def scope(self, name):
        if name == 'ANTHROPIC_API_KEY':
            return endpoint_identity('anthropic', 'https://api.anthropic.com')
        if name == 'ELEVENLABS_API_KEY':
            return endpoint_identity('elevenlabs', 'https://api.elevenlabs.io')
        if name not in SECRET_NAMES:
            raise ConfigurationError('Unknown credential name.')
        account = self.config.get('R2_ACCOUNT_ID').strip()
        if not re.fullmatch(r'[A-Za-z0-9-]+', account):
            raise ConfigurationError('Set a valid R2 account ID before storing credentials.')
        return endpoint_identity('r2', f'https://{account}.r2.cloudflarestorage.com')

    def local(self):
        try:
            value = json.loads(self.file.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                  for k, v in value.items()):
                raise ValueError()
            return value
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise ConfigurationError('Cannot read local secrets file; original preserved.') from None

    def resolve(self, name):
        # Environment is an explicit operator override. Legacy R2 keys remain bound
        # to the account in that same .env, never to a newly selected account.
        if name in self.config.environ:
            return self.config.environ[name]
        if name.startswith('R2_') and not self.config.get('R2_ACCOUNT_ID').strip():
            return ''
        scope = self.scope(name)
        try:
            value = self.backend().get_password(scope, name)
        except Exception:
            raise KeychainUnavailable('Cannot read the keychain. Unlock the keychain and retry; no fallback credential was used.') from None
        if value is not None:
            return value
        if self.config.read().get('plaintext_secrets', False):
            value = self.local().get(scope + ':' + name)
            if value is not None:
                return value
        legacy = self.config.legacy()
        if name.startswith('R2_') and legacy.get('R2_ACCOUNT_ID', '').strip() != self.config.get('R2_ACCOUNT_ID').strip():
            return ''
        return legacy.get(name) or ''

    def save(self, name, value, *, allow_plaintext=False):
        with self.config.edit():
            return self._save(name, value, allow_plaintext=allow_plaintext)

    def _save(self, name, value, *, allow_plaintext=False):
        if self.config._operation.get() is not None:
            raise ConfigurationError('Wait for the current operation before changing credentials.')
        if name not in SECRET_NAMES or not isinstance(value, str):
            raise ConfigurationError('Invalid credential.')
        scope = self.scope(name)
        backend = None
        try:
            backend = self.backend()
            backend.set_password(scope, name, value)
            return 'keychain'
        except Exception:
            if not allow_plaintext:
                raise KeychainUnavailable('Keychain unavailable; no secret saved. Explicit consent is required for unencrypted storage.') from None
        # Do not report a fallback rotation as successful while an older keychain
        # entry would still win precedence (or while a locked vault hides it).
        if backend is not None:
            try:
                previous = backend.get_password(scope, name)
            except Exception:
                raise KeychainUnavailable('Unlock the keychain before replacing this credential; no plaintext saved.') from None
            if previous is not None:
                raise KeychainUnavailable('Existing keychain credential could not be replaced; no plaintext saved.')
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.file) + '.lock', timeout=10):
            values = self.local()
            values[scope + ':' + name] = value
            # atomic_write creates a private temporary file (0600 on POSIX).
            storage.atomic_write(self.file, json.dumps(values).encode('utf-8'))
            if os.name == 'posix':
                self.file.chmod(0o600)
        self.config.save({'plaintext_secrets': True})
        return 'plaintext'
