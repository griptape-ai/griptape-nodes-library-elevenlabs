from __future__ import annotations

import json as _json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from griptape.artifacts.audio_artifact import AudioArtifact
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact

from griptape_nodes.exe_types.core_types import Parameter, ParameterList, ParameterMessage, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.multi_options import MultiOptions

logger = logging.getLogger(__name__)


class ElevenLabsCloneVoice(DataNode):
    """Clone a voice from audio samples using ElevenLabs Instant Voice Cloning API.

    Inputs:
    - audio: Audio file(s) to use for cloning (AudioUrlArtifact, AudioArtifact, or list).
             Multiple files improve clone quality.
    - voice_name: Name for the cloned voice.
    - remove_background_noise: If true, remove background noise from audio samples.
    - description: Optional description for the voice.
    - labels: Optional labels (comma-separated string) for categorizing the voice.

    Outputs:
    - voice_id: The ID of the created voice clone (str).
    - requires_verification: Whether the voice requires verification (bool).
    """

    API_KEY_NAME: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Clone a voice from audio samples using Instant Voice Cloning."

        # Helpful message about audio requirements
        self.audio_requirements_message = ParameterMessage(
            name="audio_requirements",
            variant="info",
            value=(
                "**Audio Sample Requirements:**\n\n"
                "• **Duration:** 1-2 minutes of clear audio (recommended for Instant Voice Cloning)\n\n"
                "• **Quality:** Clear, noise-free recordings with consistent volume and tone\n\n"
                "• **Content:** Single speaker, no background noise, minimal reverb\n\n"
                "• **Multiple files:** Providing multiple audio samples improves clone quality\n\n"
                "• **Format:** MP3, 192kbps+\n\n"
                "For best results, use professional recording equipment in a quiet environment."
            ),
            full_width=True,
            markdown=True,
            hide=False,
            button_link="https://elevenlabs.io/docs/product-guides/voices/voice-cloning",
            button_icon="book-open",
            button_text="View Voice Cloning Documentation",
        )
        self.add_node_element(self.audio_requirements_message)

        # Inputs / Properties
        self.audio_list = ParameterList(
            name="audio",
            tooltip=(
                "Audio file(s) to use for cloning. "
                "Recommended: 1-2 minutes of clear, high-quality audio (MP3, 192kbps+). "
                "Multiple files improve clone quality. "
                "Ensure recordings are noise-free with a single speaker and consistent tone."
            ),
            input_types=["AudioArtifact", "AudioUrlArtifact"],
            type="AudioUrlArtifact",
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            default_value=[],
            ui_options={
                "display_name": "Audio Sample(s)",
                "expander": True,
            },
        )
        self.add_parameter(self.audio_list)
        self.add_parameter(
            Parameter(
                name="voice_name",
                input_types=["str"],
                type="str",
                default_value="Cloned Voice",
                tooltip="Name for the cloned voice.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Voice Name", "placeholder_text": "My Voice Clone"},
            )
        )
        self.add_parameter(
            ParameterBool(
                name="remove_background_noise",
                default_value=False,
                tooltip="If true, remove background noise from audio samples.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Remove Background Noise"},
            )
        )
        self.add_parameter(
            Parameter(
                name="description",
                input_types=["str"],
                type="str",
                default_value=None,
                tooltip="Optional description for the voice.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "display_name": "Description",
                    "multiline": True,
                    "placeholder_text": "e.g., A warm, friendly voice with a slight British accent, perfect for narration",
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="labels",
                default_value=None,
                tooltip=(
                    "Optional labels for categorizing the voice. "
                    'Can be a JSON object string (e.g., \'{"accent": "british", "gender": "male"}\') '
                    "or comma-separated values (e.g., 'narrator, male, deep'). "
                    "Will be serialized as JSON for the API."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                type="list",
                traits={
                    MultiOptions(
                        choices=[
                            "narrator",
                            "male",
                            "female",
                            "deep",
                            "accented",
                            "neutral",
                        ],
                        allow_user_created_options=True,
                    )
                },
            )
        )

        # Outputs
        self.add_parameter(
            Parameter(
                name="voice_id",
                output_type="str",
                type="str",
                tooltip="The ID of the created voice clone.",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Voice ID"},
            )
        )
        self.add_parameter(
            Parameter(
                name="requires_verification",
                output_type="bool",
                type="bool",
                tooltip="Whether the voice requires verification.",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Requires Verification"},
            )
        )

    def process(self) -> Any:
        yield lambda: self._run()

    def _run(self) -> None:
        audio_input = self.get_parameter_value("audio")
        voice_name: str = self.get_parameter_value("voice_name") or "Cloned Voice"
        remove_background_noise: bool = bool(self.get_parameter_value("remove_background_noise"))
        description: str | None = self.get_parameter_value("description")
        labels: str | None = self.get_parameter_value("labels")

        if not audio_input:
            error_msg = f"{self.name}: Audio input is required for voice cloning."
            raise ValueError(error_msg)

        # Get API key
        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            error_msg = f"{self.name} is missing {self.API_KEY_NAME}. Ensure it's set in the environment/config."
            raise RuntimeError(error_msg)

        # ParameterList returns a list directly, but we need to handle it properly
        # Normalize audio input to list of artifacts
        audio_list = self._normalize_audio_input(audio_input)
        if not audio_list:
            error_msg = f"{self.name}: No valid audio files found in input."
            raise ValueError(error_msg)

        self._logger.info(
            f"CloneVoice: Creating voice clone '{voice_name}' from {len(audio_list)} audio file(s), "
            f"remove_background_noise={remove_background_noise}"
        )

        # Prepare files for multipart upload
        files = []
        temp_files = []

        try:
            for audio in audio_list:
                file_obj = self._prepare_audio_file(audio)
                if file_obj:
                    # Use tuple format: (field_name, (filename, file_obj, content_type))
                    files.append(("files", ("audio.mp3", file_obj, "audio/mpeg")))
                    # Track temp files for cleanup
                    if hasattr(file_obj, "name") and Path(file_obj.name).exists():
                        temp_files.append(Path(file_obj.name))

            if not files:
                error_msg = f"{self.name}: Failed to prepare audio files for upload."
                raise ValueError(error_msg)

            # Make API request - use correct endpoint from API docs
            base_url = "https://api.elevenlabs.io"
            url = f"{base_url}/v1/voices/add"
            headers = {"xi-api-key": api_key}

            # Prepare multipart form data
            data: dict[str, Any] = {"name": voice_name}
            if remove_background_noise:
                data["remove_background_noise"] = "true"
            if description:
                data["description"] = description
            if labels:
                # Serialize labels as JSON string (API expects serialized dictionary)
                # labels can be a list (from MultiOptions) or a string
                labels_json = self._serialize_labels(labels)
                if labels_json:
                    data["labels"] = labels_json

            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, data=data, files=files, headers=headers)
                response.raise_for_status()
                response_data = response.json()

                voice_id = response_data.get("voice_id")
                if not voice_id:
                    error_msg = f"{self.name}: API response missing voice_id."
                    raise RuntimeError(error_msg)

                requires_verification = response_data.get("requires_verification", False)

                self._logger.info(
                    f"CloneVoice: Successfully created voice clone with ID: {voice_id}, "
                    f"requires_verification: {requires_verification}"
                )
                self.parameter_output_values["voice_id"] = voice_id
                self.parameter_output_values["requires_verification"] = requires_verification

        except httpx.HTTPStatusError as e:
            self._logger.error(f"CloneVoice HTTP error: {e.response.status_code} - {e.response.text}")
            error_message = self._parse_error_response(e.response.text, e.response.status_code)
            raise RuntimeError(error_message) from e
        except Exception as e:
            self._logger.error(f"CloneVoice failed: {e}")
            error_msg = f"Failed to create voice clone: {e}"
            raise RuntimeError(error_msg) from e
        finally:
            # Clean up temp files
            for temp_file in temp_files:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except Exception as e:
                    self._logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")

    def _normalize_audio_input(self, audio_input: Any) -> list[AudioUrlArtifact | AudioArtifact]:
        """Normalize audio input to a list of audio artifacts.

        ParameterList returns a list of values from child parameters.
        We need to handle both the list format and individual items.
        """
        if not audio_input:
            return []

        # ParameterList returns a list directly
        if isinstance(audio_input, list):
            result = []
            for item in audio_input:
                normalized = self._normalize_single_audio(item)
                if normalized:
                    result.append(normalized)
            return result

        # Single audio item (fallback for compatibility)
        normalized = self._normalize_single_audio(audio_input)
        return [normalized] if normalized else []

    def _normalize_single_audio(self, audio: Any) -> AudioUrlArtifact | AudioArtifact | None:
        """Normalize a single audio input to AudioUrlArtifact or AudioArtifact."""
        if isinstance(audio, (AudioUrlArtifact, AudioArtifact)):
            return audio

        if isinstance(audio, dict):
            if audio.get("type") == "AudioUrlArtifact" and "value" in audio:
                return AudioUrlArtifact(value=audio["value"])
            if audio.get("type") == "AudioArtifact" and "value" in audio:
                # AudioArtifact requires format parameter
                audio_format = audio.get("format", "mp3")
                return AudioArtifact(value=audio["value"], format=audio_format)

        return None

    def _prepare_audio_file(self, audio: AudioUrlArtifact | AudioArtifact) -> BytesIO | None:
        """Prepare audio file for multipart upload. Returns BytesIO or file-like object."""
        if isinstance(audio, AudioArtifact):
            # Direct bytes from AudioArtifact
            return BytesIO(audio.value)

        if isinstance(audio, AudioUrlArtifact):
            # Download from URL
            audio_url = audio.value
            if not audio_url:
                return None

            try:
                # Download audio bytes
                with httpx.Client(timeout=300.0) as client:
                    response = client.get(audio_url)
                    response.raise_for_status()
                    return BytesIO(response.content)
            except Exception as e:
                self._logger.error(f"Failed to download audio from {audio_url}: {e}")
                return None

        return None

    def _serialize_labels(self, labels: str | list[str]) -> str | None:
        """Serialize labels to JSON format expected by API.

        Accepts either:
        - List of strings: ['narrator', 'male', 'deep'] (from MultiOptions)
        - JSON object string: '{"accent": "british", "gender": "male"}'
        - Comma-separated values: 'narrator, male, deep' (converted to dict with numeric keys)
        """
        if not labels:
            return None

        # Handle list input (from MultiOptions)
        if isinstance(labels, list):
            items = [str(item).strip() for item in labels if item and str(item).strip()]
            if not items:
                return None
            # Convert to dict format - use numeric keys
            labels_dict = {str(i): item for i, item in enumerate(items)}
            return _json.dumps(labels_dict)

        # Handle string input
        if not isinstance(labels, str):
            return None

        labels_str = labels.strip()
        if not labels_str:
            return None

        # Try to parse as JSON first
        try:
            parsed = _json.loads(labels_str)
            # If it's already a dict, serialize it
            if isinstance(parsed, dict):
                return _json.dumps(parsed)
            # If it's a list, convert to dict with numeric keys
            if isinstance(parsed, list):
                return _json.dumps({str(i): item for i, item in enumerate(parsed)})
        except (_json.JSONDecodeError, TypeError):
            # Not valid JSON, treat as comma-separated string
            pass

        # Treat as comma-separated values
        # Split by comma and create a dict with cleaned values
        items = [item.strip() for item in labels_str.split(",") if item.strip()]
        if not items:
            return None

        # Convert to dict format - use numeric keys
        labels_dict = {str(i): item for i, item in enumerate(items)}
        return _json.dumps(labels_dict)

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
