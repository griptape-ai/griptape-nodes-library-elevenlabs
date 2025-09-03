from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, Optional, Iterable

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode


class ElevenLabsSoundEffects(DataNode):
    """Generate a sound effect from text using ElevenLabs and output a playable URL.

    Inputs:
    - text (str): Prompt describing the desired sound effect (e.g., "Cinematic Braam, Horror").
    - use_specific_duration (bool): If true, include duration_seconds in the API request (costs credits).
    - duration_seconds (float, optional): 0.1–30. Only used when use_specific_duration is true.
    - looping (bool, optional): Enable seamless looping if supported.

    Outputs:
    - audio (AudioUrlArtifact): The generated sound effect as a URL artifact. Saved to static files if possible.
    - metadata (json): Raw response metadata (optional convenience for debugging/inspection).
    """

    API_KEY_ENV_VAR: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Generate a sound effect from text and return a playable URL."

        # Inputs / Properties
        self.add_parameter(
            Parameter(
                name="text",
                input_types=["str"],
                type="str",
                tooltip="Describe the sound effect to generate.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "e.g., Cinematic Braam, Horror",
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="use_specific_duration",
                input_types=["bool"],
                type="bool",
                default_value=False,
                tooltip="If true, sends duration_seconds to API (costs 40 credits/sec).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Specific Duration"},
            )
        )
        self.add_parameter(
            Parameter(
                name="duration_seconds",
                input_types=["float", "int", "none"],
                type="float",
                default_value=None,
                tooltip="Optional: 0.1–30 sec. Only used when Use Specific Duration is true.",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.INPUT},
                ui_options={
                    "display_name": "Duration (seconds)",
                    "slider": {"min_val": 0.1, "max_val": 30.0, "step": 0.1},
                    "hide_when": {"use_specific_duration": [False]},
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="looping",
                input_types=["bool"],
                type="bool",
                default_value=False,
                tooltip="Enable seamless looping for ambient/atmospheric sounds.",
                allowed_modes={ParameterMode.PROPERTY},
            )
        )

        # Outputs
        self.add_parameter(
            Parameter(
                name="audio",
                output_type="AudioUrlArtifact",
                type="AudioArtifact",
                tooltip="Generated sound effect (playable).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Sound Effect", "expander": True, "pulse_on_run": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="metadata",
                output_type="json",
                type="dict",
                tooltip="Raw response metadata (JSON).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Metadata", "hide_property": True},
            )
        )

    def process(self) -> Any:
        # Resolve API key before scheduling work
        try:
            self._resolved_api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]
        except Exception:
            self._resolved_api_key = None  # type: ignore[attr-defined]
        if not getattr(self, "_resolved_api_key", None):  # type: ignore[attr-defined]
            self._resolved_api_key = os.environ.get(self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]

        yield lambda: self._run()

    def _sniff_audio_extension(self, data: bytes) -> str:
        try:
            if len(data) >= 4 and data[:4] == b"RIFF" and b"WAVE" in data[:32]:
                return "wav"
            if len(data) >= 3 and data[:3] == b"ID3":
                return "mp3"
            if len(data) >= 2 and data[:2] == b"\xff\xfb":
                return "mp3"
            if len(data) >= 4 and data[:4] == b"OggS":
                return "ogg"
        except Exception:
            pass
        return "mp3"

    def _join_iterable_bytes(self, it: Iterable[Any]) -> Optional[bytes]:
        chunks = []
        total = 0
        try:
            for idx, part in enumerate(it):
                if isinstance(part, (bytes, bytearray)):
                    chunks.append(bytes(part))
                    total += len(part)
                    if idx % 10 == 0:
                        try:
                            self._logger.info("SoundEffects streaming: received %s bytes so far", total)
                        except Exception:
                            pass
                else:
                    # Non-byte chunk; ignore
                    continue
            return b"".join(chunks) if chunks else None
        except Exception as e:
            try:
                self._logger.info("SoundEffects iterable join failed: %s", e)
            except Exception:
                pass
            return None

    def _run(self) -> None:
        text: Optional[str] = self.get_parameter_value("text")
        if not text or not isinstance(text, str) or len(text.strip()) == 0:
            raise ValueError("text is required to generate a sound effect.")

        # Optional params
        use_duration: bool = bool(self.get_parameter_value("use_specific_duration"))
        duration_val: Optional[float] = self.get_parameter_value("duration_seconds")
        try:
            duration: Optional[float] = float(duration_val) if (use_duration and duration_val is not None) else None
        except Exception:
            duration = None
        looping: bool = bool(self.get_parameter_value("looping"))

        # Resolve API key
        api_key: Optional[str] = getattr(self, "_resolved_api_key", None)
        if not api_key:
            try:
                api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)
            except Exception:
                api_key = None
        if not api_key:
            api_key = os.environ.get(self.API_KEY_ENV_VAR)
        if not api_key:
            raise RuntimeError("Missing ELEVEN_LABS_API_KEY. Set it in system config or environment.")

        try:
            from elevenlabs import ElevenLabs  # type: ignore
        except Exception as e:
            raise ImportError("elevenlabs package not installed. Add 'elevenlabs' to library dependencies.") from e

        client = ElevenLabs(api_key=api_key)

        # Call the Text-to-Sound-Effects API
        self._logger.info(
            "SoundEffects request: text_len=%s, use_duration=%s, duration=%s, looping=%s",
            len(text), use_duration, duration, looping,
        )
        if not use_duration:
            self._logger.info("SoundEffects will NOT include duration (lower credit cost).")

        # Build kwargs dynamically to avoid passing None
        kwargs: Dict[str, Any] = {"text": text}
        if use_duration and duration is not None:
            # Clamp to API range for safety
            if duration < 0.1:
                duration = 0.1
            if duration > 30.0:
                duration = 30.0
            kwargs["duration_seconds"] = duration
        if looping:
            # First-attempt param name
            kwargs["loop"] = True

        # Try with best-known signature, then fallbacks
        try:
            response = client.text_to_sound_effects.convert(**kwargs)
        except TypeError as e1:
            self._logger.info("SoundEffects convert signature mismatch (v1): %s; trying fallbacks…", e1)
            # Try alternate names
            alt_kwargs = {"text": text}
            if use_duration and duration is not None:
                alt_kwargs["duration"] = duration
            if looping:
                alt_kwargs["looping"] = True
            try:
                response = client.text_to_sound_effects.convert(**alt_kwargs)
            except TypeError as e2:
                self._logger.info("SoundEffects convert signature mismatch (v2): %s; trying minimal…", e2)
                response = client.text_to_sound_effects.convert(text=text)
        except Exception as e_call:
            self._logger.info("SoundEffects API call failed: %s", e_call)
            raise

        # Response is often audio bytes; add robust normalization and logging.
        # Seed metadata with request info so UI always sees something useful
        metadata: Dict[str, Any] = {
            "request": {
                "text_len": len(text),
                "use_specific_duration": use_duration,
                "duration_seconds": duration,
                "looping": looping,
            }
        }
        audio_bytes: Optional[bytes] = None
        file_url: Optional[str] = None
        file_name: Optional[str] = None
        file_ext: Optional[str] = None

        try:
            self._logger.info("SoundEffects response type: %s", type(response).__name__)
        except Exception:
            pass

        if isinstance(response, (bytes, bytearray)):
            audio_bytes = bytes(response)
            try:
                self._logger.info("SoundEffects received bytes: %s", len(audio_bytes))
            except Exception:
                pass
            metadata["response"] = {"type": type(response).__name__, "byte_length": len(audio_bytes)}
        elif isinstance(response, dict):
            try:
                keys = list(response.keys())[:10]
                self._logger.info("SoundEffects dict keys: %s", keys)
            except Exception:
                pass
            # Preserve API-provided fields under 'api'
            metadata["api"] = response
            audio_b64 = response.get("audio_base_64") or response.get("audio_base64")
            if isinstance(audio_b64, str):
                try:
                    audio_bytes = base64.b64decode(audio_b64)
                    self._logger.info("SoundEffects decoded base64 bytes: %s", len(audio_bytes))
                    metadata["response"] = {"type": "base64", "byte_length": len(audio_bytes)}
                except Exception as e_b64:
                    self._logger.info("SoundEffects base64 decode failed: %s", e_b64)
                    audio_bytes = None
        elif hasattr(response, "__iter__") and not isinstance(response, (str, bytes, bytearray)):
            self._logger.info("SoundEffects response is iterable; joining chunks…")
            audio_bytes = self._join_iterable_bytes(response)  # type: ignore[arg-type]
            try:
                self._logger.info("SoundEffects joined bytes: %s", len(audio_bytes) if audio_bytes else None)
            except Exception:
                pass
            metadata["response"] = {"type": "iterable", "byte_length": len(audio_bytes) if audio_bytes else None}
            # Try to extract metadata if possible
            if hasattr(response, "model_dump"):
                try:
                    metadata["api"] = response.model_dump()  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(response, "to_dict"):
                try:
                    metadata["api"] = response.to_dict()  # type: ignore[attr-defined]
                except Exception:
                    pass
        else:
            # Best-effort: inspect attributes
            try:
                audio_attr = getattr(response, "audio", None)
                if isinstance(audio_attr, (bytes, bytearray)):
                    audio_bytes = bytes(audio_attr)
                    self._logger.info("SoundEffects response.audio bytes: %s", len(audio_bytes))
                elif isinstance(audio_attr, str):
                    try:
                        audio_bytes = base64.b64decode(audio_attr)
                        self._logger.info("SoundEffects response.audio base64 decoded: %s", len(audio_bytes))
                    except Exception as e_a:
                        self._logger.info("SoundEffects audio str decode failed: %s", e_a)
                        audio_bytes = None
                # Try model_dump/to_dict for metadata
                if hasattr(response, "model_dump"):
                    metadata["api"] = response.model_dump()  # type: ignore[attr-defined]
                elif hasattr(response, "to_dict"):
                    metadata["api"] = response.to_dict()  # type: ignore[attr-defined]
                if audio_bytes is not None:
                    metadata["response"] = {"type": "attr", "byte_length": len(audio_bytes)}
            except Exception as e_norm:
                self._logger.info("SoundEffects normalization failed: %s", e_norm)

        # Save to static files when we have bytes; fallback to data URL otherwise
        audio_artifact = None
        try:
            from griptape.artifacts import AudioUrlArtifact  # type: ignore
        except Exception:
            AudioUrlArtifact = None  # type: ignore

        if audio_bytes and AudioUrlArtifact is not None:
            try:
                from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes  # type: ignore

                file_ext = self._sniff_audio_extension(audio_bytes)
                file_name = f"elevenlabs_sfx_{int(time.time())}.{file_ext}"
                self._logger.info(
                    "Saving sound effect to static storage: %s (bytes=%s)", file_name, len(audio_bytes)
                )
                static_files_manager = GriptapeNodes.StaticFilesManager()
                file_url = static_files_manager.save_static_file(audio_bytes, file_name)
                audio_artifact = AudioUrlArtifact(value=file_url, name=file_name)  # type: ignore
                try:
                    self.publish_update_to_parameter("audio", audio_artifact)
                    self._logger.info("SoundEffects published audio artifact: %s", file_url)
                except Exception as e_pub:
                    self._logger.info("SoundEffects publish update failed: %s", e_pub)
                metadata["file"] = {
                    "url": file_url,
                    "filename": file_name,
                    "ext": file_ext,
                    "saved_to_static": True,
                }
            except Exception as e_save:
                # Fallback to data URL if save fails
                try:
                    b64 = base64.b64encode(audio_bytes).decode("ascii")
                    data_url = f"data:audio/mpeg;base64,{b64}"
                    audio_artifact = AudioUrlArtifact(value=data_url, name="sound_effect.mp3")  # type: ignore
                    self._logger.info("Static save failed; using data URL. %s", e_save)
                    try:
                        self.publish_update_to_parameter("audio", audio_artifact)
                    except Exception:
                        pass
                    metadata["file"] = {
                        "url": data_url,
                        "filename": "sound_effect.mp3",
                        "ext": "mp3",
                        "saved_to_static": False,
                    }
                except Exception as e_data:
                    self._logger.info("SoundEffects data URL fallback failed: %s", e_data)
                    audio_artifact = None
        elif AudioUrlArtifact is not None and isinstance(metadata.get("api"), dict):
            # Try to build from API metadata if it contains a URL or base64
            api_meta = metadata.get("api", {})
            audio_url = api_meta.get("url") or api_meta.get("audio_url")
            if isinstance(audio_url, str):
                audio_artifact = AudioUrlArtifact(value=audio_url, name="sound_effect")  # type: ignore
                try:
                    self.publish_update_to_parameter("audio", audio_artifact)
                    self._logger.info("SoundEffects using URL from metadata: %s", audio_url)
                except Exception:
                    pass
                metadata["file"] = {
                    "url": audio_url,
                    "filename": "sound_effect",
                    "ext": None,
                    "saved_to_static": False,
                }
            else:
                audio_b64 = api_meta.get("audio_base_64") or api_meta.get("audio_base64")
                if isinstance(audio_b64, str):
                    try:
                        if not audio_b64.startswith("data:"):
                            audio_b64 = f"data:audio/mpeg;base64,{audio_b64}"
                        audio_artifact = AudioUrlArtifact(value=audio_b64, name="sound_effect.mp3")  # type: ignore
                        try:
                            self.publish_update_to_parameter("audio", audio_artifact)
                        except Exception:
                            pass
                        self._logger.info("SoundEffects built data URL from metadata base64")
                        metadata["file"] = {
                            "url": audio_b64,
                            "filename": "sound_effect.mp3",
                            "ext": "mp3",
                            "saved_to_static": False,
                        }
                    except Exception as e_meta:
                        self._logger.info("SoundEffects metadata base64 handling failed: %s", e_meta)
                        audio_artifact = None
        else:
            self._logger.info("SoundEffects: no audio bytes/artifact produced.")

        self.parameter_output_values["audio"] = audio_artifact
        self.parameter_output_values["metadata"] = metadata
        try:
            self._logger.info("SoundEffects outputs set. has_audio=%s", bool(audio_artifact))
        except Exception:
            pass
