import os
import re
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import fitz  # PyMuPDF
import anthropic
import boto3
from botocore.client import Config
from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
from pathlib import Path
try:
    from mutagen.mp3 import MP3 as MutagenMP3
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

load_dotenv()

app = Flask(__name__)

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

PDF_DIR = Path("static/pdfs")
PDF_DIR.mkdir(parents=True, exist_ok=True)

EPISODES_FILE = Path("static/episodes.json")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")

# Podcast identity
PODCAST_TITLE       = os.getenv("PODCAST_TITLE", "Paper to Podcast")
PODCAST_DESCRIPTION = os.getenv("PODCAST_DESCRIPTION", "Academic papers turned into podcast episodes.")
PODCAST_AUTHOR      = os.getenv("PODCAST_AUTHOR", PODCAST_TITLE)

# Cloudflare R2
R2_ACCOUNT_ID     = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID  = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_KEY     = os.getenv("R2_SECRET_KEY", "")
R2_BUCKET         = os.getenv("R2_BUCKET", "paper-to-podcast")
R2_PUBLIC_URL     = os.getenv("R2_PUBLIC_URL", "").rstrip("/")  # e.g. https://pub-xxxx.r2.dev

R2_ENABLED = all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_KEY, R2_PUBLIC_URL])

# ── Script generation: models and length ─────────────────────────────────────
# Current Claude text models the writing step can use. Keep in sync with the
# dropdown in templates/index.html. Add or remove entries here freely.
TEXT_MODELS = [
    "claude-opus-4-8",             # highest quality / deepest reasoning
    "claude-sonnet-5",             # balanced (default)
    "claude-haiku-4-5-20251001",   # fastest / cheapest
    "claude-fable-5",              # creative
]
DEFAULT_TEXT_MODEL = os.getenv("TEXT_MODEL", "claude-sonnet-5")

# Length presets → target spoken word count. ~150 words per minute.
WORDS_PER_MINUTE = 150
LENGTH_PRESETS = {
    "short":    450,    # ~3 min
    "standard": 1000,   # ~7 min
    "long":     2200,   # ~15 min
    "deep":     3600,   # ~24 min
}
DEFAULT_LENGTH = "standard"


def resolve_model(form) -> str:
    """Pick the writing model from the request, falling back to the default."""
    model = (form.get("model") or DEFAULT_TEXT_MODEL).strip()
    return model if model in TEXT_MODELS else DEFAULT_TEXT_MODEL


def resolve_target_words(form) -> int:
    """Translate the length choice (preset or custom minutes) into a word target."""
    length = (form.get("length") or DEFAULT_LENGTH).strip().lower()
    if length == "custom":
        try:
            minutes = float(form.get("target_minutes", "7"))
        except (TypeError, ValueError):
            minutes = 7
        minutes = max(1.0, min(40.0, minutes))
        return int(round(minutes * WORDS_PER_MINUTE))
    return LENGTH_PRESETS.get(length, LENGTH_PRESETS[DEFAULT_LENGTH])


