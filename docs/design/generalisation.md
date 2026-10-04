# Generalisation: design for approval

2026-10-03 · Baseline: merged `2e4c787` · Status: PR-A merged; PR-B implementation authorized on 2026-10-04.

**Goal:** install once, configure and edit prompts in the browser, retain existing libraries. Release with Anthropic and ElevenLabs first. Keep the app local and single-user; no hosting, accounts, billing system, plugin framework or desktop wrapper. The two Stage 0 fixes are already merged. Verified: 87 local tests pass; reviewed and merged trees match.

## 1. Configuration, secrets and data

Extract configuration from `app.py` into a typed, validated configuration module. Use `platformdirs` for new installations: `settings.toml` in user configuration storage; prompts/history, library/media, backups and logs in user data storage. Serve user media through validated routes. Show paths in Settings. Allow one `P2P_DATA_DIR` environment override; no portable-storage option.

Settings precedence: process environment > settings file > legacy `.env` > defaults. Secrets: process environment > OS keychain > explicitly enabled local secrets file > legacy `.env`. Parse `.env` separately rather than injecting it into the process environment. Read legacy files unchanged at their registered location; never delete or relocate them. Environment overrides are labelled in Settings.

Use `keyring` with a secure OS backend. If unavailable, offer “Store unencrypted on this computer” with explicit consent; refusal leaves the key unset. Use 0600 on POSIX and user-profile defaults on Windows, without custom ACL code. R2 credentials use the keychain too. Secrets never enter settings, logs, episode records or HTML. Bind credentials to provider plus normalized endpoint, including base path; changing endpoints requires separate credentials. Do not forward credentials across redirects. Require HTTPS except explicitly selected loopback providers.

Existing installations retain their library location indefinitely. Register the existing location through the launcher or browser. “Move library” blocks concurrent operations, backs up, copies to an empty destination, verifies counts and SHA-256 hashes, then atomically switches the stored location. Retain source files and the old location on failure; leave `.env` and external notes untouched.

Snapshot settings and prompts at operation start. Resolve credentials when needed; never persist or log operation credentials. Rotations apply to later operations; secure memory erasure is not promised. Location changes require an idle application and restart. Version only `settings.toml`; refuse newer versions clearly. Keep `episodes.json` as a list; introduce a library version marker only with a tested compatibility strategy.

## 2. Prompts and outputs

Extract five immutable shipped Markdown templates: script, voice edit, summary, show notes and metadata. Preserve current rendered requests in regression fixtures. Seed editable copies once; upgrades never overwrite edits. Allow only documented literal placeholders (`length_rule`, `notes`, `source`, `script`, `title`, `authors`), with required fields per template; no executable templating. Require `{source}` exactly once, at the end of source-bearing templates. Reject invalid saves; missing or externally edited invalid files fall back to defaults with a warning and regression coverage. System instructions and metadata JSON schema remain in code. Enforce finished responses, non-empty text, valid metadata JSON and escaped output; “no invented citations” and “script only” remain editorial guidance, not guarantees.

Settings provides editing, save, reset, history and offline Preview against a bundled sample, with a clearly labelled token estimate and no provider call. Archive exact template bytes under their SHA-256 hash. Record template hash, non-secret parameters, model, sampling version and source hash per step/attempt, including retries; large source/script values use references and hashes. Exact regeneration is not promised. Retries retain prior records and take new snapshots.

Notes destinations: `folder` writes plain Markdown; `obsidian` adds existing frontmatter and stable filenames; `none` disables export. Preserve safe stable filenames and ownership checks. Destinations must exist and be outside application data storage. R2/RSS behaviour and ownership records stay unchanged; only configuration moves into Settings.

## 3. Providers and settings UI

One `providers/` package, exactly two capabilities: text (`complete`, token count or labelled estimate, model listing) and speech (synthesize to temporary file, voice listing). Adapters declare input limits with units, context/output limits and audio formats. Preserve Anthropic family discovery, pins, caching and ElevenLabs defaults in the initial extraction. Scope caches to endpoint and credential revision; invalidate after changes. Keep application source/spend caps even when providers allow more.

