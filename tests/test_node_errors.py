"""Failures reach the editor as NodeError. The HTTP layer is mocked, and the SDK nodes run the real SDK."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from griptape.artifacts.audio_artifact import AudioArtifact
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact
from griptape_nodes.exe_types.core_types import NodeError

import elevenlabs

FOLDER = Path(__file__).resolve().parents[1] / "elevenlabs"
KEY_PAGE = "https://elevenlabs.io/app/settings/api-keys"
SETTINGS = "#settings-secrets?filter=ELEVEN_LABS_API_KEY"
# The 401 body is what the live API returned for a made-up key. The 403 and 422 bodies are canned.
REFUSED = {
    "detail": {
        "type": "authentication_error",
        "code": "unauthorized",
        "message": "Invalid API key",
        "status": "invalid_api_key",
        "request_id": "req-1",
    }
}
FORBIDDEN = {"detail": {"status": "missing_permissions", "message": "The key lacks the music_generation permission."}}
TERMS = {"detail": {"status": "limited_access", "message": "Accept the terms at https://elevenlabs.io/music-terms"}}

NODES = {
    "clone_voice": "ElevenLabsCloneVoice",
    "generate_music": "ElevenLabsGenerateMusic",
    "list_voices": "ElevenLabsListVoices",
    "save_voice": "ElevenLabsSaveVoice",
    "sound_effects": "ElevenLabsSoundEffects",
    "text_to_speech": "ElevenLabsTextToSpeech",
    "video_to_music": "ElevenLabsVideoToMusic",
    "voice_changer": "ElevenLabsVoiceChanger",
    "voice_design": "ElevenLabsDesignVoice",
}


def load(file: str):
    """Load a node file the way the engine does: on its own, with only the library folder on sys.path."""
    spec = importlib.util.spec_from_file_location(f"{file}_under_test", FOLDER / f"{file}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make(file: str):
    return getattr(load(file), NODES[file])(name="Node")


class Secrets:
    key: str | None = "test-key"

    def get_secret(self, name, **_kwargs):
        return self.key


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    import elevenlabs_errors

    fake = Secrets()
    monkeypatch.setattr(elevenlabs_errors.GriptapeNodes, "SecretsManager", staticmethod(lambda: fake))
    return fake


def serve(monkeypatch, status=200, body=None, content=None, raises=None):
    """Answer every ElevenLabs request, from the node's httpx clients and from the SDK's."""

    def handler(request):
        if raises:
            raise raises
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)

    client, async_client, sdk = httpx.Client, httpx.AsyncClient, elevenlabs.ElevenLabs
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=transport, **{**kw, "timeout": None}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: async_client(transport=transport, **{**kw, "timeout": None}))
    monkeypatch.setattr(
        elevenlabs, "ElevenLabs", lambda api_key: sdk(api_key=api_key, httpx_client=client(transport=transport))
    )


def run_to_error(file, node, **inputs):
    for name, value in inputs.items():
        node.set_parameter_value(name, value)
    with pytest.raises(NodeError) as caught:
        node._run()
    return caught.value


@pytest.mark.parametrize("file", NODES)
def test_node_file_loads_the_way_the_engine_loads_it(file, monkeypatch):
    monkeypatch.setattr(sys, "path", [str(FOLDER), *sys.path])
    monkeypatch.delitem(sys.modules, "elevenlabs_errors", raising=False)
    assert make(file).name == "Node"


@pytest.mark.parametrize("file", NODES)
def test_a_missing_key_is_the_only_error(file, secrets):
    secrets.key = None
    errors = make(file).validate_before_node_run()
    assert errors is not None and len(errors) == 1
    assert isinstance(errors[0], NodeError)
    assert str(errors[0]).startswith("ELEVEN_LABS_API_KEY is not set")
    assert [link.url for link in errors[0].links] == [SETTINGS, KEY_PAGE]


@pytest.mark.parametrize("file", ["text_to_speech", "voice_changer"])
def test_empty_inputs_are_named_by_label_after_the_key_check(file):
    errors = make(file).validate_before_node_run()
    assert errors is not None and len(errors) == 1
    assert errors[0].fields["parameter"] in {"Text", "Audio or Video"}


# generate_music uses the node's httpx client and list_voices uses the SDK, which raises ApiError.
@pytest.mark.parametrize(("file", "inputs"), [("generate_music", {"prompt": "calm"}), ("list_voices", {})])
class TestRequestRejected:
    def test_a_401_is_a_refused_key_that_links_to_settings_only(self, file, inputs, monkeypatch):
        serve(monkeypatch, 401, REFUSED)
        error = run_to_error(file, make(file), **inputs)
        assert str(error).startswith("ElevenLabs refused the API key")
        assert [link.url for link in error.links] == [SETTINGS]
        assert error.fields == {"status_code": 401, "request_id": "req-1", "error_code": "unauthorized"}
        assert error.response == REFUSED

    def test_a_403_gives_the_reason_and_no_key_link(self, file, inputs, monkeypatch):
        serve(monkeypatch, 403, FORBIDDEN)
        error = run_to_error(file, make(file), **inputs)
        assert str(error) == "The key lacks the music_generation permission."
        assert error.links == []
        assert error.fields["status_code"] == 403

    def test_a_validation_list_is_read_as_the_reason(self, file, inputs, monkeypatch):
        serve(monkeypatch, 422, {"detail": [{"loc": ["body", "prompt"], "msg": "Field required"}]})
        assert str(run_to_error(file, make(file), **inputs)) == "prompt: Field required"


def test_the_music_terms_error_links_to_the_terms(monkeypatch):
    serve(monkeypatch, 403, TERMS)
    error = run_to_error("generate_music", make("generate_music"), prompt="calm")
    assert [link.url for link in error.links] == ["https://elevenlabs.io/music-terms"]


def test_a_connection_failure_is_a_node_error(monkeypatch):
    serve(monkeypatch, raises=httpx.ConnectError("refused"))
    error = run_to_error("generate_music", make("generate_music"), prompt="calm")
    assert str(error) == "Could not reach ElevenLabs. Check your internet connection and run the node again."


@pytest.mark.parametrize("content", [b"<html>Bad gateway</html>", b"", b"[]"])
def test_clone_voice_reports_a_2xx_body_that_is_not_a_json_object(content, monkeypatch):
    serve(monkeypatch, content=content)
    node = make("clone_voice")
    error = run_to_error("clone_voice", node, audio=[AudioArtifact(value=b"sample", format="mp3")])
    assert str(error) == "ElevenLabs sent a response the node could not read (HTTP 200)."


def test_a_rejected_sound_effect_raises_instead_of_leaving_an_empty_output(monkeypatch):
    serve(monkeypatch, 422, {"detail": {"status": "invalid_text", "message": "Text is too long."}})
    node = make("sound_effects")
    error = run_to_error("sound_effects", node, text="a door slams")
    assert str(error) == "Text is too long."
    assert error.fields["error_code"] == "invalid_text"


def test_a_rejected_voice_design_raises(monkeypatch):
    serve(monkeypatch, 401, REFUSED)
    error = run_to_error("voice_design", make("voice_design"), prompt="A warm, low voice", auto_generate_text=True)
    assert str(error).startswith("ElevenLabs refused the API key")


class Audio:
    """Stands in for File in voice_changer."""

    def __init__(self, _location):
        pass

    async def aread_bytes(self):
        return b"sample"


def prepare(file, node, monkeypatch, failure, wired):
    """Set the node up so that `failure` happens, and report whether Failed is wired."""
    monkeypatch.setattr(node, "_has_outgoing_connections", lambda _output: wired)
    if file == "text_to_speech":
        node.set_parameter_value("text", "hello")
    else:
        monkeypatch.setattr(sys.modules[type(node).__module__], "File", Audio)
        node.set_parameter_value("audio_or_video", AudioUrlArtifact(value="sample.mp3"))
    match failure:
        case "refused":
            serve(monkeypatch, 401, REFUSED)
        case "empty":
            serve(monkeypatch, 200, content=b"")
        case "no_location":
            node.set_parameter_value("audio_or_video", AudioUrlArtifact(value="x"))
            monkeypatch.setattr(node, "_extract_url_from_artifact", lambda _artifact: None)
        case "no_key":
            serve(monkeypatch, 200, content=b"audio")


@pytest.mark.parametrize("wired", [True, False], ids=["failed_wired", "failed_unwired"])
@pytest.mark.parametrize(
    ("file", "failure", "message"),
    [
        ("text_to_speech", "refused", "ElevenLabs refused the API key"),
        ("text_to_speech", "empty", "ElevenLabs returned no audio data."),
        ("text_to_speech", "no_key", "ELEVEN_LABS_API_KEY is not set"),
        ("voice_changer", "refused", "ElevenLabs refused the API key"),
        ("voice_changer", "empty", "ElevenLabs returned no audio data."),
        ("voice_changer", "no_location", "Could not find a location for the 'Audio or Video' input."),
    ],
)
def test_failures_follow_failed_when_wired_and_raise_when_not(file, failure, message, wired, monkeypatch, secrets):
    node = make(file)
    prepare(file, node, monkeypatch, failure, wired)
    if failure == "no_key":
        secrets.key = None
    if wired:
        asyncio.run(node._process_async())
        assert node._execution_succeeded is False
        assert node.parameter_output_values["audio" if file == "text_to_speech" else "audio_url"] is None
        assert message in node.get_parameter_value("result_details")
    else:
        with pytest.raises(NodeError, match=message):
            asyncio.run(node._process_async())
