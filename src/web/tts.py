"""
TTS abstraction for generating audio clips.

Supported providers (set via TTS_PROVIDER env var):
  elevenlabs — ElevenLabs (default)

Env vars:
  TTS_PROVIDER      elevenlabs              (default: elevenlabs)
  ELEVENLABS_API_KEY
  TTS_MODEL         model ID                (default: eleven_multilingual_v2)

Output is always mono MP3 at 22 050 Hz / 32 kbps.
"""

import os


def generate_audio(text: str, *, voice_id=None, speed=None, stability=None,
                   similarity=None, style=None, speaker_boost=None) -> bytes:
    """Generate TTS audio for text. Returns raw MP3 bytes."""
    provider = os.environ.get('TTS_PROVIDER', 'elevenlabs').lower()
    if provider == 'elevenlabs':
        return _elevenlabs(text, voice_id=voice_id, speed=speed,
                           stability=stability, similarity=similarity,
                           style=style, speaker_boost=speaker_boost)
    raise RuntimeError(f'Unknown TTS provider: {provider}')


def _elevenlabs(text: str, *, voice_id, speed, stability, similarity, style, speaker_boost) -> bytes:
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    api_key = os.environ.get('ELEVENLABS_API_KEY', '')

    speed         = speed         if speed         is not None else 1.0
    stability     = stability     if stability     is not None else 0.48
    similarity    = similarity    if similarity    is not None else 0.75
    style         = style         if style         is not None else 0.08
    speaker_boost = speaker_boost if speaker_boost is not None else True

    if not voice_id:
        raise RuntimeError('No TTS voice configured for this deck')

    model = os.environ.get('TTS_MODEL', 'eleven_multilingual_v2')

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
