# Griptape Nodes Library - ElevenLabs

This library provides Griptape nodes for interacting with the [ElevenLabs API](https://elevenlabs.io/), enabling high-quality text-to-speech, voice cloning, voice design, and audio generation capabilities.

## Features

- **Text-to-Speech**: Generate natural-sounding speech from text with multiple voice options
- **Voice Changer**: Transform audio from one voice to another using speech-to-speech technology
- **Voice Cloning**: Clone voices from audio samples using Instant Voice Cloning
- **Voice Design**: Create custom voices from descriptive prompts
- **Sound Effects**: Generate sound effects from text descriptions
- **Music Generation**: Generate music from text prompts
- **Voice Management**: List and manage your ElevenLabs voices
- Support for multiple models (multilingual, turbo, flash, v3)
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
  - `eleven_multilingual_v2`: Best for long-form content (10k char limit)
  - `eleven_turbo_v2_5`: Fast and high quality (~250-300ms)
  - `eleven_flash_v2_5`: Ultra-fast (~75ms)
  - `eleven_v3`: Most expressive (alpha, 3k char limit)
- Voice settings (stability, speed)
- Context support (previous_text/next_text) for continuity between generations
- Language code hints for pronunciation
- Seed support for reproducible generation
- Automatic voice preview loading on node creation

### Voice Changer

Transform audio from one voice to another using speech-to-speech technology:
- Support for both audio and video inputs (audio extracted from video automatically)
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
- Returns playable audio URL
- Create background music or musical compositions

## Documentation

For detailed API documentation, visit:
- [ElevenLabs API Documentation](https://elevenlabs.io/docs)
- [ElevenLabs Voice Library](https://elevenlabs.io/app/voice-library)

## License

See [LICENSE](LICENSE) file for details.
