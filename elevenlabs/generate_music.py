from __future__ import annotations

import base64
import json as _json
import logging
import time
from typing import Any

import httpx
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_float import ParameterFloat
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options


class ElevenLabsGenerateMusic(DataNode):
    """Generate music from a prompt using ElevenLabs Music API and return a playable URL.

    Inputs:
    - prompt (str): Up to 2000 chars. Cannot be used with composition_plan in this node.
    - music_duration_seconds (float): Optional duration in seconds (10.0-300.0s). If not provided, API chooses length.
    - force_instrumental (bool): If true, ensures the generated song is purely instrumental (no vocals).
    - output_format (str): codec_sample_rate_bitrate. Default mp3_44100_128.
    - model_id (str): Default music_v1.

    Outputs:
    - audio (AudioUrlArtifact): Generated music as a playable URL.
    """

    API_KEY_NAME: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    PROMPT_TRUNCATE_LENGTH = 100
    PROMPT_MAX_LENGTH = 2000
    MIN_MUSIC_LENGTH_SEC = 10.0
    MAX_MUSIC_LENGTH_SEC = 300.0

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
            ParameterBool(
                name="use_specific_length",
                default_value=False,
                tooltip="If true, include music_duration_seconds in the request. If false, API chooses length.",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Specific Length"},
            )
        )
        self.add_parameter(
            ParameterFloat(
                name="music_duration_seconds",
                default_value=30.0,
                tooltip="Duration of the music in seconds (10.0-300.0s). Only used when Use Specific Length is true.",
                allow_input=True,
                allow_property=True,
                allow_output=False,
                slider=True,
                min_val=self.MIN_MUSIC_LENGTH_SEC,
                max_val=self.MAX_MUSIC_LENGTH_SEC,
                ui_options={
                    "display_name": "Duration (seconds)",
                    "hide_when": {"use_specific_length": [False]},
                },
            )
        )
        self.add_parameter(
            ParameterBool(
                name="force_instrumental",
                default_value=False,
                tooltip="If true, ensures the generated song is purely instrumental (no vocals).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Force Instrumental"},
            )
        )
        self.add_parameter(
            Parameter(
                name="output_format",
                input_types=["str"],
                type="str",
                default_value="mp3_44100_128",
                tooltip="Audio output format",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={
                    Options(
                        choices=[
                            "mp3_22050_32",
                            "mp3_24000_48",
                            "mp3_44100_32",
                            "mp3_44100_64",
                            "mp3_44100_96",
                            "mp3_44100_128",
                            "mp3_44100_192",
                            "pcm_8000",
                            "pcm_16000",
                            "pcm_22050",
                            "pcm_24000",
                            "pcm_32000",
                            "pcm_44100",
                            "pcm_48000",
                            "ulaw_8000",
                            "alaw_8000",
                            "opus_48000_32",
                            "opus_48000_64",
                            "opus_48000_96",
                            "opus_48000_128",
                            "opus_48000_192",
                        ]
                    )
                },
                ui_options={"display_name": "Output Format"},
            )
        )
        self.add_parameter(
            Parameter(
                name="model_id",
                input_types=["str"],
                type="str",
                default_value="music_v1",
                tooltip="Model to use (default: music_v1). Currently only 'music_v1' is available. Check GET /v1/models for latest models.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                hide_property=True,
            )
        )

        # Outputs
        self.add_parameter(
            Parameter(
                name="audio",
                output_type="AudioUrlArtifact",
                type="AudioUrlArtifact",
                tooltip="Generated music (playable).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Music", "expander": True, "pulse_on_run": True},
            )
        )

    def process(self) -> Any:
        yield lambda: self._run()

    def _run(self) -> None:
        prompt: str | None = self.get_parameter_value("prompt")
        use_length: bool = bool(self.get_parameter_value("use_specific_length"))
        duration_seconds: float | None = self.get_parameter_value("music_duration_seconds")
        force_instrumental: bool = bool(self.get_parameter_value("force_instrumental"))
        output_format: str = self.get_parameter_value("output_format") or "mp3_44100_128"
        model_id: str = self.get_parameter_value("model_id") or "music_v1"

        if prompt and len(prompt) > self.PROMPT_MAX_LENGTH:
            prompt = prompt[: self.PROMPT_MAX_LENGTH]

        # Get API key using SecretsManager (same as working voice_changer node)
        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            error_msg = f"{self.name} is missing {self.API_KEY_NAME}. Ensure it's set in the environment/config."
            raise RuntimeError(error_msg)

        # Convert seconds to milliseconds (only if use_specific_length is true)
        music_length_ms: int | None = None
        if use_length and duration_seconds is not None:
            music_length_ms = int(duration_seconds * 1000)

        # Build request JSON
        payload: dict[str, Any] = {
            "model_id": model_id,
        }
        if prompt:
            payload["prompt"] = prompt
        if music_length_ms is not None:
            payload["music_length_ms"] = music_length_ms
        if force_instrumental:
            payload["force_instrumental"] = True
        # Note: composition_plan not supported in this node; could be a future extension

        # HTTP request using httpx (same as working voice_changer node)
        base_url = "https://api.elevenlabs.io"
        url = f"{base_url}/v1/music?output_format={output_format}"
        headers = {
            "xi-api-key": api_key,
        }

        # Log request with truncated prompt for readability
        prompt_for_log = prompt
        if prompt and len(prompt) > self.PROMPT_TRUNCATE_LENGTH:
            prompt_for_log = prompt[: self.PROMPT_TRUNCATE_LENGTH] + "..."
        self._logger.info(
            "GenerateMusic request: prompt=%s, prompt_len=%s, use_length=%s, duration_seconds=%s, music_length_ms=%s, force_instrumental=%s, output_format=%s, model_id=%s",
            prompt_for_log if prompt else None,
            len(prompt) if prompt else None,
            use_length,
            duration_seconds,
            music_length_ms,
            force_instrumental,
            output_format,
            model_id,
        )

        resp_bytes: bytes | None = None
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                resp_bytes = response.content
        except httpx.HTTPStatusError as e:
            self._logger.info("GenerateMusic HTTP error: %s - %s", e.response.status_code, e.response.text)
            error_message = self._parse_error_response(e.response.text, e.response.status_code)
            raise RuntimeError(error_message) from e
        except Exception as e_http:
            self._logger.info("GenerateMusic HTTP failed: %s", e_http)
            error_msg = f"Request failed: {e_http}"
            raise RuntimeError(error_msg) from e_http

        # Save to static
        audio_artifact = None
        if resp_bytes:
            try:
                # Guess extension from output_format
                ext = "mp3"
                if isinstance(output_format, str):
                    if output_format.startswith("pcm"):
                        ext = "wav"
                    elif output_format.startswith("mp3"):
                        ext = "mp3"
                filename = f"elevenlabs_music_{int(time.time())}.{ext}"
                static_url = GriptapeNodes.StaticFilesManager().save_static_file(resp_bytes, filename)
                audio_artifact = AudioUrlArtifact(value=static_url, name=filename)
            except Exception as e_save:
                try:
                    b64 = base64.b64encode(resp_bytes).decode("ascii")
                    mime = "audio/wav" if output_format.startswith("pcm") else "audio/mpeg"
                    data_url = f"data:{mime};base64,{b64}"
                    audio_artifact = AudioUrlArtifact(value=data_url, name="music")
                    self._logger.info("GenerateMusic static save failed; used data URL: %s", e_save)
                except Exception:
                    audio_artifact = None

        self.parameter_output_values["audio"] = audio_artifact

    def _parse_error_response(self, response_text: str, status_code: int) -> str:
        """Parse error response and extract meaningful error information for the user."""
        try:
            error_data = _json.loads(response_text)

            if "detail" in error_data:
                detail = error_data["detail"]
                if isinstance(detail, dict):
                    status = detail.get("status", "")
                    message = detail.get("message", "")

                    if status and message:
                        # Handle specific error cases with helpful messages
                        if status == "limited_access" and "music-terms" in message.lower():
                            return (
                                f"{status}: {message}\n\n"
                                "To use Eleven Music, you need to accept the additional terms at "
                                "https://elevenlabs.io/music-terms. Please visit the link to accept "
                                "the terms, then try again."
                            )
                        return f"{status}: {message}"
                    if message:
                        return f"Error: {message}"
                elif isinstance(detail, str):
                    # Sometimes detail is a string
                    if "music-terms" in detail.lower() or "limited_access" in detail.lower():
                        return (
                            f"Error: {detail}\n\n"
                            "To use Eleven Music, you need to accept the additional terms at "
                            "https://elevenlabs.io/music-terms. Please visit the link to accept "
                            "the terms, then try again."
                        )
                    return f"Error: {detail}"

            if "error" in error_data:
                error_msg = error_data["error"]
                if isinstance(error_msg, str) and (
                    "music-terms" in error_msg.lower() or "limited_access" in error_msg.lower()
                ):
                    return (
                        f"Error: {error_msg}\n\n"
                        "To use Eleven Music, you need to accept the additional terms at "
                        "https://elevenlabs.io/music-terms. Please visit the link to accept "
                        "the terms, then try again."
                    )
                return f"Error: {error_msg}"

            # Check if the raw response text contains music terms reference
            if "music-terms" in response_text.lower() or "limited_access" in response_text.lower():
                return (
                    f"API Error ({status_code}): {response_text[:200]}\n\n"
                    "To use Eleven Music, you need to accept the additional terms at "
                    "https://elevenlabs.io/music-terms. Please visit the link to accept "
                    "the terms, then try again."
                )

            return f"API Error ({status_code}): {response_text[:200]}"

        except (_json.JSONDecodeError, KeyError, TypeError):
            # Even if parsing fails, check for music terms in raw text
            if "music-terms" in response_text.lower() or "limited_access" in response_text.lower():
                return (
                    f"API Error ({status_code}): {response_text[:200]}\n\n"
                    "To use Eleven Music, you need to accept the additional terms at "
                    "https://elevenlabs.io/music-terms. Please visit the link to accept "
                    "the terms, then try again."
                )
            return f"API Error ({status_code}): Unable to parse error response"