PODCAST_PROMPT = """You are writing a solo podcast episode on an academic paper. The style is intellectually intense, fast-moving, and substantive: a smart researcher thinking aloud, not a host performing surprise.

Write for a listener who already knows the broad field. Do not explain the discipline. No NPR-style setup, fake suspense, or throat-clearing. Open with the paper's core finding or central claim in the first sentence.

STEP ONE — identify the paper type and adapt accordingly:
- Empirical paper: finding, design, result, mechanism, external validity
- Benchmark paper: what is being measured, why prior evaluations missed it, what changes if the benchmark is right
- Methods paper: what the method makes possible, what assumptions it relies on, where it fails
- Theory paper: core distinction, what it explains better than rival frames, what would test it
- Review paper: map of the field, live disagreement, hidden synthesis
- Position paper: strongest claim, weakest premise, consequence if the authors are right

STEP TWO — before writing, identify the episode's central tension. The script should feel like one argument unfolding, not a sequence of smart observations. That tension should appear early and return at the end.

OPENING: The very first sentence must name the paper and its authors.
- 1–3 authors: use each author's full name exactly as it appears in the paper. Example: "Today we're looking at 'Adaptive Experimentation in the Real World' by Erik Snowberg and Leeat Yariv."
- 4 or more authors: name only the first author and add "and colleagues." Example: "Today we're looking at 'Scaling Laws for Neural Language Models' by Jared Kaplan and colleagues."
- On the first mention of any author anywhere in the script, always use their full name. Surname only on all subsequent mentions.

STRUCTURE: 70% paper content, 30% critical reach.

Paper content section:
- Do not follow the paper's section order. Reconstruct the argument in the order a smart listener needs: result, setup, test, mechanism, implication.
- Cover the specific experiments, arguments, controls, numbers, and conditions that matter.
- Include methods only when they change how much we should believe the result.
- Every number should answer "compared to what?" No orphan statistics.
- Every sentence adds a new fact, distinction, mechanism, or inference. Do not summarise passively — think through the finding.

Analytical section — use the paper type identified in STEP ONE to select the right moves. Do not use all of them; choose the one or two that cut deepest for this specific paper.

Empirical paper: Name the hidden assumption in the design or sample. State what the result would mean if the mechanism generalised beyond the study context. Name the strongest alternative explanation the data cannot rule out.

Benchmark paper: Show what practitioner behaviour changes if this benchmark is adopted. Identify what the benchmark cannot measure even in principle. Name the domain where its assumptions break hardest.

Methods paper: State what the method makes possible that was previously intractable. Identify the cheapest way to break it. Say whether the gain over existing methods is marginal or categorical.

Theory paper: Say whether the core distinction is genuinely new or a relabelling of existing concepts. Name one empirical result the theory predicts that competing accounts cannot. State what would have to be true for the theory to be wrong.

Review paper: Name the live disagreement the field is not acknowledging. State the synthesis the reviewed papers resist. Identify what a follow-up meta-analysis would need to settle the dispute.

Position paper: Identify the weakest premise in the argument. State what the position implies that its authors have not followed through on. Name the strongest empirical finding that bears on the central claim.

In all cases: one outside reference doing real explanatory work — an adjacent finding, a framework from another field, a thinker whose position this evidence bears on. If removing it would not damage the explanation, cut it.

Claim ladder — distinguish these precisely:
- "The paper shows X" — directly supported by the data
- "The paper implies Y" — strong inference
- "The tempting but unproven claim is Z" — hypothesis
- "The paper cannot tell us W" — boundary

State positions directly when the evidence warrants it. When the paper's interpretation outruns its data, name the exact leap. Do not inflate the paper's importance — the goal is to locate the exact place where it changes the listener's model, not to make every paper sound world-historical.

Precision rules:
- Avoid near-universals. "The dominant X" is almost always more accurate than "virtually all X" or "most X."
- Avoid specific quantities not stated in the paper. If you are inferring a scale or magnitude, describe the components of the process instead of naming a number.
- When a finding inverts the expected relationship, name who is in the unexpected position and describe their specific condition. Do not describe the structure of the asymmetry — describe the party caught in it.

Style rules:
- 700–1000 words. Plain spoken English. No bullet points, headers, or markdown.
- No "let me explain", "what this means is", "in other words", "to put it simply", "you might be wondering", "as shown in Figure 3."
- Do not announce that something is interesting, damning, strange, or uncomfortable. Make the sentence itself prove it.
- No direct quotation unless the paper coins a term the listener needs. Translate technical claims into precise spoken prose.
- Vary sentence length: short for pressure, longer for causal reasoning.
- Paragraphs are listenable units — usually 3 to 6 sentences, each paragraph with one job: finding, setup, contrast, mechanism, implication, objection, or unresolved tension.
- End with a precise question, not a statement about what we don't know. The question should restate the episode's central tension in fresh language — a callback, not a summary.

Before returning the script, run a silent revision pass covering four checks:

1. Technical calibration. Find any claim that is technically exact: "bit-for-bit," "cannot," "never," "always," "fully solves," "zero," "identical," specific numbers not in the paper. If the claim depends on implementation detail, benchmark setting, hardware generation, or contested definition, replace it with precise but defensible language. Do not weaken the argument — sharpen its accuracy. "Mathematically equivalent up to floating-point operation order" is stronger than "bit-for-bit identical" because it is actually true.

2. Reference necessity. Delete any outside reference that could be removed without damaging the explanation. Ask: does this reference change what the listener understands about the mechanism? If not, cut it. One reference doing real work is better than two that signal erudition.

3. Paragraph density. If a paragraph contains more than three distinct mechanisms, findings, or claims, either split it into two paragraphs or cut the weakest item. Dense paragraphs read well; they do not listen well.

4. Ending freshness. Do not force a binary framing (account A vs account B) unless the paper genuinely creates exactly two competing interpretations with different predictions. A binary ending is a structure, not a default. If the paper leaves one precise question unresolved, end on that question alone.

Do not include stage directions, sound effects, or music cues. Just the spoken script."""

