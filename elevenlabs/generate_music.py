from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode


class ElevenLabsGenerateMusic(DataNode):
    """Generate music from a prompt using ElevenLabs Music API and return a playable URL.

    Inputs:
    - prompt (str): Up to 2000 chars. Cannot be used with composition_plan in this node.
    - use_specific_length (bool): If true, include music_length_ms in the request.
    - music_length_ms (int): 10_000..300_000. Only used when use_specific_length is true.
    - output_format (str): codec_sample_rate_bitrate. Default mp3_44100_128.
    - model_id (str): Default music_v1.

    Outputs:
    - audio (AudioUrlArtifact): Generated music as a playable URL.
    - metadata (json): Request/response info, file details, and API payload.
    """

    API_KEY_ENV_VAR: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Generate music from a prompt and return a playable URL."

        # Inputs / Properties
        self.add_parameter(
            Parameter(
                name="prompt",
                input_types=["str"],
                type="str",
                tooltip="Describe the music to generate (<=2000 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "e.g., 90s hip-hop drum loop, 90 BPM"},
            )
        )
        self.add_parameter(
            Parameter(
                name="use_specific_length",
                input_types=["bool"],
                type="bool",
                default_value=False,
                tooltip="If true, sends music_length_ms (10s..300s).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Specific Length"},
            )
        )
        self.add_parameter(
            Parameter(
                name="music_length_ms",
                input_types=["int", "none"],
                type="int",
                default_value=None,
                tooltip="Length in ms (10000..300000). Only when Use Specific Length is true.",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.INPUT},
                ui_options={
                    "display_name": "Length (ms)",
                    "hide_when": {"use_specific_length": [False]},
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="output_format",
                input_types=["str"],
                type="str",
                default_value="mp3_44100_128",
                tooltip="Output format (codec_sample_rate_bitrate).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={
                    "className": "gt-select",
                    "data": {
                        "choices": [
                            ["MP3 44.1kHz 128kbps", "mp3_44100_128"],
                            ["MP3 44.1kHz 192kbps (Creator)", "mp3_44100_192"],
                            ["MP3 22.05kHz 32kbps", "mp3_22050_32"],
                            ["PCM 44.1kHz 16bit (Pro)", "pcm_44100_16"],
                        ]
                    },
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="model_id",
                input_types=["str"],
                type="str",
                default_value="music_v1",
                tooltip="Model to use (default: music_v1).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"className": "gt-select", "data": {"choices": [["music_v1", "music_v1"]]}},
            )
        )

        # Outputs
        self.add_parameter(
            Parameter(
                name="audio",
                output_type="AudioUrlArtifact",
                type="AudioArtifact",
                tooltip="Generated music (playable).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Music", "expander": True, "pulse_on_run": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="metadata",
                output_type="json",
                type="dict",
                tooltip="Request/response metadata (JSON).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Metadata", "hide_property": True},
            )
        )

    def process(self) -> Any:
        # Resolve API key before scheduling
        try:
            self._resolved_api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]
        except Exception:
            self._resolved_api_key = None  # type: ignore[attr-defined]
        if not getattr(self, "_resolved_api_key", None):  # type: ignore[attr-defined]
            self._resolved_api_key = os.environ.get(self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]

        yield lambda: self._run()

    def _run(self) -> None:
        prompt: Optional[str] = self.get_parameter_value("prompt")
        use_length: bool = bool(self.get_parameter_value("use_specific_length"))
        length_val: Optional[int] = self.get_parameter_value("music_length_ms")
        try:
            music_length_ms: Optional[int] = int(length_val) if (use_length and length_val is not None) else None
        except Exception:
            music_length_ms = None
        output_format: str = self.get_parameter_value("output_format") or "mp3_44100_128"
        model_id: str = self.get_parameter_value("model_id") or "music_v1"

        if prompt and len(prompt) > 2000:
            prompt = prompt[:2000]

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

        # Build request JSON
        payload: Dict[str, Any] = {
            "model_id": model_id,
        }
        if prompt:
            payload["prompt"] = prompt
            if use_length and music_length_ms is not None:
                # Clamp to [10000, 300000]
                if music_length_ms < 10000:
                    music_length_ms = 10000
                if music_length_ms > 300000:
                    music_length_ms = 300000
                payload["music_length_ms"] = music_length_ms
        # Note: composition_plan not supported in this node; could be a future extension

        # HTTP request
        base_url = "https://api.elevenlabs.io"
        url = f"{base_url}/v1/music?output_format={output_format}"
        headers = {
            "xi-api-key": str(api_key),
            "accept": "application/json",
            "content-type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8")

        self._logger.info(
            "GenerateMusic request: prompt_len=%s, use_length=%s, music_length_ms=%s, output_format=%s, model_id=%s",
            len(prompt) if prompt else None,
            use_length,
            music_length_ms,
            output_format,
            model_id,
        )

        req = Request(url=url, data=body, headers=headers, method="POST")
        resp_bytes: Optional[bytes] = None
        resp_status: Optional[int] = None
        resp_ct: Optional[str] = None
        try:
            with urlopen(req, timeout=60) as resp:
                resp_status = getattr(resp, "status", None) or getattr(resp, "code", None)
                resp_ct = resp.headers.get("content-type") if hasattr(resp, "headers") else None
                resp_bytes = resp.read()
        except Exception as e_http:
            self._logger.info("GenerateMusic HTTP failed: %s", e_http)
            raise

        metadata: Dict[str, Any] = {
            "request": {
                "prompt_len": len(prompt) if prompt else None,
                "use_specific_length": use_length,
                "music_length_ms": music_length_ms,
                "output_format": output_format,
                "model_id": model_id,
            },
            "response": {"status": resp_status, "content_type": resp_ct, "byte_length": len(resp_bytes) if resp_bytes else None},
        }

        # Save to static
        audio_artifact = None
        if resp_bytes:
            try:
                from griptape.artifacts import AudioUrlArtifact  # type: ignore
                from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes  # type: ignore

                # Guess extension from output_format
                ext = "mp3"
                if isinstance(output_format, str):
                    if output_format.startswith("pcm"):
                        ext = "wav"
                    elif output_format.startswith("mp3"):
                        ext = "mp3"
                filename = f"elevenlabs_music_{int(time.time())}.{ext}"
                static_url = GriptapeNodes.StaticFilesManager().save_static_file(resp_bytes, filename)
                audio_artifact = AudioUrlArtifact(value=static_url, name=filename)  # type: ignore
                metadata["file"] = {"url": static_url, "filename": filename, "ext": ext, "saved_to_static": True}
            except Exception as e_save:
                try:
                    from griptape.artifacts import AudioUrlArtifact  # type: ignore
                    b64 = base64.b64encode(resp_bytes).decode("ascii")
                    mime = "audio/wav" if output_format.startswith("pcm") else "audio/mpeg"
                    data_url = f"data:{mime};base64,{b64}"
                    audio_artifact = AudioUrlArtifact(value=data_url, name="music")  # type: ignore
                    metadata["file"] = {"url": data_url, "filename": "music", "ext": None, "saved_to_static": False}
                    self._logger.info("GenerateMusic static save failed; used data URL: %s", e_save)
                except Exception:
                    audio_artifact = None

        self.parameter_output_values["audio"] = audio_artifact
        self.parameter_output_values["metadata"] = metadata
