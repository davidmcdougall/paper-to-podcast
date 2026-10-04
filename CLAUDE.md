# Developer notes

Single-user loopback-only Flask app. Read README.md for installation, data flow, privacy and provider limitations.

- Keep all mutations behind session CSRF/Origin checks and `exclusive_mutation`.
- Episode IDs are permanent. Never derive paths or rename storage from a display title.
- Use storage.py for JSON changes; never recover parse errors by clearing a library.
- Audio is versioned. Never overwrite an existing recording while streaming.
- Default Claude models use family-scoped discovery; explicit IDs pin behavior/cost. Resolve the pair once per episode and preserve usage.
- Model output and PDF text are untrusted. Use textContent/Jinja escaping, not raw HTML.
- Keep provider tests mocked. Do not run paid or public publishing checks without explicit authorization and suitable test accounts.
- Run `python -m pytest -q` in the private environment. CI covers macOS/Windows, Python 3.10/3.13; do not claim a matrix pass until it ran.
- Persistence: legacy installs retain static/; new installs use user storage. Resolve locations through Configuration (see docs/configuration.md). Settings, secrets and generated media must never be committed.

## Code map

- `app.py`: Flask routes, request protection, provider calls, generation and R2/feed workflows.
- `configuration.py`, `credential_store.py`, `library_locations.py`: settings precedence, endpoint-bound secrets and explicit copy/verify/switch library moves. Never log credential values or provider exception bodies.
- `storage.py`: locked JSON persistence, backups and legacy-ID migration.
- `pdf_text.py`: bounded PDF extraction worker, launched in a timed subprocess.
- `templates/`, `static/ui.js`: upload/draft and library views; shared CSRF fetch helper.
- `transcribe_episode.py`, `upload_logo.py`: optional local transcription and R2 artwork utilities.
- `tests/`: isolated temporary libraries and mocked providers; no paid calls.

The flow is source → sampled script → optional research notes → saved draft → versioned audio → optional R2/feed and Obsidian export. Persist the paid script before optional work; preserve remote cleanup keys before uploads. R2 ownership is account/bucket/key, not a public hostname.
