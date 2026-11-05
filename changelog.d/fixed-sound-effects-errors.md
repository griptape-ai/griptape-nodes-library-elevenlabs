- **Breaking:** Sound Effects raises when ElevenLabs rejects the request. It used to log the error
  and finish with an empty `Sound Effect` output. A saved workflow that relied on that now stops
  at this node with ElevenLabs' message.
  [#12](https://github.com/griptape-ai/griptape-nodes-library-elevenlabs/issues/12)
