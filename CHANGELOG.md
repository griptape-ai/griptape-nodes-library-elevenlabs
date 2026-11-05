# Changelog

All notable changes to the Griptape Nodes ElevenLabs Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `elevenlabs/griptape-nodes-library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.3.0] - 2026-11-06

### Changed

- The library requires Griptape Nodes 0.105.0 or later (it listed 0.41.0).
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)
- A missing `ELEVEN_LABS_API_KEY` is reported first and on its own, before any input problem,
  with links to the key in Settings and to the ElevenLabs API key page. Generate Music, Video to
  Music, Clone Voice, List Voices, Save Voice, Sound Effects and Design Voice report it when the
  node starts instead of partway through the run.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)
- When an ElevenLabs request fails, every node shows ElevenLabs' own explanation on the node, with
  the status code, request ID and response under More info. The "Request failed: ..." and
  "Failed to create voice clone: ..." wrappers are gone. A key ElevenLabs refuses (HTTP 401) links
  to the key in Settings. An Eleven Music terms error links to https://elevenlabs.io/music-terms.
  Video to Music shows ElevenLabs' message for an HTTP 403 instead of its own fixed text. In Video
  to Music, Clone Voice, Text to Speech and Voice Changer, input problems drop the node-name
  prefix and name the parameter as the editor labels it.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)

### Fixed

- **Breaking:** Text to Speech and Voice Changer follow `Failed` when ElevenLabs sends no audio
  back, and Voice Changer does the same for an audio or video input with no readable location.
  These used to set the status and return, so with `Failed` unwired the node looked finished.
  With `Failed` unwired they now stop the run with an error. Wire `Failed` to keep going.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)
- **Breaking:** Sound Effects raises when ElevenLabs rejects the request. It used to log the error
  and finish with an empty `Sound Effect` output. A saved workflow that relied on that now stops
  at this node with ElevenLabs' message.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/compare/8a56d926e3c35bdd99b0d9b53523fc49982a5a09...v0.3.0