SUMMARY_PROMPT = """You are writing a permanent note for a researcher's Zettelkasten. This is not an abstract or a summary — it is an atomic, opinionated, linkable record of what this paper does, why it matters, and what it leaves unresolved.

Write a Markdown note (300–400 words) with these five sections:

## Claim
One sentence. State the core finding or thesis as a direct claim about the world, not about the paper. "X causes Y under condition Z" not "This paper shows that X may cause Y."

## Mechanism
Two to four sentences. What is the causal or logical chain that produces the claim? Be specific about what drives what. If the paper is empirical, name the key design choice that makes the result believable (or not).

## Context
Name what this extends, displaces, or contradicts. Cite specific prior findings or named frameworks — not vague gestures at "the literature." If this paper is in tension with something you know the researcher is likely to have encountered, say so directly.

## Limits
State the single most important thing this paper cannot establish. Name the confound it cannot rule out, the population it cannot generalise to, or the assumption that, if wrong, undoes the result. Be specific — "small sample" is not a limit; "N=48 undergraduates at one US university, no replication" is.

## Connections
Two to three short bullets. Each bullet names a concept, finding, or question this paper connects to — material for future links in the Zettelkasten. Write them as phrases the researcher can use as search terms or note titles, not full sentences. These should be intellectually live connections, not obvious category memberships.

Rules:
- Lead every section with the substance, not a meta-statement about the section
- No throat-clearing: "this paper explores", "the authors argue that", "this study investigates"
- Take positions. "The limit here is X" not "future research could explore X."
- Plain Markdown with the headers above. No citations, no equations."""

VOICE_PASS_PROMPT = """You are editing a podcast script for spoken audio delivery. Your job is purely editorial — preserve every substantive claim, fact, argument, and example exactly as written. Do not add ideas, remove ideas, or change the meaning of any sentence.

Make only these changes:
- Break sentences that are too long to follow on first hearing into two or three shorter ones
- Remove essay-register phrasing ("That reframing has a consequence", "It is worth noting that", "This is more specific than")
- Replace abstract transitions with concrete contrasts or direct continuation
- Ensure any sentence that introduces a new concept gives the listener a beat before the next one arrives
- Prefer active constructions over passive where it doesn't change the meaning
- When a comparison group appears, flag it before naming it. Then state each side of the comparison in its own short sentence.
- When a borrowed theoretical framework is named, translate its terms into what physically happens. Use the phenomenon, not the formalism — "both sounds get pulled into the same category" not "within the attractor basin of a single native prototype."
- Split any paragraph that contains more than three distinct mechanisms or claims. If all three are essential, split; if one is weaker, cut it.

Return the full edited script only. Begin the script directly — no preamble, no "Here is the edited script:", no commentary."""


SHOW_NOTES_PROMPT = """Write podcast show notes for an episode about an academic paper. The listener is browsing their podcast app deciding whether to press play.

Write 3–4 sentences of plain prose. No markdown, no headers, no bullet points.

Sentence 1: The core finding or argument — stated as a direct claim about the world, not a description of the paper.
Sentence 2: Why it matters or what it changes — the implication for how we think about the topic.
Sentences 3–4: What makes this paper interesting or surprising — the hook that earns a listen.

Rules:
- No throat-clearing: "In this episode", "This paper", "Today we discuss"
- Write as if describing a conversation, not summarising a document
- Plain text only — this will be displayed in a podcast app"""


METADATA_PROMPT = """Extract metadata from this academic paper and return ONLY a JSON object with two keys:
1. "authors": a list of author name strings (first + last name, e.g. ["Jane Smith", "John Doe"]). Empty list if not found.
2. "topics": a list of 3–5 short topic/theme tags (lowercase, 1–3 words each, e.g. ["urban sociology", "class conflict", "state theory"]).

Return only valid JSON, no markdown fences, no commentary."""


def fetch_arxiv_pdf(arxiv_input: str) -> tuple:
    """Fetch PDF bytes from arXiv given an ID or URL. Returns (pdf_bytes, filename)."""
    arxiv_id = arxiv_input.strip()
    # Strip URL prefixes
    for prefix in [
        "https://arxiv.org/abs/", "https://arxiv.org/pdf/",
        "http://arxiv.org/abs/",  "http://arxiv.org/pdf/",
        "arxiv.org/abs/",         "arxiv.org/pdf/",
    ]:
        if arxiv_id.lower().startswith(prefix):
            arxiv_id = arxiv_id[len(prefix):]
            break
    arxiv_id = arxiv_id.rstrip("/").removesuffix(".pdf")
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # strip version suffix e.g. v2, v3

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "PaperToPodcast/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        pdf_bytes = resp.read()

    if len(pdf_bytes) < 1000:
        raise ValueError(f"arXiv returned unexpectedly small response for ID '{arxiv_id}'. Check the ID.")

    return pdf_bytes, f"{arxiv_id}.pdf"


