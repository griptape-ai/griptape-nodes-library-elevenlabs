from __future__ import annotations

import json as _json
import logging
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact

from griptape_nodes.exe_types.core_types import Parameter, ParameterGroup, ParameterMessage, ParameterMode
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.exe_types.param_types.parameter_float import ParameterFloat
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.button import Button
from griptape_nodes.traits.options import Options

logger = logging.getLogger(__name__)


PROMPT_TRUNCATE_LENGTH = 100

# Voice preset mapping - friendly names to Eleven Labs voice IDs (sorted alphabetically)
VOICE_PRESET_MAP = {  # spellchecker:disable-line
    "Alexandra": "kdmDKE6EkgrWrrykO9Qt",  # spellchecker:disable-line
    "Antoni": "ErXwobaYiN019PkySvjV",  # spellchecker:disable-line
    "Austin": "Bj9UqZbhQsanLzgalpEG",  # spellchecker:disable-line
    "Clyde": "2EiwWnXFnvU5JabPnv8n",  # spellchecker:disable-line
    "Dave": "CYw3kZ02Hs0563khs1Fj",  # spellchecker:disable-line
    "Domi": "AZnzlk1XvdvUeBnXmlld",  # spellchecker:disable-line
    "Drew": "29vD33N1CtxCmqQRPOHJ",  # spellchecker:disable-line
    "Fin": "D38z5RcWu1voky8WS1ja",  # spellchecker:disable-line
    "Hope": "tnSpp4vdxKPjI9w0GnoV",  # spellchecker:disable-line
    "James": "EkK5I93UQWFDigLMpZcX",  # spellchecker:disable-line
    "Jane": "RILOU7YmBhvwJGDGjNmP",  # spellchecker:disable-line
    "Paul": "5Q0t7uMcjvnagumLfvZi",  # spellchecker:disable-line
    "Rachel": "21m00Tcm4TlvDq8ikWAM",  # spellchecker:disable-line
    "Sarah": "EXAVITQu4vr4xnSDxMaL",  # spellchecker:disable-line
    "Thomas": "GBv7mTt0atIp3Br8iCZE",  # spellchecker:disable-line
}


