# Paper to Podcast — Developer Notes

Context for working on this codebase with Claude Code or any AI assistant.

## What it does

Converts academic PDFs into podcast episodes. Upload a paper → Claude writes a spoken script → ElevenLabs voices it → (optionally) publishes to an RSS feed that appears in any podcast app.

## How it works

1. Upload a PDF via the web UI at `localhost:5050` (or paste an arXiv ID)
2. Claude rewrites the paper as a 700–1000 word spoken script (expert-level, no citations or equations)
3. ElevenLabs voices the script → MP3
4. If Cloudflare R2 is configured: MP3 uploaded to R2 and the RSS feed is updated
5. New episode appears automatically in any subscribed podcast app

## Running the server

```bash
cd paper-to-podcast
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
python3 app.py
# Opens at http://localhost:5050
```

## Configuration

All configuration is via environment variables — see `.env.example` for the full list with explanations. Required: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`. Optional: podcast identity (`PODCAST_TITLE`, `PODCAST_DESCRIPTION`, `PODCAST_AUTHOR`), a specific ElevenLabs voice, an Obsidian vault path for Markdown summaries, and Cloudflare R2 credentials to enable the published podcast feed.

## Artwork

The podcast logo is not committed. Drop your own square PNG at `static/logo.png` for the web UI header, and (if using R2) run `python3 upload_logo.py` to publish it to your feed.

## Constraints

- Text-based PDFs only (arXiv papers are ideal). Scanned/image PDFs won't work — there's no OCR.
- Episodes are saved to `static/episodes.json` and browsable at `localhost:5050/library`.

## Working on the code

The main file to edit is `app.py`. Templates are in `templates/`. Test changes by restarting the server (`Ctrl+C` then `python3 app.py`), or set `FLASK_DEBUG=1` in `.env` for auto-reload.
