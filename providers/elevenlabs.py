"""Existing ElevenLabs transport and temporary streaming output."""
import os
import tempfile
from pathlib import Path
from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

ENDPOINT = 'https://api.elevenlabs.io'
TTS_LIMITS = {"eleven_flash_v2_5": 40_000, "eleven_turbo_v2_5": 40_000, "eleven_multilingual_v2": 10_000}


def create_client(api_key, base_url=ENDPOINT, follow_redirects=False, timeout=120):
    return ElevenLabs(api_key=api_key, base_url=base_url, follow_redirects=follow_redirects, timeout=timeout)


def select_voice(client, voice_id):
    """Use the configured voice ID, or fall back to the first voice in the account."""
    if voice_id:
        client.voices.get(voice_id)
        return voice_id
    voices = client.voices.get_all()
    if not voices.voices:
        raise RuntimeError("No voices found in your ElevenLabs account.")
    return voices.voices[0].voice_id



class ElevenLabsSpeech:
    input_unit = 'characters'
    input_limits = TTS_LIMITS
    audio_formats = ('mp3_44100_128',)

    def __init__(self, client):
        self.client = client

    def list_voices(self):
        return self.client.voices.get_all().voices

    def synthesize(self, script, voice_id, model_id, directory):
        audio = self.client.text_to_speech.convert(voice_id=voice_id, text=script, model_id=model_id,
            output_format="mp3_44100_128", voice_settings=VoiceSettings(stability=.35,
            similarity_boost=.75, style=.45, use_speaker_boost=True, speed=1.15))
        fd, name = tempfile.mkstemp(suffix='.mp3', prefix='.pending-', dir=directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                for chunk in audio:
                    if chunk:
                        stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            return temporary
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
