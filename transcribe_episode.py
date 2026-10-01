"""
Transcribe an existing episode MP3 and patch it into episodes.json.

Usage:
    pip3 install -r requirements-optional.txt
    python3 transcribe_episode.py <slug>

Example:
    python3 transcribe_episode.py attention-is-all-you-need
"""

import sys
import json
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 transcribe_episode.py <slug>")
        sys.exit(1)

    slug = sys.argv[1]
    mp3_path = Path(f"static/audio/{slug}.mp3")
    episodes_path = Path("static/episodes.json")

    if not mp3_path.exists():
        print(f"Error: {mp3_path} not found")
        sys.exit(1)

    print(f"Loading Whisper model (this may take a minute on first run)...")
    import whisper
    model = whisper.load_model("base")

    print(f"Transcribing {mp3_path}...")
    result = model.transcribe(str(mp3_path))
    script = result["text"].strip()

    print(f"\n--- Transcribed script ({len(script.split())} words) ---\n")
    print(script[:500] + "..." if len(script) > 500 else script)
    print("\n---\n")

    # Patch into episodes.json
    episodes = json.loads(episodes_path.read_text())
    patched = False
    for ep in episodes:
        if ep.get("slug") == slug:
            ep["script"] = script
            if ep.get("word_count", 0) == 0:
                ep["word_count"] = len(script.split())
            patched = True
            print(f"Patched '{ep['title']}' in episodes.json")
            break

    if not patched:
        print(f"Warning: slug '{slug}' not found in episodes.json")
        sys.exit(1)

    episodes_path.write_text(json.dumps(episodes, indent=2, ensure_ascii=False))
    print("Done. Refresh the library to see the script.")

if __name__ == "__main__":
    main()
