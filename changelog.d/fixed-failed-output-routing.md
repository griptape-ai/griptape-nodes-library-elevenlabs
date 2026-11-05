- **Breaking:** Text to Speech and Voice Changer follow `Failed` when ElevenLabs sends no audio
  back, and Voice Changer does the same for an audio or video input with no readable location.
  These used to set the status and return, so with `Failed` unwired the node looked finished.
  With `Failed` unwired they now stop the run with an error. Wire `Failed` to keep going.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)
