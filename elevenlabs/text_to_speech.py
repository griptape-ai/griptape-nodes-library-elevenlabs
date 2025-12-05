from __future__ import annotations

import json as _json
import logging
import time
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


class ElevenLabsTextToSpeech(SuccessFailureNode):
    """Generate speech from text using ElevenLabs text-to-speech API (direct API, not proxy).

    Supports voice selection, voice settings, and optional context for continuity.

    Outputs:
        - audio (AudioUrlArtifact): Generated speech audio as URL artifact
        - alignment (dict): Character alignment data with start/end times (if available)
    """

    SERVICE_NAME = "ElevenLabs"
    API_KEY_NAME = "ELEVEN_LABS_API_KEY"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "ElevenLabs.Audio"
        self.description = "Generate speech from text using ElevenLabs text-to-speech API"

        # ElevenLabs API base URL
        self._api_base = "https://api.elevenlabs.io/v1/"

        # INPUTS / PROPERTIES
        # Text input
        self.add_parameter(
            Parameter(
                name="text",
                input_types=["str"],
                type="str",
                tooltip="Text to convert to speech",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Enter text to convert to speech...",
                    "display_name": "Text",
                },
            )
        )

        # Model selection
        self.add_parameter(
            Parameter(
                name="model_id",
                input_types=["str"],
                type="str",
                default_value="eleven_multilingual_v2",
                tooltip=(
                    "ElevenLabs model to use. "
                    "eleven_v3: Most expressive (alpha, 3k char limit, no previous_text/next_text). "
                    "eleven_multilingual_v2: Best for long-form (10k char limit). "
                    "eleven_flash_v2_5: Ultra-fast (~75ms). "
                    "eleven_turbo_v2_5: Fast and high quality (~250-300ms)."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={
                    Options(
                        choices=[
                            "eleven_multilingual_v2",
                            "eleven_turbo_v2_5",
                            "eleven_flash_v2_5",
                            "eleven_v3",
                            "eleven_turbo_v2",
                            "eleven_flash_v2",
                            "eleven_monolingual_v1",
                        ]
                    )
                },
                ui_options={"display_name": "Model"},
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
                tooltip="Enter a custom Eleven Labs voice ID",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "display_name": "Custom Voice ID",
                    "hide": True,
                    "placeholder_text": "e.g., 21m00Tcm4TlvDq8ikWAM",
                    "traits": [
                        Button(
                            size="icon",
                            icon="audio-lines",
                            tooltip="Search for a voice",
                            button_link="https://elevenlabs.io/app/voice-library",
                        )
                    ],
                },
            )
        )

        # Voice preview
        self.add_parameter(
            Parameter(
                name="voice_preview",
                input_types=["AudioUrlArtifact"],
                type="AudioUrlArtifact",
                tooltip="Preview audio sample of the selected voice (automatically set when voice is selected)",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Voice Preview", "expander": True, "hide_property": False, "height": "xs"},
            )
        )

        self.error_message = ParameterMessage(
            name="error_message",
            variant="warning",
            value="",
            markdown=True,
            hide=True,
            button_link="https://elevenlabs.io/app/voice-library",
            button_icon="audio-lines",
            button_text="View Voice Library",
        )
        self.add_node_element(self.error_message)

        self.add_parameter(
            Parameter(
                name="language_code",
                input_types=["str"],
                type="str",
                tooltip="ISO 639-1 language code as a hint for pronunciation (optional, defaults to 'en')",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "display_name": "Language Code",
                    "placeholder_text": "e.g., en, es, fr",
                },
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
                name="previous_text",
                input_types=["str"],
                type="str",
                tooltip="Context for what text comes before the generated speech. Helps maintain continuity between consecutive speech generations. Not supported with eleven_v3 model.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "display_name": "Previous Text",
                    "placeholder_text": "Optional: provide text that comes before for continuity...",
                    "hide": False,
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="next_text",
                input_types=["str"],
                type="str",
                tooltip="Context for what text comes after the generated speech. Helps maintain continuity between consecutive speech generations. Not supported with eleven_v3 model.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "display_name": "Next Text",
                    "placeholder_text": "Optional: provide text that comes after for continuity...",
                    "hide": False,
                },
            )
        )

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
                name="speed",
                default_value=1.0,
                min_val=0.7,
                max_val=1.2,
                slider=True,
                tooltip="Controls speech rate. Default is 1.0 (normal pace). Values below 1.0 slow down speech (minimum 0.7), values above 1.0 speed up speech (maximum 1.2). Extreme values may affect quality.",
                allow_input=True,
                allow_property=True,
                allow_output=False,
            )
        self.add_node_element(voice_settings_group)

        # OUTPUTS
        self.add_parameter(
            Parameter(
                name="audio",
                output_type="AudioUrlArtifact",
                type="AudioUrlArtifact",
                tooltip="Generated speech audio as URL artifact",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
                settable=False,
                ui_options={"display_name": "Audio", "pulse_on_run": True},
            )
        )

        # Alignment outputs
        self.add_parameter(
            Parameter(
                name="alignment",
                output_type="dict",
                type="dict",
                tooltip="Character alignment data with start/end times (if available)",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"hide_property": True},
            )
        )

        # Create status output parameters for success/failure information
        self._create_status_parameters(
            result_details_tooltip="Details about the text-to-speech generation result or any errors encountered",
            result_details_placeholder="Text-to-speech generation status will appear here...",
            parameter_group_initially_collapsed=False,
        )

        # Initialize visibility based on default model
        # Hide previous_text and next_text if default model is eleven_v3
        default_model = self.get_parameter_value("model_id") or "eleven_multilingual_v2"
        if default_model == "eleven_v3":
            self.hide_parameter_by_name("previous_text")
            self.hide_parameter_by_name("next_text")

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        """Update parameter visibility and fetch voice preview based on voice preset selection."""
        if parameter.name == "voice_preset":
            if value == "Custom...":
                self.show_parameter_by_name("custom_voice_id")
            else:
                self.hide_parameter_by_name("custom_voice_id")
            self._fetch_voice_preview()

        if parameter.name == "custom_voice_id":
            # Only fetch if voice_preset is "Custom..." and custom_voice_id is not empty
            if self.get_parameter_value("voice_preset") == "Custom..." and value and value.strip():
                self._fetch_voice_preview()
            else:
                self.set_parameter_value("voice_preview", None, emit_change=False)

        if parameter.name == "model_id":
            # Hide previous_text and next_text for eleven_v3 (not supported)
            if value == "eleven_v3":
                self.hide_parameter_by_name("previous_text")
                self.hide_parameter_by_name("next_text")
            else:
                self.show_parameter_by_name("previous_text")
                self.show_parameter_by_name("next_text")

        return super().after_value_set(parameter, value)

    def validate_before_node_run(self) -> list[Exception] | None:
        """Validate that required configuration is available before running the node."""
        errors = []

        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            errors.append(
                ValueError(f"{self.name} is missing {self.API_KEY_NAME}. Ensure it's set in the environment/config.")
            )

        text = self.get_parameter_value("text")
        if not text or not text.strip():
            errors.append(ValueError(f"{self.name}: Text input is required."))

        return errors or None

    def _log(self, message: str) -> None:
        logger.info(f"{self.name}: {message}")

    def process(self) -> None:
        pass

    async def aprocess(self) -> None:
        await self._process_async()

    async def _process_async(self) -> None:
        """Async implementation of the processing logic."""
        self._clear_execution_status()

        try:
            params = self._get_parameters()
        except Exception as e:
            self._set_safe_defaults()
            error_message = str(e)
            self._set_status_results(was_successful=False, result_details=error_message)
            self._handle_failure_exception(e)
            return

        api_key = self._get_api_key()
        voice_id = self._get_voice_id()

        if not voice_id:
            error_msg = f"{self.name}: Voice ID is required. Please select a voice preset or enter a custom voice ID."
            self._set_safe_defaults()
            self._set_status_results(was_successful=False, result_details=error_msg)
            self._handle_failure_exception(ValueError(error_msg))
            return

        self._log(f"Generating speech with voice {voice_id} via ElevenLabs API")

        try:
            response_bytes = await self._submit_request(voice_id, params, api_key)
            if response_bytes:
                self._handle_response(response_bytes)
                self._set_status_results(was_successful=True, result_details="Speech generated successfully")
            else:
                self._set_safe_defaults()
                self._set_status_results(was_successful=False, result_details="No audio data received from API")
        except Exception as e:
            self._set_safe_defaults()
            error_message = str(e)
            self._set_status_results(was_successful=False, result_details=error_message)
            self._handle_failure_exception(e)

    def _get_voice_id(self) -> str | None:
        """Get the voice ID from preset or custom input."""
        voice_preset = self.get_parameter_value("voice_preset")
        custom_voice_id = self.get_parameter_value("custom_voice_id")

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
            self.show_parameter_by_name("voice_preview")
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

            # Try direct voice endpoint
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
                    self.hide_parameter_by_name("voice_preview")
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
                    self.hide_parameter_by_name("voice_preview")
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
                    self.hide_parameter_by_name("voice_preview")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    return

                response.raise_for_status()
                voice_data = response.json()

                preview_url = voice_data.get("preview_url")
                if preview_url:
                    from griptape.artifacts import AudioUrlArtifact

                    preview_artifact = AudioUrlArtifact(value=str(preview_url))
                    self.set_parameter_value("voice_preview", preview_artifact, emit_change=True)
                    self.error_message.value = ""
                    self.hide_message_by_name("error_message")
                    self.show_parameter_by_name("voice_preview")
                    self._log(f"Successfully fetched voice preview: {preview_url}")
                else:
                    self._log("Voice data does not contain preview_url")
                    self.set_parameter_value("voice_preview", None, emit_change=False)
                    self.error_message.value = "Voice data does not contain preview_url"
                    self.show_message_by_name("error_message")
                    self.hide_parameter_by_name("voice_preview")
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
            self.hide_parameter_by_name("voice_preview")
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
            self.hide_parameter_by_name("voice_preview")
            self.set_parameter_value("voice_preview", None, emit_change=False)

    def _get_parameters(self) -> dict[str, Any]:
        text = self.get_parameter_value("text") or ""
        model_id = self.get_parameter_value("model_id") or "eleven_multilingual_v2"
        language_code = self.get_parameter_value("language_code")
        seed = self.get_parameter_value("seed")
        previous_text = self.get_parameter_value("previous_text")
        next_text = self.get_parameter_value("next_text")
        stability_str = self.get_parameter_value("stability")
        speed = self.get_parameter_value("speed")

        params: dict[str, Any] = {
            "text": text,
            "model_id": model_id,
        }

        # Add optional parameters if they have values
        if language_code:
            params["language_code"] = language_code
        if seed is not None and seed != -1:
            params["seed"] = seed

        # previous_text and next_text are not supported with eleven_v3
        if model_id != "eleven_v3":
            if previous_text:
                params["previous_text"] = previous_text
            if next_text:
                params["next_text"] = next_text

        # Add voice_settings with stability and speed
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

        if speed is not None:
            voice_settings["speed"] = speed

        if voice_settings:
            params["voice_settings"] = voice_settings

        return params

    def _get_api_key(self) -> str:
        """Get the API key - validation is done in validate_before_node_run()."""
        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            msg = f"{self.name} is missing {self.API_KEY_NAME}. This should have been caught during validation."
            raise RuntimeError(msg)
        return api_key

    async def _submit_request(self, voice_id: str, params: dict[str, Any], api_key: str) -> bytes | None:
        """Submit request to ElevenLabs text-to-speech API (direct API, not proxy)."""
        url = urljoin(self._api_base, f"text-to-speech/{voice_id}")

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        self._log(f"Submitting request to ElevenLabs API: {url}")
        self._log_request(params)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, json=params, headers=headers)
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
        """Parse error response and extract meaningful error information."""
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
                elif isinstance(detail, str):
                    return f"Error: {detail}"

            if "error" in error_data:
                error_msg = error_data["error"]
                if isinstance(error_msg, str):
                    return f"Error: {error_msg}"

            return f"API Error ({status_code}): {response_text[:200]}"

        except Exception:
            return f"API Error ({status_code}): Unable to parse error response"

    def _log_request(self, payload: dict[str, Any]) -> None:
        """Log request payload with truncated text for readability."""
        try:
            sanitized_payload = payload.copy()
            for key in ["text", "previous_text", "next_text"]:
                if key in sanitized_payload:
                    text_value = sanitized_payload[key]
                    if isinstance(text_value, str) and len(text_value) > PROMPT_TRUNCATE_LENGTH:
                        sanitized_payload[key] = text_value[:PROMPT_TRUNCATE_LENGTH] + "..."

            self._log(f"Request payload: {_json.dumps(sanitized_payload, indent=2)}")
        except Exception:
            pass

    def _handle_response(self, response_bytes: bytes) -> None:
        """Handle audio response from ElevenLabs API."""
        try:
            self._log("Processing audio bytes from API response")
            filename = f"eleven_tts_{int(time.time())}.mp3"

            static_files_manager = GriptapeNodes.StaticFilesManager()
            saved_url = static_files_manager.save_static_file(response_bytes, filename)
            self.parameter_output_values["audio"] = AudioUrlArtifact(value=saved_url, name=filename)
            self._log(f"Saved audio to static storage as {filename}")

            # Note: Direct API doesn't provide alignment data in the same format as proxy
            # Set to None for now
            self.parameter_output_values["alignment"] = None

        except Exception as e:
            self._log(f"Failed to save audio from bytes: {e}")
            self.parameter_output_values["audio"] = None
            self.parameter_output_values["alignment"] = None
            raise

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["audio"] = None
        self.parameter_output_values["alignment"] = None
