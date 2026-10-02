"""Transcribe stored audio locally: python transcribe_episode.py <episode-id>. Requires FFmpeg."""
import shutil
import sys
from pathlib import Path
from filelock import FileLock, Timeout
import storage

BASE = Path(__file__).resolve().parent


def main():
    if len(sys.argv) != 2 or not storage.valid_id(sys.argv[1]):
        raise SystemExit('Usage: python transcribe_episode.py <episode-id>')
    slug = sys.argv[1]
    episodes = BASE / 'static/episodes.json'
    with FileLock(str(episodes)+'.operation.lock', timeout=0):
        ep = next((e for e in storage.load(episodes) if e['slug'] == slug), None)
        if ep is None:
            raise SystemExit('Episode not found; no model was downloaded.')
        name = ep.get('local_audio') or slug+'.mp3'
        if Path(name).name != name or '\\' in name:
            raise SystemExit('Invalid stored audio filename.')
        mp3 = BASE/'static/audio'/name
        if not mp3.is_file():
            raise SystemExit('Episode audio does not exist.')
        if not shutil.which('ffmpeg'):
            raise SystemExit('Install FFmpeg and make ffmpeg available on PATH before transcribing.')
        import whisper
        print('Loading Whisper base (downloads model on first use)…')
        script = whisper.load_model('base').transcribe(str(mp3))['text'].strip()
        if not script:
            raise SystemExit('Empty transcription; episode preserved.')
        storage.update(episodes, slug, {'script': script, 'word_count': len(script.split()),
                                      'character_count': len(script)})
        print('Transcription saved. Review it before re-voicing; transcription can contain errors.')


if __name__ == '__main__':
    try:
        main()
    except Timeout:
        raise SystemExit('The app is busy. Wait for the current operation and retry.')
