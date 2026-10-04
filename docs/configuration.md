# Configuration and data locations (PR-A)

This is the configuration backend only. The browser settings/editor and installer are later PRs. Existing `.env` files continue to work without editing or conversion. No legacy settings or secrets are automatically imported, relocated or deleted. Startup records the selected library and legacy .env path once in settings.toml.

## Locations

New installations use `platformdirs` for the current user: typically `~/Library/Application Support/paper-to-podcast` on macOS and `%LOCALAPPDATA%\paper-to-podcast` on Windows. `settings.toml` uses the OS config directory; `library/` under the data directory holds `episodes.json`, audio, PDFs, feed and optional `logo.png`. Backups for an explicit move live under `backups/`. Logs and prompt storage are reserved for later PRs.

On first startup the library choice is recorded, so a later `.env` cannot redirect an existing library. If no location is recorded and both candidate directories contain `episodes.json`, startup refuses to guess; set `[paths].library_dir` explicitly. Otherwise an existing user-data library takes precedence. If the installation has a `.env`, `static/episodes.json` or existing media, its `static/` library stays in place. A recorded `[paths].library_dir` takes precedence. A missing recorded library stops startup; it never becomes a silently empty replacement.

`P2P_DATA_DIR` is the sole environment override for unusual setups. It must be absolute; it selects a data root with `config/settings.toml` and `library/`. It does not copy existing files. Do not use it as an upgrade/migration command. Remove it and restart to return to the previous location.

The optional `library_locations.move_library(config, destination)` backend requires a separate empty destination. It locks operations, copies managed files to a backup and destination, verifies byte counts/SHA-256 hashes, then records the new location. It never deletes the source or changes `.env`. Failures can leave an unselected partial destination and backup; inspect these before retrying into an empty destination. Successful moves require a restart; an old instance refuses subsequent requests. The browser action is deferred to PR-F.

## Settings

A minimal optional file:

```toml
schema_version = 1

[settings]
podcast_title = "Research notes"
text_model = "auto"
fast_model = "auto"
elevenlabs_voice_id = ""
```

Settings keys are the lowercase forms of the existing non-secret environment names in `.env.example`, plus `flask_debug` (keep `"0"`). All setting values are strings. Precedence is process environment, saved settings, legacy `.env`, defaults; an explicit empty value also wins. `Configuration.snapshot().sources` reports the winning source for the future settings UI.

`Configuration.save()` validates and merges changes under locks, keeps the previous file as `settings.toml.bak`, and atomically replaces the file. Unknown keys, secret fields, malformed TOML or unsupported versions are refused without overwriting the file. Only settings are versioned; `episodes.json` retains its list format and existing storage protections.

`[paths]` supports absolute `library_dir` and `legacy_env_path` for the later launcher/import UI. These register locations, not copies. Location changes need a restart. Other settings apply to later operations; an operation keeps its starting settings.

## Credentials

Anthropic, ElevenLabs, R2 access-key ID and R2 secret key use the native macOS Keychain or Windows Credential Locker via `keyring`. R2 account ID, bucket and public URL are non-secret settings. No keychain lookup occurs at import/startup. There are no automatic network calls or update checks.

Precedence is process environment, native keychain, explicitly enabled local secrets file, legacy `.env`. Keychain entries are scoped by provider and normalized endpoint (including path); R2 entries are scoped to the account endpoint, not the public domain. Legacy R2 keys are usable only with the account from their `.env`. Environment credentials are explicit operator overrides. Additional configurable provider endpoints are deferred.

`config.credentials.save(name, value)` attempts the keychain and fails with a safe message if unavailable. `allow_plaintext=True` is an explicit consent parameter for the future UI: only a failed keychain write takes this path. The fallback is `secrets.json` beside `settings.toml`, enabled by `plaintext_secrets = true`. It uses mode 0600 on POSIX and inherited profile permissions on Windows; no custom ACL code. Never place this file in a shared directory. Refusing consent saves no plaintext. A locked vault or failed replacement of an existing keychain entry must be resolved first; plaintext cannot silently replace a higher-priority key. A keychain read error stops resolution with an unlock/retry message; only a successful read returning no entry permits fallback. No third-party/network keyring backend is auto-selected.

Credentials are resolved when needed and retained only for the current operation/SDK client; they are not stored on episodes or logged. In-app credential changes refuse a running operation and apply to later ones. External keychain/environment changes are observed on the next resolution; already-resolved credentials remain fixed until that operation ends. Python/SDK memory erasure is not guaranteed. No migration deletes keys from `.env` or the keychain.

Tests use temporary directories, synthetic keys and an in-memory keychain. Native OS keychain prompts/permissions and actual provider entitlements still require a separate manual check. PR-A makes no paid or publishing calls.