class ElevenLabsVoiceChanger(SuccessFailureNode):
    """Transform audio from one voice to another using Eleven Labs speech-to-speech API.

    Supports both audio and video inputs. If video is provided, audio will be extracted first.
    Maintains full control over emotion, timing, and delivery of the original audio.

    Outputs:
        - audio_url (AudioUrlArtifact): Transformed audio with new voice as URL artifact
    """

    SERVICE_NAME = "ElevenLabs"
    API_KEY_NAME = "ELEVEN_LABS_API_KEY"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "ElevenLabs.Audio"
        self.description = "Transform audio from one voice to another using Eleven Labs speech-to-speech"

        # ElevenLabs API base URL
        self._api_base = "https://api.elevenlabs.io/v1/"

        # INPUTS / PROPERTIES
        # Audio/Video input

        self.add_parameter(
            Parameter(
                name="audio_or_video",
                input_types=["any"],
                type="AudioUrlArtifact",
                tooltip="Audio or video file to transform. If video is provided, audio will be extracted first.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "clickable_file_browser": True,
                    "expander": True,
                    "display_name": "Audio or Video",
                    "hide_property": True,
                },
            )
        )

        # Voice preset selection
        self.add_parameter(
            Parameter(
                name="voice_preset",
                input_types=["str"],
                type="str",
                default_value="Alexandra",
                tooltip="Select a preset voice or choose 'Custom...' to enter a voice ID",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={
                    Options(
                        choices=[
                            "Alexandra",
                            "Antoni",
                            "Austin",
                            "Clyde",
                            "Dave",
                            "Domi",
                            "Drew",
                            "Fin",
                            "Hope",
                            "James",
                            "Jane",
                            "Paul",
                            "Rachel",
                            "Sarah",
                            "Thomas",
                            "Custom...",
                        ]
                    )
                },
                ui_options={"display_name": "Voice"},
            )
        )

        # Custom voice ID field (hidden by default)
        self.add_parameter(
            Parameter(
                name="custom_voice_id",
                input_types=["str"],
                type="str",
                tooltip="Enter a custom Eleven Labs voice ID (must be publicly accessible)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "display_name": "Custom Voice ID",
                    "hide": True,
                    "placeholder_text": "e.g., 21m00Tcm4TlvDq8ikWAM",
                },
                traits={
                    Button(
                        size="icon",
                        icon="audio-lines",
                        tooltip="Search for a voice",
                        button_link="https://elevenlabs.io/app/voice-library",
                    )
                },
            )
        )

        # Voice preview (input/property that gets set to preview URL)
        self.add_parameter(
            Parameter(
                name="voice_preview",
                input_types=["AudioUrlArtifact"],
                type="AudioUrlArtifact",
                tooltip="Preview audio sample of the selected voice (automatically set when voice is selected)",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Voice Preview", "expander": True, "hide_property": False},
            )
        )
        self.error_message = ParameterMessage(
            name="error_message",
            variant="error",
            value="",
            markdown=True,
            hide=True,
            button_link="https://elevenlabs.io/app/voice-library",
            button_icon="audio-lines",
            button_text="View Voice Library",
        )
        self.add_node_element(self.error_message)

        # Voice Settings
        with ParameterGroup(name="Voice_Settings", collapsed=True) as voice_settings_group:
            ParameterString(
                name="stability",
                default_value="Natural",
                tooltip="Controls voice consistency. Creative (0.0) = more variable and emotional, Natural (0.5) = balanced, Robust (1.0) = most stable and consistent.",
                allow_input=True,
                allow_property=True,
                allow_output=False,
                traits={Options(choices=["Creative", "Natural", "Robust"])},
            )
            ParameterFloat(
                name="similarity_boost",
                default_value=0.75,
                min_val=0.0,
                max_val=1.0,
                slider=True,
                tooltip="Controls how similar the generated voice is to the original voice. Higher values make it more similar.",
                allow_input=True,
                allow_property=True,
                allow_output=False,
            )
        self.add_node_element(voice_settings_group)
        # Model selection
        self.add_parameter(
            Parameter(
                name="model_id",
                input_types=["str"],
                type="str",
                default_value="eleven_multilingual_sts_v2",
                tooltip="Select the speech-to-speech model to use",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["eleven_multilingual_sts_v2"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="seed",
                input_types=["int"],
                type="int",
                default_value=-1,
                tooltip="Seed for reproducible generation (-1 for random seed)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Seed"},
            )
        )

        self.add_parameter(
            Parameter(
                name="remove_background_noise",
                input_types=["bool"],
                type="bool",
                default_value=False,
                tooltip="Remove background noise from the input audio",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Remove Background Noise"},
            )
        )

        # Output format
        self.add_parameter(
            Parameter(
                name="output_format",
                input_types=["str"],
                type="str",
                default_value="mp3_44100_128",
                tooltip="Output format of the generated audio (codec_sample_rate_bitrate)",
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
        # OUTPUTS
        self.add_parameter(
            Parameter(
                name="audio_url",
                output_type="AudioUrlArtifact",
                type="AudioUrlArtifact",
                tooltip="Transformed audio with new voice as URL artifact",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
                settable=False,
                ui_options={"is_full_width": True, "pulse_on_run": True},
            )
        )

        # Create status output parameters for success/failure information
        self._create_status_parameters(
            result_details_tooltip="Details about the voice transformation result or any errors encountered",
            result_details_placeholder="Voice transformation status will appear here...",
            parameter_group_initially_collapsed=False,
        )

        # Fetch voice preview for the default voice on node creation
        self._fetch_voice_preview()

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        """Update parameter visibility based on voice preset selection and fetch preview."""
        if parameter.name == "voice_preset":
            if value == "Custom...":
                self.show_parameter_by_name("custom_voice_id")
                # Don't fetch preview yet - wait for custom_voice_id to be set
            else:
                self.hide_parameter_by_name("custom_voice_id")
                # Fetch preview for the selected preset voice
                self._fetch_voice_preview()

        if parameter.name == "custom_voice_id":
            # Fetch preview when custom voice ID is set (only if voice_preset is "Custom...")
            voice_preset = self.get_parameter_value("voice_preset")
            if voice_preset == "Custom...":
                # Only fetch if we have a non-empty value
                if value and isinstance(value, str) and value.strip():
                    self._fetch_voice_preview()
                else:
                    # Clear preview if custom_voice_id is empty
                    self.set_parameter_value("voice_preview", None, emit_change=False)

        return super().after_value_set(parameter, value)

    def validate_before_node_run(self) -> list[Exception] | None:
        """Validate that required configuration is available before running the node."""
        errors = []

        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            errors.append(
                ValueError(f"{self.name} is missing {self.API_KEY_NAME}. Ensure it's set in the environment/config.")
            )

        audio_or_video = self.get_parameter_value("audio_or_video")
        if not audio_or_video:
            errors.append(ValueError(f"{self.name} requires an audio or video input."))

        return errors or None

    def _log(self, message: str) -> None:
        with suppress(Exception):
            logger.info(message)

    def process(self) -> None:
        pass

    async def aprocess(self) -> None:
        await self._process_async()

    async def _process_async(self) -> None:
        """Async implementation of the processing logic."""
        self._clear_execution_status()

        try:
            # Get and prepare audio input
            audio_url = await self._prepare_audio_input()
            if not audio_url:
                self._set_safe_defaults()
                self._set_status_results(was_successful=False, result_details="Failed to prepare audio input")
                return

            # Get parameters
            params = self._get_parameters()
            voice_id = params.pop("voice_id")

            # Download audio file
            audio_bytes = await self._download_audio(audio_url)

            # Submit request
            response_bytes = await self._submit_request(voice_id, audio_bytes, params)

            if response_bytes:
                self._handle_response(response_bytes)
                self._set_status_results(
                    was_successful=True, result_details="Voice transformation completed successfully"
                )
            else:
                self._set_safe_defaults()
                self._set_status_results(was_successful=False, result_details="No audio data received from API")

        except Exception as e:
            self._set_safe_defaults()
            error_message = str(e)
            self._set_status_results(was_successful=False, result_details=error_message)
            self._handle_failure_exception(e)

    async def _prepare_audio_input(self) -> str | None:
        """Prepare audio input, extracting from video if necessary."""
        audio_or_video = self.get_parameter_value("audio_or_video")

        if not audio_or_video:
            return None

        # Check if it's a video artifact
        if hasattr(audio_or_video, "__class__") and "Video" in audio_or_video.__class__.__name__:
            # Extract audio from video
            video_url = self._extract_url_from_artifact(audio_or_video)
            if not video_url:
                error_msg = f"{self.name} could not extract URL from video input"
                raise ValueError(error_msg)
            audio_url = await self._extract_audio_from_video(video_url)
            return audio_url

        # It's already audio
        audio_url = self._extract_url_from_artifact(audio_or_video)
        return audio_url

    def _extract_url_from_artifact(self, artifact: Any) -> str | None:
        """Extract URL from artifact (audio or video)."""
        if isinstance(artifact, str):
            return artifact

        if hasattr(artifact, "value"):
            value = artifact.value
            if isinstance(value, str):
                return value

        return None

    async def _extract_audio_from_video(self, video_url: str) -> str:
        """Extract audio from video using FFmpeg."""
        try:
            import static_ffmpeg.run  # type: ignore[import-untyped]
        except ImportError:
            error_msg = f"{self.name} requires FFmpeg to extract audio from video. Please ensure FFmpeg is available."
            raise ValueError(error_msg) from None

        # Get FFmpeg path (returns tuple of ffmpeg_path, ffprobe_path)
        try:
            ffmpeg_path, _ = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        except Exception as e:
            error_msg = f"FFmpeg not found. Please ensure static-ffmpeg is properly installed. Error: {e!s}"
            raise ValueError(error_msg) from e

        # Create temporary output file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
            temp_audio_path = Path(temp_file.name)

        try:
            # Build FFmpeg command to extract audio
            cmd = [
                ffmpeg_path,
                "-i",
                video_url,
                "-vn",  # No video
                "-acodec",
                "libmp3lame",
                "-b:a",
                "128k",
                "-y",  # Overwrite
                str(temp_audio_path),
            ]

            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)  # noqa: S603

            if not temp_audio_path.exists() or temp_audio_path.stat().st_size == 0:
                error_msg = "FFmpeg did not create output file or file is empty"
                raise ValueError(error_msg)

            # Read audio bytes and save to static storage
            with temp_audio_path.open("rb") as f:
                audio_bytes = f.read()

            # Save to static storage and return URL
            filename = f"extracted_audio_{int(time.time())}.mp3"
            static_files_manager = GriptapeNodes.StaticFilesManager()
            audio_url = static_files_manager.save_static_file(audio_bytes, filename)

            return audio_url

        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg failed to extract audio: {e.stderr}"
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to extract audio from video: {e}"
            raise ValueError(error_msg) from e
        finally:
            # Clean up temp file
            if temp_audio_path.exists():
                temp_audio_path.unlink()

    async def _download_audio(self, audio_url: str) -> bytes:
        """Download audio from URL."""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.get(audio_url)
                response.raise_for_status()
                return response.content
        except Exception as e:
            error_msg = f"Failed to download audio from {audio_url}: {e}"
            raise ValueError(error_msg) from e

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameters for the API request."""
        voice_preset = self.get_parameter_value("voice_preset")
        voice_id = None
        if voice_preset == "Custom...":
            voice_id = self.get_parameter_value("custom_voice_id")
        elif voice_preset:
            voice_id = VOICE_PRESET_MAP.get(voice_preset)

        if not voice_id:
            error_msg = f"{self.name} requires a valid voice selection"
            raise ValueError(error_msg)

        model_id = self.get_parameter_value("model_id") or "eleven_multilingual_sts_v2"
        output_format = self.get_parameter_value("output_format") or "mp3_44100_128"
        seed = self.get_parameter_value("seed")
        remove_background_noise = self.get_parameter_value("remove_background_noise") or False
        stability_str = self.get_parameter_value("stability")
        similarity_boost = self.get_parameter_value("similarity_boost")

        params: dict[str, Any] = {
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
        }

        # Add optional parameters
        if seed is not None and seed != -1:
            params["seed"] = seed

        if remove_background_noise:
            params["remove_background_noise"] = True

        # Build voice_settings
        voice_settings = {}
        if stability_str is not None:
            match stability_str:
                case "Creative":
                    voice_settings["stability"] = 0.0
                case "Natural":
                    voice_settings["stability"] = 0.5
                case "Robust":
                    voice_settings["stability"] = 1.0
                case _:
                    msg = f"{self.name} received invalid stability value: {stability_str}. Must be one of: Creative, Natural, or Robust"
                    raise ValueError(msg)

        if similarity_boost is not None:
            voice_settings["similarity_boost"] = similarity_boost

        if voice_settings:
            params["voice_settings"] = _json.dumps(voice_settings)

        return params

    def _get_api_key(self) -> str:
        """Get the API key - validation is done in validate_before_node_run()."""
        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            msg = f"{self.name} is missing {self.API_KEY_NAME}. This should have been caught during validation."
            raise RuntimeError(msg)
        return api_key

    def _get_voice_id(self) -> str | None:
        """Get the current voice ID from preset or custom field."""
        voice_preset = self.get_parameter_value("voice_preset")
        custom_voice_id = self.get_parameter_value("custom_voice_id")

        # If voice_preset is "Custom..." and we have a custom_voice_id, use it
        if voice_preset == "Custom...":
            if custom_voice_id and isinstance(custom_voice_id, str) and custom_voice_id.strip():
                return custom_voice_id.strip()
            return None

        # Otherwise, use the preset mapping
        if voice_preset:
            return VOICE_PRESET_MAP.get(voice_preset)

        return None

    def _fetch_voice_preview(self) -> None:
        """Fetch and set the preview URL for the selected voice."""
        voice_id = self._get_voice_id()
        if not voice_id:
            self.set_parameter_value("voice_preview", None, emit_change=False)
            self.error_message.value = ""
            self.hide_message_by_name("error_message")
            return

        try:
            api_key = self._get_api_key()
            if not api_key:
                self._log("Cannot fetch voice preview: API key not available")
                self.set_parameter_value("voice_preview", None, emit_change=False)
                self.error_message.value = "API key not available"
                self.show_message_by_name("error_message")
                return

            headers = {"xi-api-key": api_key}

            self._log(f"Fetching voice preview for voice_id: {voice_id}")

            # Try direct voice endpoint first
            url = urljoin(self._api_base, f"voices/{voice_id}")

            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=headers)

                # Handle specific error cases with detailed error messages
                if response.status_code == 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("detail", {}).get("message", error_text)
                    except Exception:
                        error_msg = error_text
                    self._log(f"Voice ID '{voice_id}' error (400 Bad Request): {error_msg}")
                    error_message = (
                        f"Voice '{voice_id}' is not accessible. \n\n"
                        "To use voices from the Voice Library, you must first add them to 'My Voices' "
                        "at https://elevenlabs.io/app/voice-library. "
                        "Once added to your account, the voice preview will be available."
                    )
                    self.error_message.value = error_message
                    self.show_message_by_name("error_message")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    return
                if response.status_code == 404:
                    self._log(f"Voice ID '{voice_id}' not found (404 Not Found)")
                    error_message = (
                        f"Voice '{voice_id}' not found in your account. "
                        "To use voices from the Voice Library, you must first add them to 'My Voices' "
                        "at https://elevenlabs.io/app/voice-library. "
                        "Once added to your account, the voice preview will be available."
                    )
                    self.error_message.value = error_message
                    self.show_message_by_name("error_message")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    return
                if response.status_code == 401:
                    self._log("Unauthorized - API key may be invalid or voice is private")
                    error_message = (
                        "Unauthorized access. The API key may be invalid, or the voice is private. "
                        "To use voices from the Voice Library, you must first add them to 'My Voices' "
                        "at https://elevenlabs.io/app/voice-library."
                    )
                    self.error_message.value = error_message
                    self.show_message_by_name("error_message")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    return

                response.raise_for_status()
                voice_data = response.json()

                preview_url = voice_data.get("preview_url")
                if preview_url:
                    preview_artifact = AudioUrlArtifact(value=str(preview_url))
                    self.set_parameter_value("voice_preview", preview_artifact, emit_change=True)
                    self.error_message.value = ""
                    self.hide_message_by_name("error_message")
                    self._log(f"Successfully fetched voice preview: {preview_url}")
                else:
                    self._log("Voice data does not contain preview_url")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    self.error_message.value = "Voice data does not contain preview_url"
                    self.show_message_by_name("error_message")
        except httpx.HTTPStatusError as e:
            error_text = e.response.text
            try:
                error_data = e.response.json()
                error_msg = error_data.get("detail", {}).get("message", error_text)
            except Exception:
                error_msg = error_text
            self._log(f"HTTP error fetching voice preview ({e.response.status_code}): {error_msg}")
            error_message = (
                f"Failed to fetch voice preview (HTTP {e.response.status_code}): {error_msg}. "
                "To use voices from the Voice Library, you must first add them to 'My Voices' "
                "at https://elevenlabs.io/app/voice-library."
            )
            self.error_message.value = error_message
            self.show_message_by_name("error_message")
            self.set_parameter_value("voice_preview", None, emit_change=False)
        except Exception as e:
            self._log(f"Failed to fetch voice preview: {e}")
            error_message = (
                f"Failed to fetch voice preview: {e}. "
                "To use voices from the Voice Library, you must first add them to 'My Voices' "
                "at https://elevenlabs.io/app/voice-library."
            )
            self.error_message.value = error_message
            self.show_message_by_name("error_message")
            self.set_parameter_value("voice_preview", None, emit_change=False)

    async def _submit_request(self, voice_id: str, audio_bytes: bytes, params: dict[str, Any]) -> bytes | None:
        """Submit request to ElevenLabs speech-to-speech API (direct API, not proxy)."""
        api_key = self._get_api_key()
        url = urljoin(self._api_base, f"speech-to-speech/{voice_id}")

        # Build query parameters
        query_params: dict[str, Any] = {}
        if "output_format" in params:
            query_params["output_format"] = params.pop("output_format")

        # Build multipart form data (as per ElevenLabs API docs)
        files = {"audio": ("audio.mp3", audio_bytes, "audio/mpeg")}

        form_data: dict[str, Any] = {}
        if "model_id" in params:
            form_data["model_id"] = params.pop("model_id")
        if "seed" in params:
            form_data["seed"] = str(params.pop("seed"))
        if "remove_background_noise" in params:
            form_data["remove_background_noise"] = str(params.pop("remove_background_noise")).lower()
        if "voice_settings" in params:
            # voice_settings should be a JSON string for the API
            form_data["voice_settings"] = params.pop("voice_settings")

        headers = {"xi-api-key": api_key}

        self._log(f"Submitting request to ElevenLabs speech-to-speech API with voice: {voice_id}")

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    url,
                    params=query_params,
                    files=files,
                    data=form_data,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._log(f"HTTP error: {e.response.status_code} - {e.response.text}")
            error_message = self._parse_error_response(e.response.text, e.response.status_code)
            raise RuntimeError(error_message) from e
        except Exception as e:
            self._log(f"Request failed: {e}")
            msg = f"Request failed: {e}"
            raise RuntimeError(msg) from e

        self._log("Request submitted successfully")
        return response.content

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
                        return f"{status}: {message}"
                    if message:
                        return f"Error: {message}"

            if "error" in error_data:
                return f"Error: {error_data['error']}"

            return f"API Error ({status_code}): {response_text[:200]}"

        except (_json.JSONDecodeError, KeyError, TypeError):
            return f"API Error ({status_code}): Unable to parse error response"

    def _handle_response(self, response_bytes: bytes) -> None:
        """Handle audio response from API (raw audio bytes)."""
        try:
            self._save_audio_from_bytes(response_bytes)
        except Exception as e:
            self._log(f"Failed to process response: {e}")
            self.parameter_output_values["audio_url"] = None
            raise

    def _save_audio_from_bytes(self, audio_bytes: bytes) -> None:
        """Save audio bytes to static storage."""
        try:
            filename = f"eleven_voice_changer_{int(time.time())}.mp3"

            static_files_manager = GriptapeNodes.StaticFilesManager()
            saved_url = static_files_manager.save_static_file(audio_bytes, filename)
            self.parameter_output_values["audio_url"] = AudioUrlArtifact(value=saved_url, name=filename)
            self._log(f"Saved transformed audio to static storage as {filename}")
        except Exception as e:
            self._log(f"Failed to save audio from bytes: {e}")
            self.parameter_output_values["audio_url"] = None
            raise

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["audio_url"] = None
