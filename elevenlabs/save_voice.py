from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
from urllib.request import urlopen

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode


class ElevenLabsSaveVoice(DataNode):
    """Create an ElevenLabs voice from a selected preview (generated_voice_id).

    Inputs:
    - generated_voice_id (str): From Design Voice node (preview_audio_1/2/3 outputs)
    - voice_name (str): Name for the created voice
    - voice_description (str): 20–1000 chars
    - labels (dict): Optional key/value labels

    Outputs:
    - voice (json): Full API response
    - voice_id (str)
    - preview_audio (AudioUrlArtifact): Playable preview (downloaded and saved as static if possible)
    """

    API_KEY_ENV_VAR: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Save a designed voice by creating it from a generated preview id."

        # Inputs / properties
        self.add_parameter(
            Parameter(
                name="generated_voice_id",
                input_types=["str"],
                type="str",
                tooltip="Connect from Design Voice preview output (voice id).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="voice_name",
                input_types=["str"],
                type="str",
                tooltip="Name for the created voice.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="voice_description",
                input_types=["str"],
                type="str",
                tooltip="20–1000 chars description for the created voice.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="labels",
                input_types=["dict"],
                type="dict",
                default_value=None,
                tooltip="Optional labels for the voice (key/value).",
                allowed_modes={ParameterMode.PROPERTY},
            )
        )

        # Outputs
        self.add_parameter(
            Parameter(
                name="voice",
                output_type="json",
                type="dict",
                tooltip="Created voice metadata (JSON).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Voice JSON", "hide_property": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="voice_id",
                output_type="str",
                type="str",
                tooltip="The ID of the created voice.",
                allowed_modes={ParameterMode.OUTPUT},
            )
        )
        self.add_parameter(
            Parameter(
                name="preview_audio",
                output_type="AudioUrlArtifact",
                type="AudioArtifact",
                tooltip="Preview audio for the created voice.",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Preview Audio", "expander": True, "pulse_on_run": True},
            )
        )

    def process(self) -> Any:
        # Resolve and cache API key before scheduling background work
        try:
            self._resolved_api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]
        except Exception:
            self._resolved_api_key = None  # type: ignore[attr-defined]
        if not getattr(self, "_resolved_api_key", None):  # type: ignore[attr-defined]
            self._resolved_api_key = os.environ.get(self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]

        yield lambda: self._run()

    def _run(self) -> None:
        # Collect inputs
        gen_id: Optional[str] = self.get_parameter_value("generated_voice_id")
        voice_name: Optional[str] = self.get_parameter_value("voice_name")
        voice_description: Optional[str] = self.get_parameter_value("voice_description")
        labels: Optional[Dict[str, str]] = self.get_parameter_value("labels")

        # Basic validation
        if not gen_id:
            raise ValueError("generated_voice_id is required.")
        if not voice_name:
            raise ValueError("voice_name is required.")
        if not voice_description or len(voice_description) < 20 or len(voice_description) > 1000:
            raise ValueError("voice_description must be between 20 and 1000 characters.")

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

        # Call API
        try:
            from elevenlabs import ElevenLabs
        except Exception as e:
            raise ImportError("elevenlabs package not installed. Add 'elevenlabs' to library dependencies.") from e

        client = ElevenLabs(api_key=api_key)

        self._logger.info(
            "SaveVoice request: gen_id=%s, name=%s, desc_len=%s, labels=%s",
            gen_id,
            voice_name,
            len(voice_description),
            bool(labels),
        )

        response = client.text_to_voice.create(
            voice_name=voice_name,
            voice_description=voice_description,
            generated_voice_id=gen_id,
            labels=labels,
        )

        # Normalize response to dict
        voice_dict: Dict[str, Any]
        if isinstance(response, dict):
            voice_dict = response
        elif hasattr(response, "model_dump"):
            voice_dict = response.model_dump()  # type: ignore[attr-defined]
        elif hasattr(response, "to_dict"):
            voice_dict = response.to_dict()  # type: ignore[attr-defined]
        else:
            voice_dict = {k: getattr(response, k) for k in dir(response) if not k.startswith("_") and not callable(getattr(response, k))}

        voice_id = voice_dict.get("voice_id")
        preview_url = voice_dict.get("preview_url")
        if not preview_url:
            # Try nested locations if top-level preview_url missing
            try:
                verified_langs = voice_dict.get("verified_languages") or []
                if verified_langs and isinstance(verified_langs, list):
                    preview_url = verified_langs[0].get("preview_url")
            except Exception:
                preview_url = None

        self.parameter_output_values["voice"] = voice_dict
        self.parameter_output_values["voice_id"] = voice_id

        # Attempt to save preview to static files for reliable playback
        preview_artifact = None
        if preview_url:
            try:
                from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes  # type: ignore
                from griptape.artifacts import AudioUrlArtifact  # type: ignore

                data = urlopen(preview_url, timeout=15).read()
                filename = f"elevenlabs_{voice_id or 'voice'}_preview.mp3"
                static_url = GriptapeNodes.StaticFilesManager().save_static_file(data, filename)
                preview_artifact = AudioUrlArtifact(value=static_url)
            except Exception:
                try:
                    from griptape.artifacts import AudioUrlArtifact  # type: ignore

                    preview_artifact = AudioUrlArtifact(value=preview_url)
                except Exception:
                    preview_artifact = None

        self.parameter_output_values["preview_audio"] = preview_artifact


