# Griptape Nodes Library - ElevenLabs

This library provides Griptape nodes for interacting with the [ElevenLabs API](https://elevenlabs.io/), enabling high-quality text-to-speech, voice cloning, voice design, and audio generation capabilities.

## Features

- **Text-to-Speech**: Generate natural-sounding speech from text with multiple voice options
- **Voice Changer**: Transform audio from one voice to another using speech-to-speech technology
- **Voice Cloning**: Clone voices from audio samples using Instant Voice Cloning
- **Voice Design**: Create custom voices from descriptive prompts
- **Sound Effects**: Generate sound effects from text descriptions
- **Music Generation**: Generate music from text prompts
- **Video to Music**: Generate background music for one or more videos
- **Voice Management**: List and manage your ElevenLabs voices
- Support for multiple models (v4, v3, multilingual, flash)
- Voice preview functionality with automatic loading
- Async implementation for efficient processing

## Installation

1. Get your API key from [ElevenLabs API Keys](https://elevenlabs.io/app/settings/api-keys)

2. Add the library to Griptape Nodes:
   - In the Griptape Nodes app, navigate to Manage → Library Management
   - Paste the following url in **Git Url**: `https://github.com/griptape-ai/griptape-nodes-library-elevenlabs`
   - Click **Download**

3. Configure your API key in the secrets manager as `ELEVEN_LABS_API_KEY`

## ⚠️ Important: API Key and Custom Voices

**Your ElevenLabs API key is essential for accessing custom voices.** 

When using custom voices (voices from the ElevenLabs Voice Library or voices you've created), you must:

1. **Add voices to your account**: Custom voices must be added to "My Voices" in your ElevenLabs account at [https://elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library) before they can be used
2. **Use your own API key**: The API key must belong to the account that has access to the custom voices
3. **Verify access**: The voice preview feature will automatically check if a voice is accessible with your API key and provide helpful error messages if access is denied

**Note**: Preset voices (Alexandra, Antoni, Austin, etc.) work with any valid API key, but custom voices require the API key from the account that owns or has access to those voices.

## Nodes

### Text to Speech

Generate high-quality speech from text with support for:
- Multiple voice presets (Alexandra, Antoni, Austin, Clyde, Dave, Domi, Drew, Fin, Hope, James, Jane, Paul, Rachel, Sarah, Thomas)
- Custom voice IDs from your ElevenLabs account
- Multiple models:
  - `eleven_v4`: Flagship, most emotive, 90+ languages (10k char limit, no speed control)
  - `eleven_v4_turbo`: Most expressive real-time model (~100ms, no speed control)
  - `eleven_v3`: Previous generation, expressive and dramatic (5k char limit)
  - `eleven_multilingual_v2`: Stable on long-form content (10k char limit)
  - `eleven_flash_v2_5`: Fast and affordable (~75ms, 40k char limit)
  - `eleven_flash_v2`: Ultra-low latency, English only (~75ms, 30k char limit)
- Saved workflows that use the deprecated `eleven_turbo_v2_5`, `eleven_turbo_v2` or `eleven_monolingual_v1` models are migrated automatically to `eleven_flash_v2_5`, `eleven_flash_v2` and `eleven_multilingual_v2`
- Audio tags (such as `[whispers]` or `[laughs]`) in the text with `eleven_v4` and `eleven_v3`
- Voice settings (stability, and speed on models that support it)
- Context support (previous_text/next_text) for continuity between generations
- Language code hints for pronunciation
- Seed support for reproducible generation
- Automatic voice preview loading on node creation

### Voice Changer

Transform audio from one voice to another using speech-to-speech technology:
- Support for both audio and video inputs (audio extracted from video automatically)
- Models: `eleven_multilingual_sts_v2` (29 languages) and `eleven_english_sts_v2` (English only)
- Maintains emotion, timing, and delivery of original audio
- Voice preset selection or custom voice IDs
- Voice settings (stability, similarity_boost)
- Background noise removal option
- Multiple output formats (MP3, PCM, Opus at various sample rates)
- Seed support for reproducible generation
- Automatic voice preview loading on node creation

### Clone Voice

Clone a voice from audio samples using Instant Voice Cloning:
- Upload audio samples to create a new voice
- Automatic voice preview after cloning
- Returns the cloned voice ID for use in other nodes
- For more information about voice cloning, view the [documentation](https://help.elevenlabs.io/hc/en-us/sections/23821115950481-Voice-Cloning)

### Design Voice

Create custom voices from descriptive prompts:
- Generate preview samples from text descriptions (20-1000 characters)
- Auto-generate preview text or provide custom text
- Multiple preview outputs (up to 3)
- Voice quality and guidance controls
- Optional reference audio for bias
- Returns structured metadata with voice IDs and preview URLs

### Save Voice

Save a designed voice to your ElevenLabs account:
- Select from previously generated voice previews
- Permanently save the voice to your account
- Returns the saved voice ID for future use

### List Voices

List voices available in your ElevenLabs account:
- Paginated results (10 per page)
- Shows voice IDs, names, and preview players
- Useful for discovering available voices for use in other nodes

### Sound Effects

Generate sound effects from text descriptions:
- Text-to-sound effect generation
- Returns playable audio URL
- Useful for adding audio effects to projects

### Generate Music

Generate music from text prompts:
- Text-to-music generation
- Models: `music_v2_5` (default, most advanced), `music_v2` and `music_v1`
- Returns playable audio URL
- Create background music or musical compositions

### Video to Music

Generate background music that fits one or more videos:
- Up to 10 videos (200 MB and 600 seconds combined), joined in the order given
- Optional description and style tags (such as upbeat or cinematic)
- Model selection (`music_v2_5` by default, `music_v2`, `music_v1`)
- Options to add detected sound-effect cues, use the video's own audio as a reference, and sign the output with C2PA
- Optional separate tracks: the music and the sound effects come out as two audio outputs
- Videos can be URLs, local paths or macro paths
- Requires a paid ElevenLabs subscription

## Documentation

For detailed API documentation, visit:
- [ElevenLabs API Documentation](https://elevenlabs.io/docs)
- [ElevenLabs Voice Library](https://elevenlabs.io/app/voice-library)

## License

See [LICENSE](LICENSE) file for details.
