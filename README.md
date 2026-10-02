# Paper to Podcast

Turn a text-based academic PDF or arXiv ID into a spoken episode, running locally at **http://127.0.0.1:5050**.

Claude writes a script and research notes; ElevenLabs voices it. **Script first, voice later** is the default so you can review claims before paying for audio. Optional Cloudflare R2 publishes audio and an RSS feed.

![Upload page — appearance from the earlier release; controls have since changed.](docs/upload.png)
![Library with sample episodes.](docs/library.png)

## What you need

- **Python 3.10–3.13**, from [python.org](https://www.python.org/downloads/). The local verification used macOS and Python 3.12; see [testing](#testing-and-contributing) for the CI matrix and remaining checks.
- An [Anthropic API key](https://console.anthropic.com) with billing credit. A Claude chat subscription does not supply API credit.
- For audio, an [ElevenLabs API key](https://elevenlabs.io) and an accessible voice. **Use a paid plan for Voice Library voices**: these are unavailable through the API on the free tier. Access also depends on voice availability and key permissions. See [voice access](https://elevenlabs.io/docs/overview/capabilities/voices).
- An internet connection for providers and arXiv. R2 and Obsidian are optional.

## Quick start

Open Terminal on Mac or PowerShell on Windows. Use **only the commands for your operating system**. Lines starting with `#` are explanatory comments.

**1. Install/check Python.**

Mac:
```bash
python3 --version
```

Windows:
```powershell
py --version
```

If missing or too old, install Python from python.org, then reopen the terminal. On Windows, enable the installer's PATH option if offered. If `py` is unavailable but `python --version` is correct, use `python` instead of `py` for the environment creation below.

**2. Download the code.** On GitHub choose Code → Download ZIP, extract it and move `paper-to-podcast-main` to Documents. Windows Extract All may create two nested folders: use the inner folder containing `app.py` and `requirements.txt`. Adjust these paths to its actual location (Windows Documents may be under OneDrive).

Mac:
```bash
cd "$HOME/Documents/paper-to-podcast-main"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
```

Windows PowerShell:
```powershell
cd "$HOME\Documents\paper-to-podcast-main"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
```

These commands call the private environment directly: no activation or PowerShell execution-policy changes are needed.

**3. Create the settings file.**

Mac:
```bash
cp .env.example .env
open -e .env
```

Windows:
```powershell
Copy-Item .env.example .env
notepad .env
```

Replace the two API key placeholders with your own keys. Keep the exact variable names and save as `.env`, not `.env.txt`. In TextEdit use plain text and avoid smart quotes. Dotfiles are hidden by default in Finder; Explorer handles them differently.

```dotenv
ANTHROPIC_API_KEY=your-real-key
ELEVENLABS_API_KEY=your-real-key
```

For script-only use, ElevenLabs can remain blank. **Leave all R2 credentials and `R2_PUBLIC_URL` blank for local use.** Never share `.env`; it allows spending on your accounts. The app warns about missing/placeholder keys and incomplete R2 configuration.

**4. Choose a voice (recommended before your first audio).** In ElevenLabs, add an accessible voice to your account, copy its ID, and set `ELEVENLABS_VOICE_ID` in `.env`. The key must permit voice lookup and speech generation. Without an ID, the app uses the first returned account voice; its identity/order is not guaranteed. Paid membership alone does not guarantee access to every voice.

**5. Start the server.**

Mac:
```bash
.venv/bin/python app.py
```

Windows:
```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5050** in your browser. Leave the terminal open. To stop, press Ctrl+C. Next time, open the terminal, return to the folder and run the same start command.

**6. Try a Short script.** Paste `1706.03762`, choose Short and Generate script. Review it against the paper, then click Voice this episode. If arXiv is unavailable, download a text PDF in your browser and upload it instead. The episode is stored in the library. If audio fails, retry voicing the saved script there; generating another draft repeats Claude charges.

## If something goes wrong

- **Missing module:** use the exact environment Python commands above; do not install into another Python.
- **Session expired / CSRF error:** reload the page after restarting the server. Use the same hostname throughout; `localhost` and `127.0.0.1` have separate browser sessions.
- **Authentication / access error:** check the key, API billing and model/voice permissions. Do not assume that buying a higher voice plan fixes a wrong ID or restricted key.
- **Rate limit / quota:** check provider usage, billing and status before retrying. Failed/time-out requests can still incur provider usage.
- **Script too long for speech:** keep the draft, choose Flash in the preview, or generate a shorter draft. Multilingual v2 permits 10,000 characters; Flash v2.5 permits 40,000. You can also select the voice model beside Voice / re-voice in the library.
- **Another operation is running:** wait. Mutations are serialized to prevent duplicate spending and conflicting writes.
- **No extracted text:** scanned/image PDFs need external OCR; this app does not provide it. Encrypted PDFs are rejected.
- **Address already in use:** stop the earlier server in its terminal. Port 5050 may also belong to another application; do not kill an unknown process.
- **Corrupt/duplicate library IDs:** stop the app, preserve both `static/episodes.json` and `static/episodes.json.bak`, and repair or restore a known-good copy. The app refuses to replace unreadable data with an empty library.
- **Publishing failed:** local audio remains playable. Fix R2 and use **Publish / retry** in the library; this does not regenerate script/audio.
- **Deletion incomplete:** retry Delete after fixing the reported problem. A durable deletion marker excludes that episode from future feeds. Previously downloaded copies cannot be recalled.

## Length, models and limits

Presets target 450 / 1,000 / 2,200 / 3,600 spoken words. Auto targets 500–2,500 words; Custom accepts 1–40 minutes at 150 words/minute. These are writing targets, not duration guarantees. Voice speed is 1.15; measured MP3 duration is shown after generation.

Input PDFs are limited to 20 MiB, 100 pages and 500,000 extracted characters, with a 30-second extraction timeout. Complex content streams are bounded. These are practical limits, not a sandbox guarantee against every malicious PDF. Long text is sampled for individual passes, and the UI warns when the main script source is sampled. Figures, equations and layout may not extract accurately. **Book support is not promised.**

Long paper sources are sampled from beginning, middle and end to fit the character and measured token budgets; sampling is recorded as an episode warning. Prompts are limited to 180,000 characters and a counted token budget of 60,000 including reserved output; lower model limits also apply. Truncated Claude responses are not treated as finished scripts. If the voice-edit pass fails, the completed first-pass script is saved for review, without automatic voicing. Editing is not fact-checking.

Defaults discover the newest available **Sonnet** for writing/summary and **Haiku** for editing, metadata and show notes. Set `TEXT_MODEL` and `FAST_MODEL` to explicit IDs to pin behavior/cost. Both models are validated before generation and saved on the episode with usage; discovery cannot guarantee future pricing or quality.

Discovery follows every API page, caches successful results for an hour and errors for 60 seconds, and never switches families or reuses stale results after a failed refresh. Page loading does not contact providers. Blank settings mean `auto`. Check [model lifecycle notices](https://platform.claude.com/docs/en/about-claude/model-deprecations) if using pins.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for scripts |
| `ELEVENLABS_API_KEY` | Required for audio |
| `ELEVENLABS_VOICE_ID` | Recommended explicit accessible voice |
| `TEXT_MODEL`, `FAST_MODEL` | `auto` (default), or explicit IDs to pin models |
| `TEXT_MODEL_OPTIONS` | Comma-separated additional writing choices; selection also controls summary |
| `TEXT_MODEL_FAMILY`, `FAST_MODEL_FAMILY` | Families for `auto` only; defaults Sonnet/Haiku |
| `PODCAST_TITLE`, `PODCAST_DESCRIPTION`, `PODCAST_AUTHOR` | Public feed identity |
| `OBSIDIAN_VAULT_PATH` | Optional existing vault directory; notes use immutable episode IDs |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL` | Optional public publishing; leave credentials/URL blank to disable |
| `FLASK_DEBUG` | Leave unset; `1` enables the development debugger |

## Costs

Pricing checked **2026-10-01**. Check the [ElevenLabs API pricing page](https://elevenlabs.io/pricing/api) for your account's actual billing product. It currently advertises **$0.04/1,000 characters for Flash/Turbo** and **$0.08/1,000 for Multilingual**, with dollar-based API billing. The separate [creative plans](https://elevenlabs.io/pricing) show Starter at $6/month and 30,000 credits. Do not assume a creative-plan credit allowance directly determines your API episode allowance; verify your dashboard and any voice-specific pricing.

The script pass keeps the v1 source-cost cap: at most `max(12,000, target words × 6)` source words (15,000 in Auto mode), sampled across the paper. Character and measured-token limits can reduce this further. Longer output targets can therefore cost more in both input and output; sampling is reported once on the episode.

Illustrative audio-only cost, using six characters per word (including spaces):

| Target | Approximate characters | Flash | Multilingual v2 |
|---|---:|---:|---:|
| Short: 450 words | 2,700 | $0.11 | $0.22 |
| Standard: 1,000 words | 6,000 | $0.24 | $0.48 |
| Long: 2,200 words | 13,200 | $0.53 | Exceeds single-request limit |
| Deep: 3,600 words | 21,600 | $0.86 | Exceeds single-request limit |

These exclude taxes, subscription commitments, retries and Claude. Actual billing uses actual script characters, displayed before voicing. The old 900 characters/minute approximation was 150 words × six characters; it is not a measured speech rate.

A complete script workflow makes up to **five Claude generation calls**: script, voice edit, summary, metadata, show notes, plus model validation/token-count requests. Cost depends on selected model, source size, output and retries; see [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). The episode JSON records input/output tokens for completed generation responses. Provider dashboards are authoritative, including usage from interrupted requests. No fixed per-episode ceiling is promised.

## Public RSS feed (optional)

1. In Cloudflare R2 create a bucket and enable its public development URL, or configure a public custom domain. Consult [R2 setup](https://developers.cloudflare.com/r2/get-started/) and [public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/); `r2.dev` is for development and has rate limits.
2. Create an R2 API token scoped to **Object Read & Write** on that bucket. Save the Account ID, Access Key ID and Secret Access Key in `.env`, with `R2_BUCKET` and an HTTPS `R2_PUBLIC_URL`.
3. Restart the app. Successful audio generation then attempts to upload audio and publish the feed. Drafts and failed audio are excluded. Errors are shown with a voice-free publishing retry.
4. Optional: supply your own square PNG as `static/logo.png`, ideally 3000×3000, then run the environment's Python with `upload_logo.py`. Without it, feed artwork may be missing.
5. Generate/publish at least one episode, then add `{R2_PUBLIC_URL}/feed.xml` by URL in your podcast app.

**This is a publicly accessible feed, not a private feed.** Anyone with the URLs can access the objects. Rename keeps the same episode ID/GUID; deletion updates the feed and removes tracked R2 audio versions. Restoring the original R2 configuration is necessary when deleting an episode published to a different location. Downloaded/cached copies are outside the app's control.

Local files use immutable IDs; re-voicing writes a new audio version and preserves previous local versions until deletion. Back up the whole generated-data folders, not just the latest JSON backup. Metadata writes use a lock, atomic replacement and a last-good backup. Remote operations are not a transaction; failures are reported and retryable.

## Privacy, safety and rights

This is a **single-user local application**, not a hosted service. Keep the loopback binding and debugger off. It rejects non-loopback clients and unexpected hosts, and requires session-bound CSRF tokens for mutations. Do not expose it through tunnels, reverse proxies or a network port; these controls are not a login system.

Extracted paper text is sent to Anthropic; the script is sent to ElevenLabs. Source PDFs/scripts are saved locally. Configuring R2 publishes generated audio/show notes; source PDFs are not uploaded to R2 by this app. Do not process confidential papers without permission to send them to those providers. Check providers' current data terms.

Review scripts against their sources: summaries can misstate results, invent references or overstate conclusions. The voice-edit pass is editorial only. Code licensing grants no rights to source papers, third-party artwork or voices. Publish only material you have the necessary rights to use.

## Utilities

Optional local transcription needs [FFmpeg](https://ffmpeg.org/download.html) on PATH and Whisper:

```bash
# Use .\.venv\Scripts\python.exe instead on Windows.
.venv/bin/python -m pip install -r requirements-optional.txt
.venv/bin/python transcribe_episode.py EPISODE_ID
```

The utility checks the episode/audio and FFmpeg before loading Whisper. Its first run downloads the `base` model. Review the transcription before re-voicing it. Whisper/FFmpeg installation and execution are separate from the core app and not covered by the core clean-install check.

## Testing and contributing

```bash
# Use .\.venv\Scripts\python.exe instead on Windows.
.venv/bin/python -m pip install -r requirements-dev.txt -c constraints.txt
.venv/bin/python -m pytest -q
```

Tests use temporary libraries, synthetic PDFs and mocked providers. They cover request protection, escaping, path validation, concurrent writes, stream failures, model selection/cache behavior, source limits and publishing retries. GitHub Actions defines macOS/Windows on Python 3.10 and 3.13. **A defined workflow is not a recorded Windows pass**: check the Actions result before claiming Windows support has been verified.

Before a release, run one paid Short episode with your own keys, record the model IDs/actual billed usage, listen to the audio, verify an R2 feed in a podcast client, and run the Windows workflow. Automated tests cannot confirm provider-account entitlements or speech quality. Do not put live secrets into tests.

Main code: `app.py`; persistence: `storage.py`; PDF worker: `pdf_text.py`; UI: `templates/` and `static/ui.js`; tests: `tests/`. `constraints.txt` records the tested package set. Update constraints deliberately and rerun checks.

## License and artwork

Original application code is MIT; see [LICENSE](LICENSE). Dependency licenses and optional-tool limitations are documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). PyMuPDF and Mutagen have been replaced; the direct core dependencies use permissive licenses; see the notices for transitive licenses, including Certifi’s MPL-2.0.

The simple `static/favicon.svg` was authored for this project under MIT. The older raster favicon assets have been removed from the current tree because their provenance was undocumented; they remain in git history. Supply artwork you have permission to publish. Screenshots contain demonstration paper titles and are not paper reproductions.

## Upgrading an existing library

Back up `static/` and `.env` first. On first read, invalid or duplicate v1 IDs are assigned permanent UUIDs under the library lock. Each migration saves a timestamped `episodes.json.migration.*.bak` (the first also keeps `episodes.json.migration.bak`), copies safely located audio/PDF files to the new IDs, and preserves original files plus `legacy_slug`/`legacy_files`. Duplicate v1 entries may already share overwritten media; migration cannot recover lost versions. Missing/unsafe files are left as drafts with a migration warning.

New R2 publications store account, bucket and object keys independently of the public domain. Changing only `R2_PUBLIC_URL` is safe; republish existing episodes to update their feed URLs. For legacy episodes whose old domain differs, verify the configured bucket contains their original audio, then choose **Adopt R2 location** in the library. The app requires matching stored byte counts and verifies each bucket object against its local original using SHA-256 before recording the location. Restore the original local audio if it is missing or has been re-voiced. This proves matching content, not historical bucket ownership: your confirmation still identifies the bucket you intend to manage. Arbitrary old public URLs are never fetched. Account/bucket mismatches and disabled R2 are rejected before deletion starts. After a remote request has begun, a failure remains marked pending because the server may already have applied it; retry Delete after fixing connectivity.

Obsidian exports use a readable title plus full ID, retain that filename after renaming, and include a title heading and audio link. Flash v2.5 is the default speech model following [ElevenLabs guidance](https://elevenlabs.io/docs/overview/models); existing Turbo episodes remain supported.

Existing v1 Obsidian `slug.md` notes are left untouched. The first new export creates a separate titled note to preserve any hand edits; reconcile them manually if desired. Migrated published records retain a non-empty, unique legacy feed GUID. Empty or duplicate legacy GUIDs cannot be preserved uniquely, so podcast clients may show those migrated records as new episodes.