def fetch_arxiv_meta(arxiv_input: str) -> dict:
    """Return title and authors from the arXiv Atom API. Returns {} on failure."""
    arxiv_id = arxiv_input.strip()
    for prefix in [
        "https://arxiv.org/abs/", "https://arxiv.org/pdf/",
        "http://arxiv.org/abs/",  "http://arxiv.org/pdf/",
        "arxiv.org/abs/",         "arxiv.org/pdf/",
    ]:
        if arxiv_id.lower().startswith(prefix):
            arxiv_id = arxiv_id[len(prefix):]
            break
    arxiv_id = arxiv_id.rstrip("/").removesuffix(".pdf")
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "PaperToPodcast/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return {}

    title   = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
    authors = [
        (a.findtext("atom:name", "", ns) or "").strip()
        for a in entry.findall("atom:author", ns)
    ]
    return {"title": title, "authors": [a for a in authors if a]}


def smart_truncate(text: str, max_words: int) -> str:
    """Sample from head, middle, and tail rather than truncating from the front.
    This preserves coverage of methods / results / discussion for longer papers."""
    words = text.split()
    if len(words) <= max_words:
        return text
    head  = int(max_words * 0.40)
    tail  = int(max_words * 0.20)
    mid   = max_words - head - tail
    mid_start = len(words) // 2 - mid // 2
    mid_end   = mid_start + mid
    return " ".join(
        words[:head]
        + ["[…]"]
        + words[mid_start:mid_end]
        + ["[…]"]
        + words[-tail:]
    )


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def extract_title(text: str) -> str:
    """Best-effort title extraction: first non-empty line, truncated."""
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 10:
            return line[:120]
    return "Untitled Paper"


def generate_podcast_script(paper_text: str, notes: str = "",
                            target_words: int = 1000, model: str = None) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    model = model if model in TEXT_MODELS else DEFAULT_TEXT_MODEL

    # Longer scripts need broader coverage of the source; scale the input window.
    input_cap = max(12000, target_words * 6)
    truncated = smart_truncate(paper_text, input_cap)

    # Rewrite the prompt's length target to match the requested length.
    low, high = max(150, round(target_words * 0.85)), round(target_words * 1.15)
    prompt = PODCAST_PROMPT.replace("700–1000 words", f"{low}–{high} words")

    notes_section = f"\n\nAdditional instructions for this script:\n{notes.strip()}" if notes and notes.strip() else ""

    # Token budget must cover the (larger) output for long scripts.
    out_tokens = int(target_words * 1.8) + 1500

    # Pass 1: content and argument
    response = client.messages.create(
        model=model,
        max_tokens=out_tokens,
        messages=[
            {
                "role": "user",
                "content": f"{prompt}{notes_section}\n\nHere is the paper:\n\n{truncated}",
            }
        ],
    )
    # Extract the first text block
    draft = next(b.text for b in response.content if b.type == "text")

    # Pass 2: voice edit — preserve all claims, improve speakability (Haiku: editing not reasoning)
    final = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=int(target_words * 1.8) + 1000,
        messages=[
            {
                "role": "user",
                "content": f"{VOICE_PASS_PROMPT}\n\nScript to edit:\n\n{draft}",
            }
        ],
    ).content[0].text

    return final


def extract_metadata(paper_text: str) -> dict:
    """Extract authors and topics from the paper using Claude Haiku (cheap + fast)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # Metadata lives in the header/abstract — head-only is correct here
    truncated = " ".join(paper_text.split()[:3000])
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": f"{METADATA_PROMPT}\n\nPaper text:\n\n{truncated}",
                }
            ],
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
        return {
            "authors": [str(a) for a in data.get("authors", [])],
            "topics":  [str(t) for t in data.get("topics", [])],
        }
    except Exception:
        return {"authors": [], "topics": []}


def generate_summary(paper_text: str, title: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    truncated = smart_truncate(paper_text, 8000)
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=900,
        messages=[
            {
                "role": "user",
                "content": f"{SUMMARY_PROMPT}\n\nPaper title: {title}\n\nPaper text:\n\n{truncated}",
            }
        ],
    )
    return message.content[0].text


def generate_show_notes(paper_text: str, title: str, authors: list = None) -> str:
    """Generate plain-text podcast show notes optimised for podcast app episode listings."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    truncated = smart_truncate(paper_text, 6000)
    byline = ""
    if authors:
        if len(authors) == 1:
            byline = f" by {authors[0]}"
        elif len(authors) <= 3:
            byline = f" by {', '.join(authors[:-1])} and {authors[-1]}"
        else:
            byline = f" by {authors[0]} and colleagues"
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"{SHOW_NOTES_PROMPT}\n\nPaper: \"{title}\"{byline}\n\nPaper text:\n\n{truncated}",
        }],
    )
    return message.content[0].text.strip()


