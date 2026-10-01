# Developer notes

Single-user loopback-only Flask app. Read README.md for installation, data flow, privacy and provider limitations.

- Keep all mutations behind session CSRF/Origin checks and `exclusive_mutation`.
- Episode IDs are permanent. Never derive paths or rename storage from a display title.
- Use storage.py for JSON changes; never recover parse errors by clearing a library.
- Audio is versioned. Never overwrite an existing recording while streaming.
- Default Claude models are pinned; newest-in-family selection is explicit opt-in. Resolve the pair once per episode and preserve usage.
- Model output and PDF text are untrusted. Use textContent/Jinja escaping, not raw HTML.
- Keep provider tests mocked. Do not run paid or public publishing checks without explicit authorization and suitable test accounts.
- Run `python -m pytest -q` in the private environment. CI covers macOS/Windows, Python 3.10/3.13; do not claim a matrix pass until it ran.
- Persistence: static/episodes.json, .json.bak, static/audio/, static/pdfs/. These are ignored and must never be committed.
