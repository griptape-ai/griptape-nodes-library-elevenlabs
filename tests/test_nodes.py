"""Drive the real ElevenLabs nodes and check the errors they raise.

The HTTP layer is faked at httpx's transport, so requests, status handling and response parsing run for real.
The SDK nodes get a stand-in `elevenlabs` module whose client raises the SDK's ApiError.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from griptape.artifacts.audio_artifact import AudioArtifact
from griptape.artifacts.audio_url_artifact import AudioUrlArtifact
from griptape_nodes.exe_types.core_types import NodeError

KEY_SECRET_LINK = "#settings-secrets?filter=ELEVEN_LABS_API_KEY"

REFUSED_KEY_BODY = {
    "detail": {
        "type": "authentication_error",
        "code": "unauthorized",
        "message": "Invalid API key",
        "status": "invalid_api_key",
        "request_id": "req-401",
    }
}

NODE_FILES = [
    "clone_voice",
    "generate_music",
    "list_voices",
    "save_voice",
    "sound_effects",
    "text_to_speech",
    "voice_changer",
    "voice_design",
]

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "elevenlabs"

REAL_CLIENT = httpx.Client
REAL_ASYNC_CLIENT = httpx.AsyncClient


def _node(module_name: str, class_name: str) -> tuple[Any, Any]:
    module = importlib.import_module(module_name)
    return module, getattr(module, class_name)(name="Some Node")


def _fake_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Route every httpx client the nodes create through `handler`; return the requests it saw."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: REAL_CLIENT(transport=transport, **kwargs))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=transport, **kwargs))
    return seen


def _answer(status: int, body: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, json=body)


def _with_key(module: Any, key: str | None):
    """Patch the secrets lookup used by the SuccessFailureNode and httpx DataNode classes."""
    engine = patch.object(module, "GriptapeNodes")
    started = engine.start()
    started.SecretsManager.return_value.get_secret.return_value = key
    return engine


@pytest.fixture
def key_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELEVEN_LABS_API_KEY", "key")


@pytest.fixture
def key_absent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ELEVEN_LABS_API_KEY", raising=False)


# --- Text to Speech -----------------------------------------------------------------------------


@pytest.fixture
def patched_engine():
    started: list[Any] = []

    def start(module: Any, key: str | None) -> None:
        engine = _with_key(module, key)
        started.append(engine)

    yield start
    for engine in started:
        engine.stop()


def test_tts_validation_reports_each_problem_without_the_node_name(patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "  ")
    patched_engine(module, None)

    errors = node.validate_before_node_run()

    assert errors is not None
    assert all(isinstance(error, NodeError) for error in errors)
    assert all("Some Node" not in str(error) for error in errors)
    assert len(errors) == 2
    key_error, text_error = errors
    assert key_error.links[0].url == KEY_SECRET_LINK
    assert str(text_error) == "'Text' is empty. Enter the text to speak and run the node again."
    assert text_error.fields == {"parameter": "text"}


def test_tts_a_refused_key_raises_with_status_request_id_response_and_links(monkeypatch, patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node._has_outgoing_connections = lambda _parameter: False
    patched_engine(module, "key")
    _fake_http(monkeypatch, _answer(401, REFUSED_KEY_BODY))

    with pytest.raises(NodeError) as raised:
        asyncio.run(node._process_async())

    assert str(raised.value).startswith("ElevenLabs rejected the API key: Invalid API key.")
    assert raised.value.fields == {"status_code": 401, "request_id": "req-401", "error_code": "invalid_api_key"}
    assert raised.value.response == REFUSED_KEY_BODY
    assert [link.label for link in raised.value.links] == ["Update the API key", "Get an ElevenLabs API key"]
    assert raised.value.links[0].url == KEY_SECRET_LINK


def test_tts_follows_the_failed_output_when_it_is_wired(monkeypatch, patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node._has_outgoing_connections = lambda _parameter: True
    patched_engine(module, "key")
    _fake_http(monkeypatch, _answer(429, {"detail": {"status": "rate_limited", "message": "Slow down."}}))

    asyncio.run(node._process_async())

    assert node.parameter_output_values["was_successful"] is False
    assert "Slow down." in node.parameter_output_values["result_details"]
    assert node.parameter_output_values["audio"] is None


def test_tts_a_key_missing_at_run_time_goes_through_the_failure_path(patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node._has_outgoing_connections = lambda _parameter: True
    patched_engine(module, None)

    asyncio.run(node._process_async())

    assert node.parameter_output_values["was_successful"] is False
    assert "ELEVEN_LABS_API_KEY is not set" in node.parameter_output_values["result_details"]


def test_tts_an_empty_answer_raises_instead_of_failing_silently(monkeypatch, patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node._has_outgoing_connections = lambda _parameter: False
    patched_engine(module, "key")
    _fake_http(monkeypatch, lambda _request: httpx.Response(200, content=b""))

    with pytest.raises(NodeError, match="ElevenLabs returned no audio"):
        asyncio.run(node._process_async())


def test_tts_a_missing_voice_names_the_parameter(monkeypatch, patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node.set_parameter_value("voice_preset", "Custom...")
    node.set_parameter_value("custom_voice_id", "")
    node._has_outgoing_connections = lambda _parameter: False
    patched_engine(module, "key")

    with pytest.raises(NodeError) as raised:
        asyncio.run(node._process_async())

    assert str(raised.value) == (
        "No voice is selected. Choose one in 'Voice', or enter an ID in 'Custom Voice ID', and run the node again."
    )
    assert raised.value.fields == {"parameter": "voice_preset"}


def test_tts_a_connection_failure_says_elevenlabs_could_not_be_reached(monkeypatch, patched_engine) -> None:
    module, node = _node("text_to_speech", "ElevenLabsTextToSpeech")
    node.set_parameter_value("text", "Hello there")
    node._has_outgoing_connections = lambda _parameter: False
    patched_engine(module, "key")

    def refuse(request: httpx.Request) -> httpx.Response:
        msg = "no route to host"
        raise httpx.ConnectError(msg, request=request)

    _fake_http(monkeypatch, refuse)

    with pytest.raises(NodeError, match="Could not reach ElevenLabs: no route to host"):
        asyncio.run(node._process_async())


# --- Voice Changer ------------------------------------------------------------------------------


def _voice_changer(patched_engine, *, audio: Any = "https://example.com/in.mp3") -> tuple[Any, Any]:
    module, node = _node("voice_changer", "ElevenLabsVoiceChanger")
    if audio is not None:
        node.set_parameter_value("audio_or_video", AudioUrlArtifact(value=audio))
    node._has_outgoing_connections = lambda _parameter: False
    patched_engine(module, "key")
    return module, node


def test_voice_changer_validation_reports_each_problem_without_the_node_name(patched_engine) -> None:
    module, node = _node("voice_changer", "ElevenLabsVoiceChanger")
    patched_engine(module, None)

    errors = node.validate_before_node_run()

    assert errors is not None
    assert all(isinstance(error, NodeError) for error in errors)
    assert all("Some Node" not in str(error) for error in errors)
    assert errors[0].links[0].url == KEY_SECRET_LINK
    assert str(errors[1]) == "'Audio or Video' has no input. Connect an audio or video file and run the node again."


def test_voice_changer_a_validation_list_from_the_api_is_read_from_detail(monkeypatch, patched_engine) -> None:
    _module, node = _voice_changer(patched_engine)
    body = {"detail": [{"loc": ["body", "seed"], "msg": "Input should be less than 4294967295", "type": "x"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=b"audio")
        return httpx.Response(422, json=body)

    _fake_http(monkeypatch, handler)

    with pytest.raises(NodeError) as raised:
        asyncio.run(node._process_async())

    assert str(raised.value) == "seed: Input should be less than 4294967295"
    assert raised.value.fields == {"status_code": 422}
    assert raised.value.response == body


def test_voice_changer_an_unreadable_input_names_the_parameter(patched_engine) -> None:
    _module, node = _voice_changer(patched_engine, audio=None)

    with pytest.raises(NodeError) as raised:
        asyncio.run(node._process_async())

    assert str(raised.value) == (
        "Could not read the file connected to 'Audio or Video'. Connect an audio or video file and run the node again."
    )
    assert raised.value.fields == {"parameter": "audio_or_video"}


def test_voice_changer_a_failed_download_says_which_input_and_the_status(monkeypatch, patched_engine) -> None:
    _module, node = _voice_changer(patched_engine)
    _fake_http(monkeypatch, lambda _request: httpx.Response(404, text="gone"))

    with pytest.raises(NodeError) as raised:
        asyncio.run(node._process_async())

    assert str(raised.value) == (
        "Could not download the file connected to 'Audio or Video' (HTTP 404). "
        "Check that the file is still available and run the node again."
    )
    assert "example.com" not in str(raised.value)


def test_voice_changer_an_empty_answer_raises_instead_of_failing_silently(monkeypatch, patched_engine) -> None:
    _module, node = _voice_changer(patched_engine)
    _fake_http(monkeypatch, lambda request: httpx.Response(200, content=b"audio" if request.method == "GET" else b""))

    with pytest.raises(NodeError, match="ElevenLabs returned no audio"):
        asyncio.run(node._process_async())


# --- Generate Music -----------------------------------------------------------------------------


def _music(patched_engine, key: str | None = "key") -> tuple[Any, Any]:
    module, node = _node("generate_music", "ElevenLabsGenerateMusic")
    node.set_parameter_value("prompt", "calm piano")
    patched_engine(module, key)
    return module, node


def test_music_a_missing_key_links_to_the_secret_and_the_key_page(patched_engine) -> None:
    _module, node = _music(patched_engine, key=None)

    with pytest.raises(NodeError) as raised:
        node._run()

    assert [link.label for link in raised.value.links] == ["Add the API key", "Get an ElevenLabs API key"]
    assert "Some Node" not in str(raised.value)


def test_music_terms_error_carries_the_terms_link(monkeypatch, patched_engine) -> None:
    _module, node = _music(patched_engine)
    body = {"detail": {"status": "limited_access", "message": "You must accept the terms at /music-terms first."}}
    _fake_http(monkeypatch, _answer(403, body))

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value) == (
        "You must accept the terms at /music-terms first. Accept the Eleven Music terms, then run the node again."
    )
    assert [link.url for link in raised.value.links] == ["https://elevenlabs.io/music-terms"]
    assert raised.value.fields == {"status_code": 403, "error_code": "limited_access"}
    assert raised.value.response == body


def test_music_an_api_error_is_raised_as_the_providers_own_message(monkeypatch, patched_engine) -> None:
    _module, node = _music(patched_engine)
    _fake_http(monkeypatch, _answer(400, {"detail": {"status": "bad_prompt", "message": "The prompt is not allowed."}}))

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value) == "The prompt is not allowed."


# --- Clone Voice --------------------------------------------------------------------------------


def _clone(patched_engine, key: str | None = "key", audio: Any = None) -> tuple[Any, Any]:
    module, node = _node("clone_voice", "ElevenLabsCloneVoice")
    values = {"audio": audio, "voice_name": "Mine"}
    node.get_parameter_value = lambda name: values.get(name)
    patched_engine(module, key)
    return module, node


def test_clone_without_audio_names_the_parameter(patched_engine) -> None:
    _module, node = _clone(patched_engine)

    with pytest.raises(NodeError) as raised:
        node._run()

    assert (
        str(raised.value) == "'Audio Sample(s)' has no input. Connect at least one audio sample and run the node again."
    )
    assert raised.value.fields == {"parameter": "audio"}


def test_clone_an_api_error_is_not_wrapped_in_a_second_message(monkeypatch, patched_engine) -> None:
    _module, node = _clone(patched_engine, audio=[AudioArtifact(value=b"abc", format="mp3")])
    body = {"detail": {"status": "voice_limit_reached", "message": "You have reached your voice limit."}}
    _fake_http(monkeypatch, _answer(400, body))

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value) == "You have reached your voice limit."
    assert raised.value.fields == {"status_code": 400, "error_code": "voice_limit_reached"}
    assert raised.value.response == body


def test_clone_a_response_without_a_voice_id_attaches_the_response(monkeypatch, patched_engine) -> None:
    _module, node = _clone(patched_engine, audio=[AudioArtifact(value=b"abc", format="mp3")])
    _fake_http(monkeypatch, _answer(200, {"unexpected": True}))

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value) == "ElevenLabs did not return a voice ID for the cloned voice. Run the node again."
    assert raised.value.response == {"unexpected": True}


# --- Nodes that use the ElevenLabs SDK ----------------------------------------------------------


class FakeApiError(Exception):
    """Same attributes and str() as elevenlabs.core.api_error.ApiError."""

    def __init__(self, *, status_code: int, body: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers

    def __str__(self) -> str:
        return f"headers: {self.headers}, status_code: {self.status_code}, body: {self.body}"


def _install_sdk(monkeypatch: pytest.MonkeyPatch, error: Exception | None, *, raise_on_iteration: bool = False) -> None:
    """Install a stand-in `elevenlabs` module whose client calls fail with `error`."""

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        if error is not None:
            raise error
        return {}

    def stream(*_args: Any, **_kwargs: Any) -> Any:
        # The SDK's convert() is a generator: the request is sent, and fails, when iteration starts.
        if error is not None:
            raise error
        yield b"audio"

    class Namespace:
        search = staticmethod(fail)
        create = staticmethod(fail)
        design = staticmethod(fail)
        convert = staticmethod(stream if raise_on_iteration else fail)

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.voices = Namespace()
            self.text_to_voice = Namespace()
            self.text_to_sound_effects = Namespace()

    module = types.ModuleType("elevenlabs")
    module.ElevenLabs = FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "elevenlabs", module)


SDK_NODES = [
    ("list_voices", "ElevenLabsListVoices", {}),
    (
        "save_voice",
        "ElevenLabsSaveVoice",
        {
            "generated_voice_id": "gen-1",
            "voice_name": "Mine",
            "voice_description": "A calm, warm narrator voice for audiobooks.",
        },
    ),
    ("sound_effects", "ElevenLabsSoundEffects", {"text": "door slam"}),
    (
        "voice_design",
        "ElevenLabsDesignVoice",
        {
            "prompt": "a raspy cowboy voice with a heavy accent",
            "auto_generate_text": True,
        },
    ),
]


def _sdk_node(module_name: str, class_name: str, values: dict[str, Any]) -> Any:
    _module, node = _node(module_name, class_name)
    for name, value in values.items():
        node.set_parameter_value(name, value)
    return node


@pytest.mark.parametrize(("module_name", "class_name", "values"), SDK_NODES)
def test_sdk_node_a_missing_key_links_to_the_secret_and_the_key_page(
    module_name: str, class_name: str, values: dict[str, Any], key_absent
) -> None:
    node = _sdk_node(module_name, class_name, values)

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value).startswith("ELEVEN_LABS_API_KEY is not set.")
    assert [link.label for link in raised.value.links] == ["Add the API key", "Get an ElevenLabs API key"]


@pytest.mark.parametrize(("module_name", "class_name", "values"), SDK_NODES)
def test_sdk_node_a_refused_key_raises_with_status_request_id_response_and_links(
    module_name: str, class_name: str, values: dict[str, Any], key_present, monkeypatch
) -> None:
    node = _sdk_node(module_name, class_name, values)
    _install_sdk(
        monkeypatch,
        FakeApiError(status_code=401, body=REFUSED_KEY_BODY, headers={"x-trace-id": "trace-1"}),
        raise_on_iteration=True,
    )

    with pytest.raises(NodeError) as raised:
        node._run()

    assert str(raised.value).startswith("ElevenLabs rejected the API key: Invalid API key.")
    assert raised.value.fields == {"status_code": 401, "request_id": "req-401", "error_code": "invalid_api_key"}
    assert raised.value.response == REFUSED_KEY_BODY
    assert raised.value.links[0].label == "Update the API key"
    assert isinstance(raised.value.__cause__, FakeApiError)


@pytest.mark.parametrize(
    ("module_name", "class_name", "values"), [node for node in SDK_NODES if node[0] != "sound_effects"]
)
def test_sdk_node_other_failures_propagate_unchanged(
    module_name: str, class_name: str, values: dict[str, Any], key_present, monkeypatch
) -> None:
    node = _sdk_node(module_name, class_name, values)
    _install_sdk(monkeypatch, RuntimeError("socket closed"), raise_on_iteration=True)

    with pytest.raises(RuntimeError, match="socket closed"):
        node._run()


def test_sound_effects_a_rejected_request_is_not_swallowed_while_the_stream_is_read(key_present, monkeypatch) -> None:
    """The SDK sends the request when its generator is first iterated, so the error appears while joining chunks."""
    node = _sdk_node("sound_effects", "ElevenLabsSoundEffects", {"text": "door slam"})
    body = {"detail": {"status": "quota_exceeded", "message": "You have run out of credits."}}
    _install_sdk(monkeypatch, FakeApiError(status_code=401, body=body), raise_on_iteration=True)

    with pytest.raises(NodeError, match="You have run out of credits."):
        node._run()


def test_sdk_nodes_name_the_parameter_when_an_input_is_missing(key_present) -> None:
    save = _sdk_node("save_voice", "ElevenLabsSaveVoice", {"generated_voice_id": "g", "voice_name": "n"})
    with pytest.raises(NodeError) as raised:
        save._run()
    assert str(raised.value) == "'Voice Description' must be between 20 and 1000 characters. It has 0."
    assert raised.value.fields == {"parameter": "voice_description"}

    effects = _sdk_node("sound_effects", "ElevenLabsSoundEffects", {"text": " "})
    with pytest.raises(NodeError, match="'Text' is empty"):
        effects._run()

    design = _sdk_node("voice_design", "ElevenLabsDesignVoice", {"prompt": ""})
    with pytest.raises(NodeError, match="'Prompt' is empty"):
        design._run()


# --- Loading ------------------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", NODE_FILES)
def test_a_node_file_loads_the_way_the_engine_loads_it(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine loads each node file on its own, with the library folder on sys.path.

    There is no parent package, so a node has to import its sibling modules by bare name. The dev
    environment installs the project, which would hide a package-name import, so make the package
    unimportable here.
    """
    monkeypatch.syspath_prepend(str(LIBRARY_DIR))
    monkeypatch.setitem(sys.modules, "elevenlabs", None)
    monkeypatch.delitem(sys.modules, "elevenlabs_node_errors", raising=False)

    spec = importlib.util.spec_from_file_location(f"engine_loaded_{module_name}", LIBRARY_DIR / f"{module_name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "elevenlabs_node_errors" in sys.modules
