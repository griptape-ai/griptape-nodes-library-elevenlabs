from __future__ import annotations

import base64
import json as _json
import logging
import mimetypes
from typing import Any
from urllib.parse import urlparse

import httpx
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact
from griptape.artifacts.video_url_artifact import VideoUrlArtifact
from griptape_nodes.exe_types.core_types import Parameter, ParameterList, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.exe_types.param_components.project_file_parameter import ProjectFileParameter
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.files.file import File
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.multi_options import MultiOptions
from griptape_nodes.traits.options import Options

OUTPUT_FORMATS = [
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


class ElevenLabsVideoToMusic(DataNode):
    """Generate background music for one or more videos using the ElevenLabs Video to Music API.

    Inputs:
    - videos: Up to 10 videos (200 MB and 600 seconds combined). Multiple videos are combined in order.
    - description: Optional guidance for the music (<=4100 chars).
    - tags: Optional style tags, such as upbeat or cinematic (max 10).
    - add_sfx: If true, include sound-effect cues detected in the video.
    - use_audio_as_reference: If true, use the video's own audio (genre, BPM, mood, arc) as a reference.
    - sign_with_c2pa: If true, sign the output with C2PA (MP3 output only).
    - output_format: codec_sample_rate_bitrate. Default mp3_44100_128.

    Outputs:
    - audio (AudioUrlArtifact): Generated music as a playable URL.
    """

    API_KEY_NAME: str = "ELEVEN_LABS_API_KEY"
    _logger = logging.getLogger("griptape_nodes")

    MAX_VIDEOS = 10
    MAX_TOTAL_BYTES = 200 * 1024 * 1024
    MAX_DESCRIPTION_LENGTH = 4100
    MAX_TAGS = 10

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ElevenLabs.Audio"
        self.description = "Generate background music for a video using the ElevenLabs Video to Music API."

        self.add_parameter(
            ParameterList(
                name="videos",
                tooltip=(
                    "**Video(s) to score**\n\n"
                    "- Up to 10 videos, 200 MB and 600 seconds combined\n"
                    "- Multiple videos are combined in the order given\n"
                    "- Combining many videos can slow the request down. Joining them first is recommended\n\n"
                    "[Video to Music guide](https://elevenlabs.io/docs/api-reference/music/video-to-music)"
                ),
                input_types=["VideoUrlArtifact", "VideoArtifact"],
                type="VideoUrlArtifact",
                allowed_modes={ParameterMode.INPUT},
                default_value=[],
                ui_options={"display_name": "Video(s)", "expander": True, "hide_property": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="description",
                input_types=["str"],
                type="str",
                default_value=None,
                tooltip=f"Optional guidance for the music (<={self.MAX_DESCRIPTION_LENGTH} chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "display_name": "Description",
                    "placeholder_text": "e.g., Warm acoustic guitar that builds to an uplifting finish",
                },
            )
        )
        self.add_parameter(
            Parameter(
                name="tags",
                default_value=None,
                tooltip=f"Optional style tags (max {self.MAX_TAGS}). Type your own to add more.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                type="list",
                traits={
                    MultiOptions(
                        choices=["upbeat", "cinematic", "calm", "dramatic", "energetic", "ambient"],
                        allow_user_created_options=True,
                    )
                },
            )
        )
        self.add_parameter(
            ParameterBool(
                name="add_sfx",
                default_value=False,
                tooltip="If true, include sound-effect cues detected in the video.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Add Sound Effects"},
            )
        )
        self.add_parameter(
            ParameterBool(
                name="use_audio_as_reference",
                default_value=False,
                tooltip="If true, analyze the video's own audio and use its genre, BPM, instrumentation, mood and arc as a reference.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Audio as Reference"},
            )
        )
        self.add_parameter(
            ParameterBool(
                name="sign_with_c2pa",
                default_value=False,
                tooltip="If true, sign the output with C2PA. Applies to MP3 output only.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Sign with C2PA"},
            )
        )
        self.add_parameter(
            Parameter(
                name="output_format",
                input_types=["str"],
                type="str",
                default_value="mp3_44100_128",
                tooltip="Audio output format. MP3 at 192 kbps needs a Creator tier or higher, and PCM at 44.1 kHz needs Pro.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=OUTPUT_FORMATS)},
                ui_options={"display_name": "Output Format"},
            )
        )

        self._output_file = ProjectFileParameter(
            node=self, name="output_file", default_filename="elevenlabs_video_music.mp3"
        )
        self._output_file.add_parameter()

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
        videos_input = self.get_parameter_value("videos")
        description: str | None = self.get_parameter_value("description")
        tags = self._normalize_tags(self.get_parameter_value("tags"))
        add_sfx = bool(self.get_parameter_value("add_sfx"))
        use_audio_as_reference = bool(self.get_parameter_value("use_audio_as_reference"))
        sign_with_c2pa = bool(self.get_parameter_value("sign_with_c2pa"))
        output_format: str = self.get_parameter_value("output_format") or "mp3_44100_128"

        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            error_msg = f"{self.name} is missing {self.API_KEY_NAME}. Ensure it's set in the environment/config."
            raise RuntimeError(error_msg)

        video_sources = self._collect_video_sources(videos_input)
        if not video_sources:
            error_msg = f"{self.name}: At least one video is required."
            raise ValueError(error_msg)
        if len(video_sources) > self.MAX_VIDEOS:
            error_msg = f"{self.name}: At most {self.MAX_VIDEOS} videos are allowed, got {len(video_sources)}."
            raise ValueError(error_msg)

        files = self._load_videos(video_sources)

        data: dict[str, Any] = {}
        if description:
            data["description"] = description[: self.MAX_DESCRIPTION_LENGTH]
        if tags:
            data["tags"] = tags
        if add_sfx:
            data["add_sfx"] = "true"
        if use_audio_as_reference:
            data["use_audio_as_reference"] = "true"
        if sign_with_c2pa:
            data["sign_with_c2pa"] = "true"

        url = f"https://api.elevenlabs.io/v1/music/video-to-music?output_format={output_format}"
        headers = {"xi-api-key": api_key}

        self._logger.info(
            "VideoToMusic request: videos=%s, description_len=%s, tags=%s, add_sfx=%s, "
            "use_audio_as_reference=%s, sign_with_c2pa=%s, output_format=%s",
            len(files),
            len(description) if description else None,
            tags,
            add_sfx,
            use_audio_as_reference,
            sign_with_c2pa,
            output_format,
        )

        try:
            with httpx.Client(timeout=600.0) as client:
                response = client.post(url, data=data, files=files, headers=headers)
                response.raise_for_status()
                resp_bytes = response.content
        except httpx.HTTPStatusError as e:
            self._logger.info("VideoToMusic HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise RuntimeError(self._parse_error_response(e.response.text, e.response.status_code)) from e
        except Exception as e:
            self._logger.info("VideoToMusic HTTP failed: %s", e)
            error_msg = f"Request failed: {e}"
            raise RuntimeError(error_msg) from e

        self.parameter_output_values["audio"] = self._save_audio(resp_bytes, output_format)

    def _collect_video_sources(self, videos_input: Any) -> list[str]:
        """Return the location string of each connected video."""
        if not videos_input:
            return []
        items = videos_input if isinstance(videos_input, list) else [videos_input]
        sources: list[str] = []
        for item in items:
            if isinstance(item, VideoUrlArtifact):
                value = item.value
            elif isinstance(item, dict):
                value = item.get("value")
            elif isinstance(item, str):
                value = item
            else:
                value = getattr(item, "value", None)
            if isinstance(value, str) and value:
                sources.append(value)
        return sources

    def _load_videos(self, sources: list[str]) -> list[tuple[str, tuple[str, bytes, str]]]:
        """Read each video (URL, local path or macro path) into a multipart `videos` field."""
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        total_bytes = 0
        for index, source in enumerate(sources, start=1):
            try:
                content = File(source).read_bytes()
            except Exception as e:
                error_msg = f"{self.name}: Could not read video {index} ({source}): {e}"
                raise ValueError(error_msg) from e
            total_bytes += len(content)
            if total_bytes > self.MAX_TOTAL_BYTES:
                error_msg = f"{self.name}: Videos exceed the 200 MB combined limit."
                raise ValueError(error_msg)
            filename = self._filename_for(source, index)
            content_type = mimetypes.guess_type(filename)[0] or "video/mp4"
            files.append(("videos", (filename, content, content_type)))
        return files

    @staticmethod
    def _filename_for(source: str, index: int) -> str:
        suffix = ""
        name = urlparse(source).path.rsplit("/", 1)[-1]
        if "." in name:
            suffix = "." + name.rsplit(".", 1)[-1]
        return f"video_{index}{suffix or '.mp4'}"

    def _normalize_tags(self, tags: Any) -> list[str]:
        """Accept a list, a JSON list string, or comma-separated text."""
        if not tags:
            return []
        if isinstance(tags, str):
            try:
                parsed = _json.loads(tags)
            except (_json.JSONDecodeError, TypeError):
                parsed = [part for part in tags.split(",")]
            tags = parsed if isinstance(parsed, list) else [tags]
        cleaned = [str(tag).strip() for tag in tags if tag and str(tag).strip()]
        return cleaned[: self.MAX_TAGS]

    def _save_audio(self, resp_bytes: bytes, output_format: str) -> AudioUrlArtifact | None:
        if not resp_bytes:
            return None
        ext = "mp3"
        if output_format.startswith("pcm"):
            ext = "wav"
        elif output_format.startswith("opus"):
            ext = "opus"
        try:
            saved = self._output_file.build_file(default_filename=f"elevenlabs_video_music.{ext}").write_bytes(
                resp_bytes
            )
            return AudioUrlArtifact(value=saved.location, name=saved.location)
        except Exception as e_save:
            b64 = base64.b64encode(resp_bytes).decode("ascii")
            mime = "audio/wav" if ext == "wav" else "audio/ogg" if ext == "opus" else "audio/mpeg"
            self._logger.info("VideoToMusic file save failed; used data URL: %s", e_save)
            return AudioUrlArtifact(value=f"data:{mime};base64,{b64}", name="music")

    def _parse_error_response(self, response_text: str, status_code: int) -> str:
        """Extract a useful message from an API error response."""
        if status_code == 403:
            return (
                "Error: Video to Music needs a paid ElevenLabs subscription. "
                "If you have one, accept the Eleven Music terms at https://elevenlabs.io/music-terms."
            )
        try:
            error_data = _json.loads(response_text)
        except (_json.JSONDecodeError, TypeError):
            return f"API Error ({status_code}): {response_text[:200]}"

        detail = error_data.get("detail") if isinstance(error_data, dict) else None
        if isinstance(detail, dict):
            status = detail.get("status", "")
            message = detail.get("message", "")
            if status and message:
                return f"{status}: {message}"
            if message:
                return f"Error: {message}"
        elif isinstance(detail, str):
            return f"Error: {detail}"
        elif isinstance(detail, list) and detail:
            messages = [str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail]
            return f"Error: {'; '.join(messages)}"
        return f"API Error ({status_code}): {response_text[:200]}"