def get_voice_id(client: ElevenLabs) -> str:
    """Use the configured voice ID, or fall back to the first voice in the account."""
    if ELEVENLABS_VOICE_ID:
        return ELEVENLABS_VOICE_ID
    voices = client.voices.get_all()
    if not voices.voices:
        raise RuntimeError("No voices found in your ElevenLabs account.")
    return voices.voices[0].voice_id


def text_to_speech(script: str, filename: str, model_id: str = "eleven_turbo_v2_5") -> Path:
    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    voice_id = get_voice_id(client)
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script,
        model_id=model_id,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.35,        # lower = more expressive, varied delivery
            similarity_boost=0.75,
            style=0.45,            # adds energy and rhythm variation
            use_speaker_boost=True,
            speed=1.15,            # ~15% faster than default
        ),
    )
    audio_path = AUDIO_DIR / filename
    with open(audio_path, "wb") as f:
        for chunk in audio_iter:
            if chunk:
                f.write(chunk)

    if audio_path.stat().st_size == 0:
        audio_path.unlink(missing_ok=True)
        raise RuntimeError(
            "ElevenLabs returned empty audio. "
            "Check your ELEVENLABS_API_KEY is correct and your account has quota remaining."
        )
    return audio_path


def get_audio_duration(audio_path: Path) -> int:
    """Return audio duration in seconds, or 0 if mutagen is unavailable."""
    if not MUTAGEN_AVAILABLE:
        return 0
    try:
        audio = MutagenMP3(str(audio_path))
        return int(audio.info.length)
    except Exception:
        return 0


