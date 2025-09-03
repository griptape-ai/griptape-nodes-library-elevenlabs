from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode


class ElevenLabsListVoices(DataNode):
    """List up to 100 voices in the user's ElevenLabs account and display 10 per page.

    UI per-slot (1..10):
    - voice_id_i (OUTPUT str)
    - name_i (PROPERTY str, display-only)
    - preview_i (OUTPUT AudioUrlArtifact) using preview_url directly
    """

    API_KEY_ENV_VAR: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    PAGE_SIZE: int = 10
    FETCH_LIMIT: int = 100

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "List account voices (10 per page) with IDs, names, and preview players."

        # Pagination control
        self.add_parameter(
            Parameter(
                name="page",
                input_types=["int"],
                type="int",
                default_value=1,
                tooltip="Page to display (1..N)",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={
                    "display_name": "Page",
                    "className": "gt-select",
                    "data": {"choices": [["Page 1", 1]]},
                },
            )
        )

        # Internal flag to control initial visibility
        self.add_parameter(
            Parameter(
                name="loaded",
                input_types=["bool"],
                type="bool",
                default_value=False,
                tooltip="Internal flag to reveal results after first load.",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"hide_property": True},
            )
        )

        # Outputs per slot (hidden until first successful run)
        for i in range(1, 11):
            self.add_parameter(
                Parameter(
                    name=f"voice_id_{i}",
                    output_type="str",
                    type="str",
                    tooltip=f"Voice ID #{i}",
                    allowed_modes={ParameterMode.OUTPUT},
                    ui_options={"display_name": f"Voice ID {i}", "hide_property": True},
                )
            )
            self.add_parameter(
                Parameter(
                    name=f"name_{i}",
                    input_types=["str"],
                    type="str",
                    tooltip=f"Name #{i}",
                    allowed_modes={ParameterMode.PROPERTY},
                    ui_options={"display_name": f"Name {i}", "disabled": True, "hide_property": True},
                )
            )
            self.add_parameter(
                Parameter(
                    name=f"preview_{i}",
                    output_type="AudioUrlArtifact",
                    type="AudioArtifact",
                    tooltip=f"Preview #{i}",
                    allowed_modes={ParameterMode.OUTPUT},
                    ui_options={"display_name": f"Sample {i}", "expander": True, "pulse_on_run": True, "hide_property": True},
                )
            )

        # Optional: total pages for information (not required to wire)
        self.add_parameter(
            Parameter(
                name="total_pages",
                output_type="int",
                type="int",
                tooltip="Total pages calculated from fetched voices.",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Total Pages", "hide_property": True},
            )
        )

        # Explicitly hide all per-slot params and total_pages so no ports/labels render until run
        try:
            for i in range(1, 11):
                self.hide_parameter_by_name(f"voice_id_{i}")
                self.hide_parameter_by_name(f"name_{i}")
                self.hide_parameter_by_name(f"preview_{i}")
            self.hide_parameter_by_name("total_pages")
        except Exception:
            pass

    # Re-run when page changes; hide results while reloading
    def after_value_set(self, parameter: Parameter, value: Any, modified_parameters_set: set[str]) -> None:  # type: ignore[override]
        try:
            if parameter.name == "page":
                # Hide outputs while the next run repopulates
                try:
                    self.publish_update_to_parameter("loaded", False)
                except Exception:
                    pass
                # Clamp page to sane positive integer in case of manual edits
                try:
                    v = int(value)
                    if v < 1:
                        v = 1
                        self.publish_update_to_parameter("page", v)
                except Exception:
                    pass
        except Exception:
            pass

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
        page: int = int(self.get_parameter_value("page") or 1)

        api_key: Optional[str] = getattr(self, "_resolved_api_key", None)
        if not api_key:
            try:
                api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)
            except Exception:
                api_key = os.environ.get(self.API_KEY_ENV_VAR)
        if not api_key:
            raise RuntimeError("Missing ELEVEN_LABS_API_KEY. Set it in system config or environment.")

        try:
            from elevenlabs import ElevenLabs  # type: ignore
        except Exception as e:
            raise ImportError("elevenlabs package not installed. Add 'elevenlabs' to library dependencies.") from e

        client = ElevenLabs(api_key=api_key)

        # Fetch up to 100 voices (no local cache persisted; every run pulls fresh)
        voices_resp = client.voices.search(include_total_count=True, page_size=self.FETCH_LIMIT)  # type: ignore[attr-defined]

        # Normalize result
        if hasattr(voices_resp, "model_dump"):
            data = voices_resp.model_dump()  # type: ignore[attr-defined]
        elif hasattr(voices_resp, "to_dict"):
            data = voices_resp.to_dict()  # type: ignore[attr-defined]
        elif isinstance(voices_resp, dict):
            data = voices_resp
        else:
            data = {k: getattr(voices_resp, k) for k in dir(voices_resp) if not k.startswith("_") and not callable(getattr(voices_resp, k))}

        voices = data.get("voices") or []
        total = len(voices)
        total_pages = max(1, math.ceil(min(total, self.FETCH_LIMIT) / self.PAGE_SIZE))

        # Clamp page
        page = max(1, min(page, total_pages))
        start = (page - 1) * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_items = voices[start:end]

        # Clear then hide all slots before repopulating
        for i in range(1, 11):
            self.parameter_output_values[f"voice_id_{i}"] = None
            self.parameter_output_values[f"name_{i}"] = ""
            self.parameter_output_values[f"preview_{i}"] = None
            try:
                self.hide_parameter_by_name(f"voice_id_{i}")
                self.hide_parameter_by_name(f"name_{i}")
                self.hide_parameter_by_name(f"preview_{i}")
            except Exception:
                pass

        # Populate current page and reveal populated slots
        for idx, v in enumerate(page_items, start=1):
            if idx > 10:
                break
            vid = v.get("voice_id") if isinstance(v, dict) else getattr(v, "voice_id", None)
            name = v.get("name") if isinstance(v, dict) else getattr(v, "name", None)
            preview_url = v.get("preview_url") if isinstance(v, dict) else getattr(v, "preview_url", None)

            id_param = f"voice_id_{idx}"
            name_param = f"name_{idx}"
            prev_param = f"preview_{idx}"

            self.parameter_output_values[id_param] = vid
            self.parameter_output_values[name_param] = name or ""
            try:
                from griptape.artifacts import AudioUrlArtifact  # type: ignore
                if preview_url:
                    self.parameter_output_values[prev_param] = AudioUrlArtifact(value=str(preview_url))
            except Exception:
                self.parameter_output_values[prev_param] = None

            try:
                self.show_parameter_by_name(id_param)
                self.show_parameter_by_name(name_param)
                self.show_parameter_by_name(prev_param)
            except Exception:
                pass

        # Set total pages for UI and reveal it
        self.parameter_output_values["total_pages"] = total_pages
        try:
            self.show_parameter_by_name("total_pages")
        except Exception:
            pass

        # Update the page dropdown choices to 1..total_pages
        try:
            choices = [[f"Page {i}", i] for i in range(1, total_pages + 1)]
            self.publish_update_to_parameter("page", page)
            try:
                self.publish_update_to_parameter("page", {"__ui_options__": {"data": {"choices": choices}}})
            except Exception:
                pass
        except Exception:
            pass

        # Mark loaded so UI shows the slots
        try:
            self.publish_update_to_parameter("loaded", True)
        except Exception:
            pass


