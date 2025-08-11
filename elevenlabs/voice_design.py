from __future__ import annotations

import base64
import os
import logging
import unicodedata
from uuid import uuid4
from typing import Any, Dict, List, Optional

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterMessage
from griptape_nodes.exe_types.node_types import DataNode
"""
Audio playback: we'll attempt to import dict_to_audio_url_artifact lazily in process()
to avoid a hard dependency at import time.
"""


class ElevenLabsDesignVoice(DataNode):
    """Design a voice from a descriptive prompt using ElevenLabs and return playable previews.

    Outputs both raw preview metadata and a list of AudioUrlArtifacts for inline playback.
    """

    SERVICE_NAME: str = "ElevenLabs"
    API_KEY_ENV_VAR: str = "ELEVEN_LABS_API_KEY"

    # Use engine logger so messages appear in Griptape logs panel
    _logger = logging.getLogger("griptape_nodes")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Design a voice from a prompt and preview the results."

        # Inputs / Properties
        # Prompt (used as ElevenLabs voice_description)
        self.add_parameter(
            Parameter(
                name="prompt",
                input_types=["str"],
                type="str",
                tooltip="20-1000 chars. Describe timbre, accent, age, style.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "e.g., a raspy cowboy voice with a heavy accent",
                },
            )
        )

        # model_id is fixed in code (eleven_multilingual_ttv_v2)

        # Optional preview text for the API (distinct from the prompt above)
        self.add_parameter(
            Parameter(
                name="preview_text",
                input_types=["str"],
                type="str",
                default_value=None,
                tooltip="Optional preview text (100-1000 chars). If omitted and auto_generate_text is false, service may return only IDs.",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Place your text here",
                    "hide_when": {"auto_generate_text": [True]},
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="auto_generate_text",
                input_types=["bool"],
                type="bool",
                default_value=True,
                tooltip="Automatically generate preview text.",
                allowed_modes={ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            Parameter(
                name="output_format",
                input_types=["str"],
                type="str",
                default_value="mp3_44100_192",
                tooltip="codec_sample_rate_bitrate (e.g., mp3_44100_192, mp3_22050_32, pcm_44100_16).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={
                    "className": "gt-select",
                    "data": {
                        "choices": [
                            ["MP3 44.1kHz 192kbps", "mp3_44100_192"],
                            ["MP3 22.05kHz 32kbps", "mp3_22050_32"],
                            ["WAV/PCM 44.1kHz 16bit", "pcm_44100_16"],
                        ]
                    }
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="loudness",
                input_types=["float", "int"],
                type="float",
                default_value=0.5,
                tooltip="Volume level (-1 to 1). 0 ~ -24 LUFS.",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"slider": {"min_val": -1.0, "max_val": 1.0, "step": 0.05}},
            )
        )

        self.add_parameter(
            Parameter(
                name="seed",
                input_types=["int", "none"],
                type="int",
                default_value=None,
                tooltip="Deterministic seed (0..2,147,483,647).",
                allowed_modes={ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            Parameter(
                name="guidance_scale",
                input_types=["float", "int"],
                type="float",
                default_value=5.0,
                tooltip="Prompt adherence (0..100). Higher = more literal.",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"slider": {"min_val": 0.0, "max_val": 100.0, "step": 0.5}},
            )
        )

        self.add_parameter(
            Parameter(
                name="quality",
                input_types=["float", "int", "none"],
                type="float",
                default_value=None,
                tooltip="Quality-vs-variety (-1..1).",
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={"slider": {"min_val": -1.0, "max_val": 1.0, "step": 0.05}},
            )
        )

        self.add_parameter(
            Parameter(
                name="reference_audio",
                input_types=["AudioArtifact", "AudioUrlArtifact", "str"],
                type="AudioArtifact",
                tooltip="Optional base64 data URL or audio to bias design (v3 only).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"clickable_file_browser": True, "expander": True},
            )
        )

        # No explicit status parameter; keep UI minimal

        # Outputs
        self.add_parameter(
            Parameter(
                name="preview_metadata",
                output_type="json",
                type="dict",
                tooltip="Preview metadata (JSON: text, previews, counts).",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Preview Metadata", "hide_property": True}
            )
        )

        self.add_parameter(
            Parameter(
                name="preview_audios",
                output_type="list[AudioUrlArtifact]",
                type="list[AudioArtifact]",
                tooltip="Playable audio previews.",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"display_name": "Preview Audios","expander": True, "pulse_on_run": True},
            )
        )

        # Individual preview outputs (since API returns 3): Voice ID followed by Sample
        for i in range(1, 4):
            self.add_parameter(
                Parameter(
                    name=f"voice_id_{i}",
                    output_type="str",
                    type="str",
                    tooltip=f"Voice ID for preview #{i}",
                    allowed_modes={ParameterMode.OUTPUT},
                    ui_options={"display_name": f"Voice ID {i}", "hide_property": True},
                )
            )
            self.add_parameter(
                Parameter(
                    name=f"preview_audio_{i}",
                    output_type="AudioUrlArtifact",
                    type="AudioArtifact",
                    tooltip=f"Preview audio #{i}",
                    allowed_modes={ParameterMode.OUTPUT},
                    ui_options={"display_name": f"Sample {i}", "expander": True},
                )
            )

    def _get_reference_audio_b64(self, ref: Any) -> Optional[str]:
        if ref is None:
            return None
        # Accept data URLs directly
        if isinstance(ref, str):
            if ref.startswith("data:audio") and "," in ref:
                return ref.split(",", 1)[1]
            # If it's already base64 without header, make a best-effort validation
            try:
                # Validate base64 (ignore whitespace)
                base64.b64decode(ref, validate=True)
                return ref
            except Exception:
                return None
        # If dict artifact-like with uri/url
        if isinstance(ref, dict):
            uri = ref.get("uri") or ref.get("url")
            if isinstance(uri, str) and uri.startswith("data:audio") and "," in uri:
                return uri.split(",", 1)[1]
        return None

    def process(self) -> Any:
        # Resolve API key before scheduling to avoid context issues
        # Try primary key from system config
        try:
            self._resolved_api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]
        except Exception:
            self._resolved_api_key = None  # type: ignore[attr-defined]
        # Env fallbacks
        if not getattr(self, "_resolved_api_key", None):  # type: ignore[attr-defined]
            self._resolved_api_key = os.environ.get(self.API_KEY_ENV_VAR)  # type: ignore[attr-defined]
        # Non-blocking pattern: schedule _run
        yield lambda: self._run()

    def _run(self):
        # Local helper: coerce text to ASCII-only to satisfy strict header encoders in some envs
        def _to_ascii(s: Optional[str]) -> Optional[str]:
            if s is None:
                return None
            try:
                return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
            except Exception:
                try:
                    return s.encode("ascii", "ignore").decode("ascii")
                except Exception:
                    return s
        # Validate inputs
        # Use the 'prompt' parameter for voice_description
        description: Optional[str] = self.get_parameter_value("prompt")
        if not description:
            self.parameter_output_values["previews"] = []
            self.parameter_output_values["preview_audios"] = []
            raise ValueError("voice_description is required.")

        # Enforce API min/max length with smart coercion
        if len(description) < 20:
            self._logger.info("voice_description < 20 chars; auto-expanding to meet API minimum…")
            fallback = f"{description}. Natural, clear, expressive voice."
            while len(fallback) < 20:
                fallback += " voice"
            description = fallback[:1000]
        elif len(description) > 1000:
            self._logger.info("voice_description > 1000 chars; truncating to max allowed…")
            description = description[:1000]

        # Fixed model; no user selection
        model_id: str = "eleven_multilingual_ttv_v2"
        # The prompt is the voice_description; preview_text is optional API text param
        preview_text: Optional[str] = self.get_parameter_value("preview_text")
        auto_generate_text: bool = bool(self.get_parameter_value("auto_generate_text"))
        output_format: str = self.get_parameter_value("output_format") or "mp3_44100_192"
        loudness: float = float(self.get_parameter_value("loudness") if self.get_parameter_value("loudness") is not None else 0.5)
        seed: Optional[int] = self.get_parameter_value("seed")
        guidance_scale: float = float(self.get_parameter_value("guidance_scale") if self.get_parameter_value("guidance_scale") is not None else 5.0)
        quality: Optional[float] = self.get_parameter_value("quality")
        reference_audio = self.get_parameter_value("reference_audio")

        # Only include preview_text if valid; otherwise ignore
        if preview_text is not None:
            if len(preview_text) == 0:
                preview_text = None
            elif len(preview_text) < 100:
                self._logger.info("preview_text < 100 chars; ignoring.")
                preview_text = None
            elif len(preview_text) > 1000:
                self._logger.info("preview_text > 1000 chars; truncating to max allowed…")
                preview_text = preview_text[:1000]

        # Resolve API key from central config or environment (no service-specific lookups)
        # Prefer API key resolved in process()
        api_key: Optional[str] = getattr(self, "_resolved_api_key", None)
        if not api_key:
            try:
                api_key = self.get_config_value(value=self.API_KEY_ENV_VAR)
            except Exception:
                api_key = None
        if not api_key:
            api_key = os.environ.get(self.API_KEY_ENV_VAR)

        if not api_key:
            self.parameter_output_values["previews"] = []
            self.parameter_output_values["preview_audios"] = []
            raise RuntimeError("Missing ELEVEN_LABS_API_KEY. Set it in system config or environment.")

        try:
            from elevenlabs import ElevenLabs  # Optional dep until library installs
        except Exception as e:
            self.parameter_output_values["previews"] = []
            self.parameter_output_values["preview_audios"] = []
            raise ImportError(
                "elevenlabs package not installed. Add 'elevenlabs' to library dependencies."
            ) from e

        # Ensure API key is ASCII-only to avoid header encoding issues in some envs
        api_key_ascii = (_to_ascii(api_key) if isinstance(api_key, str) else api_key)  # type: ignore[arg-type]
        client = ElevenLabs(api_key=api_key_ascii)

        # Sanitize strings to ASCII to avoid header encoding issues in some clients/envs
        def _to_ascii(s: Optional[str]) -> Optional[str]:
            if s is None:
                return None
            try:
                return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
            except Exception:
                return s.encode("ascii", "ignore").decode("ascii")

        safe_description = _to_ascii(description) or description
        safe_preview_text = _to_ascii(preview_text) if preview_text is not None else None

        payload: Dict[str, Any] = {
            "voice_description": safe_description,
            "model_id": model_id,
            "loudness": loudness,
            "seed": seed,
            "guidance_scale": guidance_scale,
            "quality": quality,
        }
        # API requires either text or auto_generate_text true; respect UI value
        if safe_preview_text is not None:
            payload["text"] = safe_preview_text
        elif auto_generate_text:
            payload["auto_generate_text"] = True
        else:
            raise ValueError("Provide 'preview_text' (>=100 chars) or enable 'auto_generate_text'.")
        # no-op; handled above

        # Only supported on ttv_v3
        ref_b64 = self._get_reference_audio_b64(reference_audio)
        if ref_b64 and model_id == "eleven_ttv_v3":
            payload["reference_audio_base64"] = ref_b64

        # Log request summary (without dumping full text)
        try:
            self._logger.info(
                "DesignVoice request: model=%s, output_format=%s, has_preview_text=%s, auto_generate_text=%s, guidance=%s, loudness=%s, seed=%s, quality=%s",
                model_id,
                output_format,
                bool(preview_text),
                payload.get("auto_generate_text", False),
                guidance_scale,
                loudness,
                seed,
                quality,
            )
        except Exception:
            pass

        try:
            # Some SDKs accept output_format as arg; if not, the client may ignore it gracefully.
            response = client.text_to_voice.design(output_format=output_format, **payload)
        except TypeError:
            # Fall back if SDK version doesn't accept output_format in method signature
            response = client.text_to_voice.design(**payload)
        except UnicodeEncodeError as e_hdr:
            # Fallback to direct HTTP call with ASCII-safe headers
            try:
                import httpx  # type: ignore

                base_url = "https://api.elevenlabs.io"
                url = f"{base_url}/v1/text-to-voice/design"
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "xi-api-key": str(api_key_ascii),
                }
                # Force ASCII-only headers
                def _ascii_headers(h: Dict[str, Any]) -> Dict[str, str]:
                    out: Dict[str, str] = {}
                    for k, v in h.items():
                        ks = _to_ascii(str(k)) or str(k)
                        vs = _to_ascii(str(v)) or str(v)
                        out[ks] = vs
                    return out
                headers = _ascii_headers(headers)
                params = {"output_format": output_format}
                with httpx.Client(timeout=30) as hc:
                    r = hc.post(url, headers=headers, params=params, json=payload)
                r.raise_for_status()
                response = r.json()
                self._logger.info("Used direct HTTP fallback for design due to header encoding issue: %s", e_hdr)
            except Exception as e_http:
                raise e_http

        previews = []
        preview_artifacts = []

        # Response shape per docs:
        # {
        #   "previews": [{"audio_base_64": str, "generated_voice_id": str, "media_type": str, "duration_secs": float}],
        #   "text": str
        # }
        # Normalize response
        resp_dict: Dict[str, Any] = {}
        try:
            if isinstance(response, dict):
                resp_dict = response
            elif hasattr(response, "model_dump"):
                resp_dict = response.model_dump()  # type: ignore[attr-defined]
            elif hasattr(response, "to_dict"):
                resp_dict = response.to_dict()  # type: ignore[attr-defined]
            else:
                # Best-effort: collect public attributes
                resp_dict = {k: getattr(response, k) for k in dir(response) if not k.startswith("_") and not callable(getattr(response, k))}
        except Exception:
            resp_dict = {}

        previews_list = resp_dict.get("previews") or getattr(response, "previews", [])  # type: ignore[attr-defined]
        used_text = resp_dict.get("text") or getattr(response, "text", None)  # type: ignore[attr-defined]

        # Log response summary
        try:
            self._logger.info(
                "DesignVoice response: previews=%s, preview_text_len=%s",
                len(previews_list) if isinstance(previews_list, list) else 0,
                len(used_text) if isinstance(used_text, str) else None,
            )
            if isinstance(previews_list, list) and previews_list:
                p0 = previews_list[0]
                keys = list(p0.keys()) if isinstance(p0, dict) else [k for k in dir(p0) if not k.startswith("_")][:10]
                self._logger.debug("First preview keys: %s", keys)
        except Exception:
            pass

        for i, p in enumerate(previews_list or []):
            # Support both SDK object and dict
            audio_b64 = (
                (getattr(p, "audio_base_64", None) if not isinstance(p, dict) else p.get("audio_base_64"))
                or (getattr(p, "audio_base64", None) if not isinstance(p, dict) else p.get("audio_base64"))
            )
            gen_id = (getattr(p, "generated_voice_id", None) if not isinstance(p, dict) else p.get("generated_voice_id"))
            media_type = (
                (getattr(p, "media_type", None) if not isinstance(p, dict) else p.get("media_type"))
                or "audio/mpeg"
            )
            duration = (getattr(p, "duration_secs", None) if not isinstance(p, dict) else p.get("duration_secs"))

            # Per-preview logging (truncated)
            try:
                self._logger.info(
                    "Preview[%s]: has_b64=%s b64_len=%s gen_id=%s media_type=%s duration=%s",
                    i,
                    bool(audio_b64),
                    len(audio_b64) if isinstance(audio_b64, str) else None,
                    gen_id,
                    media_type,
                    duration,
                )
                if isinstance(audio_b64, str):
                    self._logger.debug("Preview[%s] b64_head=%s", i, audio_b64[:60])
            except Exception:
                pass

            audio_url = None
            if audio_b64:
                # Prefer saving to static files for reliable playback
                mime = media_type if isinstance(media_type, str) else "audio/mpeg"
                ext = "mp3"
                if isinstance(mime, str):
                    if "wav" in mime:
                        ext = "wav"
                    elif "ogg" in mime:
                        ext = "ogg"
                    elif "mpeg" in mime or "mp3" in mime:
                        ext = "mp3"
                try:
                    from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes  # type: ignore
                    from griptape.artifacts import AudioUrlArtifact  # type: ignore

                    audio_bytes = base64.b64decode(audio_b64)
                    file_stub = gen_id or f"preview_{i+1}_{uuid4().hex[:8]}"
                    filename = f"elevenlabs_{file_stub}.{ext}"
                    static_url = GriptapeNodes.StaticFilesManager().save_static_file(audio_bytes, filename)
                    audio_artifact = AudioUrlArtifact(value=static_url)
                    preview_artifacts.append(audio_artifact)
                    audio_url = static_url
                except Exception as e_save:
                    # Fallbacks: data URL path
                    try:
                        from griptape.artifacts import AudioUrlArtifact  # type: ignore

                        data_url = f"data:{mime};base64,{audio_b64}"
                        audio_artifact = AudioUrlArtifact(value=data_url)
                        preview_artifacts.append(audio_artifact)
                        audio_url = data_url
                        self._logger.info("Static save failed; used data URL for preview %s: %s", i, e_save)
                    except Exception as e_art2:
                        # Last resort: try helper with 'url' key; else leave raw info
                        try:
                            from griptape_nodes_library.utils.audio_utils import dict_to_audio_url_artifact  # type: ignore
                            data_url = f"data:{mime};base64,{audio_b64}"
                            audio_dict = {"url": data_url}
                            audio_artifact = dict_to_audio_url_artifact(audio_dict)
                            preview_artifacts.append(audio_artifact)
                            audio_url = data_url
                        except Exception:
                            self._logger.info("All conversions failed for preview %s: %s", i, e_art2)

            preview_entry = {
                "generated_voice_id": gen_id,
                "media_type": media_type,
                "duration_secs": duration,
                "text": used_text,
                "audio_url": audio_url,
            }
            previews.append(preview_entry)

            # Populate paired outputs: voice_id_N and preview_audio_N
            id_slot = f"voice_id_{i + 1}"
            audio_slot = f"preview_audio_{i + 1}"
            self.parameter_output_values[id_slot] = gen_id
            try:
                if i < len(preview_artifacts):
                    self.publish_update_to_parameter(audio_slot, preview_artifacts[i])
            except Exception:
                pass

        # JSON metadata for convenient Display JSON rendering
        self.parameter_output_values["preview_metadata"] = {
            "text": used_text,
            "count": len(previews),
            "previews": previews,
        }
        self.parameter_output_values["preview_audios"] = preview_artifacts
        # Populate individual outputs if present
        for idx in range(3):
            key = f"preview_audio_{idx + 1}"
            self.parameter_output_values[key] = preview_artifacts[idx] if idx < len(preview_artifacts) else None
        try:
            self._logger.info("Built %s AudioUrlArtifact(s) from %s preview(s)", len(preview_artifacts), len(previews))
        except Exception:
            pass
        # done



