"""
TTS abstraction for generating audio clips.

Supported providers (set via TTS_PROVIDER env var):
  elevenlabs — ElevenLabs (default)

Relevant env vars:
  TTS_PROVIDER      elevenlabs              (default: elevenlabs)
  ELEVENLABS_API_KEY
  TTS_VOICE_ID      ElevenLabs voice ID     (find at elevenlabs.io/voice-library)
  TTS_MODEL         model ID                (default: eleven_multilingual_v2)
  TTS_SPEED         speaking rate           (default: 1.0)
  TTS_STABILITY     stability 0–1           (default: 0.48)
  TTS_SIMILARITY    similarity boost 0–1    (default: 0.75)
  TTS_STYLE         style exaggeration 0–1  (default: 0.08)
  TTS_SPEAKER_BOOST true | false            (default: true)

Output is always mono MP3 at 22 050 Hz / 32 kbps.
"""

import os


def generate_audio(text: str) -> bytes:
    """Generate TTS audio for text. Returns raw MP3 bytes."""
    provider = os.environ.get('TTS_PROVIDER', 'elevenlabs').lower()
    if provider == 'elevenlabs':
        return _elevenlabs(text)
    raise RuntimeError(f'Unknown TTS provider: {provider}')


def _elevenlabs(text: str) -> bytes:
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    api_key  = os.environ.get('ELEVENLABS_API_KEY', '')
    voice_id = os.environ.get('TTS_VOICE_ID')
    if not voice_id:
        raise RuntimeError('TTS_VOICE_ID is not set')

    model         = os.environ.get('TTS_MODEL', 'eleven_multilingual_v2')
    speed         = float(os.environ.get('TTS_SPEED',      '1.0'))
    stability     = float(os.environ.get('TTS_STABILITY',  '0.48'))
    similarity    = float(os.environ.get('TTS_SIMILARITY', '0.75'))
    style         = float(os.environ.get('TTS_STYLE',      '0.08'))
    speaker_boost = os.environ.get('TTS_SPEAKER_BOOST', 'true').lower() != 'false'

    client = ElevenLabs(api_key=api_key)
    chunks = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model,
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=similarity,
            style=style,
            speed=speed,
            use_speaker_boost=speaker_boost,
        ),
        output_format='mp3_22050_32',
    )
    return b''.join(chunks)