After release, add one OpenAI-compatible text adapter with tested presets for OpenAI, OpenRouter, Ollama and LM Studio. Unsupported discovery requires an explicit model; unavailable counting uses a conservative estimate and documented model limits, refusing generation when a safe budget cannot be established.

Defer the second speech provider to that later PR; prefer a supported hosted OpenAI option over a bundled local engine, but recheck API lifecycle first. Limits remain adapter-specific. For chunked synthesis, split on sentences with bounded fallback for oversized sentences, synthesize temporary chunks, decode/join with a tested codec path, validate final duration/size, then commit versioned audio. Middle-chunk failure preserves previous audio and reports incurred usage uncertainty; no automatic paid retries. Codec dependencies and the supported API need approval in that PR. See [Speech reference](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create) and [model deprecations](https://developers.openai.com/api/docs/deprecations).

`/settings` retains loopback, Host, Origin, session and CSRF protection. Include models, write-only keys (set/unset), voice, podcast identity, notes, R2 and prompts. Zero-key startup redirects home to a setup checklist; existing libraries remain accessible. Startup and page loads make no automatic network calls, including update checks; any update check is opt-in. Explicit connection tests use documented non-generating listing requests and report “Connection verified; generation not tested”; unsupported tests say so. Test successful listing followed by forbidden generation separately from listing failures.

## 4. Installation and delivery

Planning estimates: L/M/H = low/medium/high; verify OS reputation behaviour on real machines.

| Approach | User friction | Maintenance | Signing/notarisation | Windows reputation risk | Updates |
|---|---|---|---|---|---|
| Platform installer using uv | L | M | No custom executable initially | M: downloaded scripts | Verified pinned release |
| Direct pipx/uv tool install | M | L | No custom executable initially | L–M | Explicit pinned reinstall |
| Desktop bundle | L after setup | H | Plan signing/notarisation | H if unsigned | Separate updater |

Build the uv installer and entry point; uv installs/manages Python and locked dependencies. Launcher only starts/stops, opens the browser and shows logs; recognize own instances and explain port conflicts. Re-running the installer with a pinned tag updates or rolls back; stage/check before switching, retaining the previous usable environment. No browser updater. Uninstall removes app/launcher but preserves library, settings and keychain entries unless deletion is explicitly requested; document locations. Test Windows security prompts and macOS launcher quarantine on real machines.

**PR order:** A configuration/keychain/locations → B prompt storage/history → C existing adapters → E notes → F settings/editor/first run → G installer/docs **and release** → D additional providers. Extract code from `app.py`; justify dependencies. README: install → setup → episode, privacy/rights and dated costs; technical detail moves to `docs/`.

**Planning allowances, not promises:** A 2–3 days; B ~2; C 1–2; E ~1; F 3–4; G 3–5. F/G carry most uncertainty. Stop PR-A if it looks likely to exceed about three days and explain why.

**Acceptance:** mocked providers only; no paid calls or publication. Preserve all security, atomic storage, corruption refusal, IDs, saved drafts, versioned audio and retry guarantees. Test precedence, keychain failure, endpoint isolation, prompt fallback/history and operation snapshots. Verify upgrades/moves preserve library, media, settings and edited prompts by counts/hashes. On macOS/Windows with Python 3.10/3.13, test install/reinstall, start, first-run redirect/checklist, mocked Short script, shutdown, failed update and reinstalling the previous pinned version. Mocks cannot verify live permissions, sound quality or OS security prompts. A maintainer Short episode and scratch R2 publish/delete before release require separate, bounded authorization; record results in release notes.

**Decision:** PR-A merged as `340bd82`. PR-B (prompt storage/history) authorized on 2026-10-04; open it for review and stop unmerged before PR-C. Browser editing remains in PR-F.
