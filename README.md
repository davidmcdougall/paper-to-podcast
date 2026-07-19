# Paper to Podcast

Upload an academic PDF → get a spoken podcast episode.

Claude reads the paper and writes a 700–1000 word spoken script — expert-level analysis, no citations or equations, structured as a narrative argument. ElevenLabs voices it. If you configure Cloudflare R2, episodes are published to an RSS feed you can subscribe to in any podcast app.

---

## What you need

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com) — Claude does the writing (~$0.05–0.20 per episode with Sonnet)
- An [ElevenLabs API key](https://elevenlabs.io) — voices the script (~$0.10–0.30 per episode)
- *(Optional)* A [Cloudflare R2](https://developers.cloudflare.com/r2/) account for podcast feed hosting (free tier covers most personal use)

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/davidmcdougall/paper-to-podcast.git
cd paper-to-podcast
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure your environment**

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
PODCAST_TITLE=My Research Podcast
```

See `.env.example` for all options with explanations.

**4. Run the server**

```bash
python3 app.py
```

Open [http://localhost:5050](http://localhost:5050). Upload a PDF or paste an arXiv ID and press Generate.

---

## Setting up the podcast feed (optional)

Without R2, audio is stored locally and playable from the web UI at `localhost:5050/library`. With R2, episodes are uploaded and an RSS feed is published — subscribe once in Overcast, Pocket Casts, or Apple Podcasts and new episodes appear automatically.

**1. Create a Cloudflare R2 bucket**

- Go to the [Cloudflare dashboard](https://dash.cloudflare.com) → R2 → Create bucket
- Name it `paper-to-podcast` (or whatever you'd like — just set `R2_BUCKET` to match)
- Under the bucket's **Settings** tab, enable **Public access** and note the public URL (looks like `https://pub-xxxx.r2.dev`)

**2. Create an API token**

- In the R2 section, go to **Manage R2 API Tokens** → Create API Token
- Permissions: **Object Read & Write** scoped to your bucket
- Copy the Account ID, Access Key ID, and Secret Access Key

**3. Add to your `.env`**

```
R2_ACCOUNT_ID=your-cloudflare-account-id
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_KEY=your-secret-key
R2_BUCKET=paper-to-podcast
R2_PUBLIC_URL=https://pub-xxxx.r2.dev
```

**4. Upload a podcast logo** *(optional but recommended)*

Podcast apps display artwork. Upload a square PNG (3000×3000px recommended) to `images/logo.png` in your R2 bucket.

**5. Subscribe**

Your RSS feed URL is `{R2_PUBLIC_URL}/feed.xml`. Add it to any podcast app as a private/custom feed.

---

## Choosing a voice

By default, Paper to Podcast uses the first voice in your ElevenLabs account. To pick a specific voice:

1. Browse the [ElevenLabs Voice Library](https://elevenlabs.io/voice-library) and add a voice to your account
2. Open the voice in your ElevenLabs dashboard, copy the Voice ID from the URL or settings panel
3. Set `ELEVENLABS_VOICE_ID=<your-voice-id>` in `.env`

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | From [console.anthropic.com](https://console.anthropic.com) |
| `ELEVENLABS_API_KEY` | Yes | From [elevenlabs.io](https://elevenlabs.io) → Profile → API Keys |
| `PODCAST_TITLE` | No | Your podcast name (default: "Paper to Podcast") |
| `PODCAST_DESCRIPTION` | No | Feed description shown in podcast apps |
| `PODCAST_AUTHOR` | No | Author name shown in podcast apps |
| `ELEVENLABS_VOICE_ID` | No | Leave blank to use first voice in your account |
| `OBSIDIAN_VAULT_PATH` | No | Path to Obsidian vault folder — saves a Zettelkasten note per episode |
| `R2_ACCOUNT_ID` | No | Cloudflare account ID (enables podcast feed) |
| `R2_ACCESS_KEY_ID` | No | R2 API token access key |
| `R2_SECRET_KEY` | No | R2 API token secret |
| `R2_BUCKET` | No | R2 bucket name (default: `paper-to-podcast`) |
| `R2_PUBLIC_URL` | No | R2 public URL, e.g. `https://pub-xxxx.r2.dev` |

---

## Notes

- **Text-based PDFs only.** Scanned or image-based PDFs won't work — no OCR. arXiv papers work perfectly.
- **Cost.** A typical paper costs roughly $0.15–0.50 total across Claude and ElevenLabs. Claude Sonnet does the writing (two passes); Haiku handles cheaper tasks like metadata and show notes.
- **Episode library.** Browse all episodes at [http://localhost:5050/library](http://localhost:5050/library).

## Project structure

```
paper-to-podcast/
├── app.py                      # Flask backend (port 5050)
├── templates/
│   ├── index.html              # Upload UI
│   └── library.html            # Episode library
├── static/
│   ├── audio/                  # Generated MP3s (gitignored)
│   └── pdfs/                   # Uploaded source PDFs (gitignored)
├── transcribe_episode.py       # Utility: transcribe existing MP3 → patch episodes.json
├── upload_logo.py              # Utility: upload podcast artwork to R2
├── script-prompt-evaluation.md # Notes on the script-generation prompt
├── requirements.txt
├── .env.example
└── LICENSE
```

## License

MIT — see [LICENSE](LICENSE).