def save_episode(title: str, slug: str, summary: str, script: str, pdf_name: str,
                 word_count: int, r2_url: str = None, file_size: int = 0,
                 authors: list = None, topics: list = None, pdf_url: str = None,
                 duration: int = 0, tts_model: str = "eleven_turbo_v2_5",
                 arxiv_id: str = None, show_notes: str = None):
    """Append episode metadata to episodes.json."""
    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            episodes = []

    # Remove any existing entry with the same slug (re-generation)
    episodes = [e for e in episodes if e.get("slug") != slug]

    episodes.insert(0, {
        "slug": slug,
        "title": title,
        "pdf_name": pdf_name,
        "pdf_url": pdf_url,
        "arxiv_id": arxiv_id or "",
        "show_notes": show_notes or "",
        "authors": authors or [],
        "topics": topics or [],
        "word_count": word_count,
        "summary": summary,
        "script": script,
        "audio_url": r2_url if r2_url else f"/static/audio/{slug}.mp3",
        "r2_url": r2_url,
        "file_size": file_size,
        "duration": duration,
        "tts_model": tts_model,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
    })

    EPISODES_FILE.write_text(json.dumps(episodes, indent=2))


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_to_r2(local_path: Path, key: str, content_type: str = "audio/mpeg") -> str:
    """Upload a file to R2 and return its public URL."""
    client = get_r2_client()
    client.upload_file(
        str(local_path),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{R2_PUBLIC_URL}/{key}"


def build_rss(episodes: list) -> str:
    """Generate RSS 2.0 feed XML from episode list."""
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for ep in episodes:
        pub_date = ep.get("date", now)
        try:
            dt = datetime.datetime.fromisoformat(pub_date)
            pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            pub_date = now

        audio_url = ep.get("r2_url") or ep.get("audio_url", "")
        size_bytes = ep.get("file_size", 0)
        duration_secs = ep.get("duration", 0)
        title = ep.get("title", "Untitled").replace("&", "&amp;")

        # Use dedicated show notes if available, fall back to Zettelkasten summary
        desc_text = ep.get("show_notes") or ep.get("summary", "")
        arxiv_id = ep.get("arxiv_id", "")
        if arxiv_id:
            desc_text += f"\n\nhttps://arxiv.org/abs/{arxiv_id}"
        summary = desc_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        duration_tag = f"\n      <itunes:duration>{duration_secs}</itunes:duration>" if duration_secs else ""

        items.append(f"""    <item>
      <title>{title}</title>
      <description><![CDATA[{summary}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{ep.get('slug', '')}</guid>
      <enclosure url="{audio_url}" length="{size_bytes}" type="audio/mpeg"/>{duration_tag}
    </item>""")

    items_xml = "\n".join(items)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{PODCAST_TITLE}</title>
    <description>{PODCAST_DESCRIPTION}</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:author>{PODCAST_AUTHOR}</itunes:author>
    <itunes:image href="{R2_PUBLIC_URL}/images/logo.png"/>
    <image>
      <url>{R2_PUBLIC_URL}/images/logo.png</url>
      <title>{PODCAST_TITLE}</title>
      <link>{R2_PUBLIC_URL}</link>
    </image>
    <itunes:category text="Education"/>
    <itunes:explicit>false</itunes:explicit>
{items_xml}
  </channel>
</rss>"""


def publish_feed():
    """Rebuild feed.xml from episodes.json and upload to R2."""
    if not R2_ENABLED:
        return

    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass

    rss = build_rss(episodes)
    feed_path = Path("static/feed.xml")
    feed_path.write_text(rss, encoding="utf-8")
    upload_to_r2(feed_path, "feed.xml", content_type="application/rss+xml")


def save_to_obsidian(title: str, slug: str, summary: str, pdf_name: str, word_count: int,
                     topics: list = None, audio_url: str = None,
                     authors: list = None, arxiv_id: str = None):
    """Write Markdown summary to Obsidian vault. Returns path written, or None if vault not configured."""
    vault_path = OBSIDIAN_VAULT_PATH.strip()
    if not vault_path:
        return None

    vault = Path(vault_path).expanduser()
    if not vault.exists():
        return None

    today = datetime.date.today().isoformat()

    # Build YAML tag list: topics + fixed tags
    tag_list = list(topics or []) + ["research", "podcast"]
    tags_yaml = "\n".join(f"  - {t}" for t in tag_list)

    authors_yaml = ""
    if authors:
        authors_yaml = "\nauthors:\n" + "\n".join(f'  - "{a}"' for a in authors)

    arxiv_line = f'\narxiv_id: "{arxiv_id}"' if arxiv_id else ""
    audio_line = f'\naudio_url: "{audio_url}"' if audio_url else ""

    frontmatter = f"""---
title: "{title}"
date: {today}
source: "{pdf_name}"{authors_yaml}{arxiv_line}
word_count: {word_count}
tags:
{tags_yaml}{audio_line}
---

"""

    # Body: heading, optional listen link, then the Zettelkasten summary
    listen_section = f"[Listen to episode]({audio_url})\n\n" if audio_url else ""
    content = frontmatter + f"# {title}\n\n{listen_section}" + summary

    output_path = vault / f"{slug}.md"
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/library")
def library():
    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass
    return render_template("library.html", episodes=episodes)


@app.route("/episodes.json")
def episodes_json():
    if EPISODES_FILE.exists():
        return EPISODES_FILE.read_text(), 200, {"Content-Type": "application/json"}
    return "[]", 200, {"Content-Type": "application/json"}


@app.route("/static/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


@app.route("/arxiv-meta")
def arxiv_meta_endpoint():
    arxiv_input = request.args.get("id", "").strip()
    if not arxiv_input:
        return jsonify({}), 400
    try:
        return jsonify(fetch_arxiv_meta(arxiv_input))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _prepare_episode(req):
    """
    Steps 1–3b: parse input → extract text → generate script → parallel tasks → save draft.
    Returns (episode_dict, None) on success, or (None, error_response_tuple) on failure.
    """
    arxiv_id = req.form.get("arxiv_id", "").strip()

    if arxiv_id:
        try:
            pdf_bytes, pdf_name = fetch_arxiv_pdf(arxiv_id)
        except Exception as e:
            return None, (jsonify({"error": f"arXiv fetch failed: {str(e)}"}), 400)
    elif "pdf" in req.files:
        pdf_file = req.files["pdf"]
        if not pdf_file.filename.lower().endswith(".pdf"):
            return None, (jsonify({"error": "File must be a PDF"}), 400)
        pdf_bytes = pdf_file.read()
        pdf_name = pdf_file.filename
    else:
        return None, (jsonify({"error": "Provide a PDF file or an arXiv ID"}), 400)

    try:
        paper_text = extract_text_from_pdf(pdf_bytes)
    except Exception as e:
        return None, (jsonify({"error": f"PDF extraction failed: {str(e)}"}), 500)

    if len(paper_text.strip()) < 200:
        return None, (jsonify({"error": "Could not extract text — this may be a scanned/image PDF."}), 400)

    custom_title = req.form.get("custom_title", "").strip()
    stem = Path(pdf_name).stem
    if custom_title:
        title = custom_title
        slug  = slugify(custom_title)
    else:
        # For arXiv papers without a custom title, fetch the real title server-side
        arxiv_id_clean = req.form.get("arxiv_id", "").strip()
        server_title = ""
        if arxiv_id_clean:
            try:
                server_title = fetch_arxiv_meta(arxiv_id_clean).get("title", "")
            except Exception:
                pass
        title = server_title or re.sub(r"[-_]+", " ", stem).strip()
        slug  = slugify(title)

    tts_model = req.form.get("tts_model", "eleven_turbo_v2_5")
    if tts_model not in ("eleven_turbo_v2_5", "eleven_multilingual_v2"):
        tts_model = "eleven_turbo_v2_5"

    notes = req.form.get("notes", "").strip()
    target_words = resolve_target_words(req.form)
    text_model   = resolve_model(req.form)

    try:
        script = generate_podcast_script(paper_text, notes=notes,
                                         target_words=target_words, model=text_model)
    except Exception as e:
        return None, (jsonify({"error": f"Claude API error: {str(e)}"}), 500)

    word_count = len(script.split())

    def _summary():
        try:    return generate_summary(paper_text, title)
        except: return ""

    def _metadata():
        try:    return extract_metadata(paper_text)
        except: return {"authors": [], "topics": []}

    def _save_pdf():
        try:
            (PDF_DIR / f"{slug}.pdf").write_bytes(pdf_bytes)
            return f"/static/pdfs/{slug}.pdf"
        except Exception as e:
            app.logger.warning(f"PDF save failed: {e}")
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_s, f_m, f_p = pool.submit(_summary), pool.submit(_metadata), pool.submit(_save_pdf)
        # Show notes need authors, so fetch metadata first — but we can't wait inside the pool.
        # Instead, generate show notes after metadata resolves (cheap sequential step).

    summary = f_s.result()
    meta    = f_m.result()
    authors = meta.get("authors", [])
    topics  = meta.get("topics", [])
    pdf_url = f_p.result()

    try:
        show_notes = generate_show_notes(paper_text, title, authors)
    except Exception:
        show_notes = ""

    arxiv_id = req.form.get("arxiv_id", "").strip()

    try:
        save_episode(title, slug, summary, script, pdf_name, word_count,
                     authors=authors, topics=topics, pdf_url=pdf_url, tts_model=tts_model,
                     arxiv_id=arxiv_id, show_notes=show_notes)
    except Exception:
        pass

    return {
        "title": title, "slug": slug, "script": script, "summary": summary,
        "show_notes": show_notes,
        "authors": authors, "topics": topics, "pdf_url": pdf_url,
        "pdf_name": pdf_name, "word_count": word_count,
        "audio_filename": f"{slug}.mp3", "tts_model": tts_model,
        "arxiv_id": arxiv_id,
    }, None


@app.route("/generate-script", methods=["POST"])
def generate_script_only():
    """Run Claude passes only — no TTS. Frontend can preview script then call /regenerate-audio."""
    ep, err = _prepare_episode(request)
    if err:
        return err
    return jsonify({
        "title":      ep["title"],
        "slug":       ep["slug"],
        "script":     ep["script"],
        "summary":    ep["summary"],
        "word_count": ep["word_count"],
    })


@app.route("/generate", methods=["POST"])
def generate():
    ep, err = _prepare_episode(request)
    if err:
        return err

    title          = ep["title"]
    slug           = ep["slug"]
    script         = ep["script"]
    summary        = ep["summary"]
    authors        = ep["authors"]
    topics         = ep["topics"]
    pdf_url        = ep["pdf_url"]
    pdf_name       = ep["pdf_name"]
    word_count     = ep["word_count"]
    audio_filename = ep["audio_filename"]
    tts_model      = ep["tts_model"]

    try:
        audio_path = text_to_speech(script, audio_filename, model_id=tts_model)
    except Exception as e:
        return jsonify({"error": f"ElevenLabs error: {str(e)}"}), 500

    r2_url    = None
    file_size = audio_path.stat().st_size
    duration  = get_audio_duration(audio_path)
    if R2_ENABLED:
        try:
            r2_url = upload_to_r2(audio_path, f"audio/{audio_filename}")
        except Exception as e:
            app.logger.warning(f"R2 upload failed: {e}")

    try:
        save_episode(title, slug, summary, script, pdf_name, word_count,
                     r2_url=r2_url, file_size=file_size,
                     authors=authors, topics=topics, pdf_url=pdf_url,
                     duration=duration, tts_model=tts_model,
                     arxiv_id=ep.get("arxiv_id", ""),
                     show_notes=ep.get("show_notes", ""))
    except Exception:
        pass

    if R2_ENABLED and r2_url:
        try:
            publish_feed()
        except Exception as e:
            app.logger.warning(f"Feed publish failed: {e}")

    audio_url = r2_url if r2_url else f"/static/audio/{audio_filename}"

    obsidian_path = None
    try:
        obsidian_path = save_to_obsidian(title, slug, summary, pdf_name, word_count,
                                         topics=topics, audio_url=audio_url,
                                         authors=authors, arxiv_id=ep.get("arxiv_id", ""))
    except Exception:
        pass

    return jsonify({
        "title":         title,
        "script":        script,
        "summary":       summary,
        "audio_url":     audio_url,
        "word_count":    word_count,
        "r2_enabled":    R2_ENABLED,
        "obsidian_saved": obsidian_path is not None,
    })


@app.route("/rename/<slug>", methods=["POST"])
def rename_episode(slug):
    new_title = request.json.get("title", "").strip()
    if not new_title:
        return jsonify({"error": "Title required"}), 400

    new_slug = slugify(new_title)

    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass

    for ep in episodes:
        if ep.get("slug") == slug:
            # Rename MP3 on disk
            old_mp3 = AUDIO_DIR / f"{slug}.mp3"
            new_mp3 = AUDIO_DIR / f"{new_slug}.mp3"
            if old_mp3.exists():
                old_mp3.rename(new_mp3)
            ep["slug"] = new_slug
            ep["title"] = new_title
            ep["audio_url"] = f"/static/audio/{new_slug}.mp3"
            break

    EPISODES_FILE.write_text(json.dumps(episodes, indent=2))
    return jsonify({"ok": True, "new_slug": new_slug})


@app.route("/delete/<slug>", methods=["POST"])
def delete_episode(slug):
    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass

    episodes = [e for e in episodes if e.get("slug") != slug]
    EPISODES_FILE.write_text(json.dumps(episodes, indent=2))

    for path in [AUDIO_DIR / f"{slug}.mp3", PDF_DIR / f"{slug}.pdf"]:
        if path.exists():
            path.unlink()

    return jsonify({"ok": True})


@app.route("/static/pdfs/<path:filename>")
def serve_pdf(filename):
    return send_from_directory(PDF_DIR, filename)


@app.route("/update-meta/<slug>", methods=["POST"])
def update_meta(slug):
    data = request.json or {}
    authors = [a.strip() for a in data.get("authors", "").split(",") if a.strip()]
    topics  = [t.strip() for t in data.get("topics", "").split(",") if t.strip()]

    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass

    found = False
    for ep in episodes:
        if ep.get("slug") == slug:
            ep["authors"] = authors
            ep["topics"]  = topics
            found = True
            break

    if not found:
        return jsonify({"error": "Episode not found"}), 404

    EPISODES_FILE.write_text(json.dumps(episodes, indent=2))
    return jsonify({"ok": True, "authors": authors, "topics": topics})


@app.route("/regenerate-audio/<slug>", methods=["POST"])
def regenerate_audio(slug):
    """Re-voice an existing episode from its stored script. No Claude calls needed."""
    episodes = []
    if EPISODES_FILE.exists():
        try:
            episodes = json.loads(EPISODES_FILE.read_text())
        except Exception:
            pass

    ep = next((e for e in episodes if e.get("slug") == slug), None)
    if not ep:
        return jsonify({"error": "Episode not found"}), 404

    script = ep.get("script", "")
    if not script:
        return jsonify({"error": "No script stored for this episode"}), 400

    # Use model from request body if supplied, otherwise fall back to stored model
    req_data = request.get_json(silent=True) or {}
    tts_model = req_data.get("tts_model") or ep.get("tts_model", "eleven_turbo_v2_5")
    if tts_model not in ("eleven_turbo_v2_5", "eleven_multilingual_v2"):
        tts_model = "eleven_turbo_v2_5"

    audio_filename = f"{slug}.mp3"
    try:
        audio_path = text_to_speech(script, audio_filename, model_id=tts_model)
    except Exception as e:
        return jsonify({"error": f"ElevenLabs error: {str(e)}"}), 500

    file_size = audio_path.stat().st_size
    duration  = get_audio_duration(audio_path)

    r2_url = None
    if R2_ENABLED:
        try:
            r2_url = upload_to_r2(audio_path, f"audio/{audio_filename}")
        except Exception as e:
            app.logger.warning(f"R2 upload failed: {e}")

    audio_url = r2_url if r2_url else f"/static/audio/{audio_filename}"

    # Update the episode in place
    for e in episodes:
        if e.get("slug") == slug:
            e["audio_url"]  = audio_url
            e["r2_url"]     = r2_url
            e["file_size"]  = file_size
            e["duration"]   = duration
            e["tts_model"]  = tts_model
            break

    EPISODES_FILE.write_text(json.dumps(episodes, indent=2))

    if R2_ENABLED and r2_url:
        try:
            publish_feed()
        except Exception as e:
            app.logger.warning(f"Feed publish failed: {e}")

    # Save/update Obsidian note now that we have an audio URL
    try:
        save_to_obsidian(
            ep.get("title", slug),
            slug,
            ep.get("summary", ""),
            ep.get("pdf_name", f"{slug}.pdf"),
            ep.get("word_count", 0),
            topics=ep.get("topics", []),
            audio_url=audio_url,
            authors=ep.get("authors", []),
            arxiv_id=ep.get("arxiv_id", ""),
        )
    except Exception:
        pass

    return jsonify({"ok": True, "audio_url": audio_url, "duration": duration})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
