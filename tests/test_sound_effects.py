"""Checks for the Sound Effects node's request. The elevenlabs package and the project files are replaced by stubs."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

NODE_FILE = Path(__file__).resolve().parents[1] / "elevenlabs" / "sound_effects.py"


def load_node_module():
    # Loaded by path: the library's own package is also called `elevenlabs`, like the SDK it uses.
    spec = importlib.util.spec_from_file_location("sound_effects_under_test", NODE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    """Stands in for elevenlabs.ElevenLabs and records what the node sent."""

    calls: list[dict] = []
    reject: tuple[str, ...] = ()

    def __init__(self, api_key: str) -> None:
        self.text_to_sound_effects = self

    def convert(self, **kwargs):
        for name in self.reject:
            if name in kwargs:
                raise TypeError(f"convert() got an unexpected keyword argument '{name}'")
        self.calls.append(kwargs)
        return iter([b"ID3fake-audio"])


class FakeSaved:
    location = "fake/elevenlabs_sfx.mp3"


class FakeFile:
    def build_file(self, **_kwargs):
        return self

    def write_bytes(self, _content):
        return FakeSaved()


@pytest.fixture
def node(monkeypatch):
    FakeClient.calls = []
    FakeClient.reject = ()
    monkeypatch.setitem(sys.modules, "elevenlabs", types.SimpleNamespace(ElevenLabs=FakeClient))
    monkeypatch.setenv("ELEVEN_LABS_API_KEY", "test-key")
    module = load_node_module()
    created = module.ElevenLabsSoundEffects(name="Sound Effects")
    created._output_file = FakeFile()
    created._resolved_api_key = "test-key"
    created.set_parameter_value("text", "a door slams")
    created.module = module
    return created


def test_defaults_to_v3_and_the_api_default_influence(node):
    node._run()
    assert FakeClient.calls == [
        {"text": "a door slams", "model_id": "eleven_text_to_sound_v3", "prompt_influence": 0.3}
    ]


def test_model_and_prompt_influence_are_sent(node):
    node.set_parameter_value("model", "eleven_text_to_sound_v2")
    node.set_parameter_value("prompt_influence", 0.8)
    node._run()
    assert FakeClient.calls[0]["model_id"] == "eleven_text_to_sound_v2"
    assert FakeClient.calls[0]["prompt_influence"] == 0.8


def test_duration_and_looping_still_go_with_them(node):
    node.set_parameter_value("use_specific_duration", True)
    node.set_parameter_value("duration_seconds", 4.0)
    node.set_parameter_value("looping", True)
    node._run()
    assert FakeClient.calls[0] == {
        "text": "a door slams",
        "model_id": "eleven_text_to_sound_v3",
        "prompt_influence": 0.3,
        "duration_seconds": 4.0,
        "loop": True,
    }


def test_request_is_recorded_in_the_metadata(node):
    node.set_parameter_value("model", "eleven_text_to_sound_v2")
    node._run()
    request = node.parameter_output_values["metadata"]["request"]
    assert request["model_id"] == "eleven_text_to_sound_v2"
    assert request["prompt_influence"] == 0.3


def test_an_old_sdk_is_an_error_not_a_quiet_fallback_to_v2(node):
    FakeClient.reject = ("model_id",)
    with pytest.raises(RuntimeError, match="Update it"):
        node._run()
    assert FakeClient.calls == []


def test_any_rejected_argument_is_an_error_and_not_retried_with_fewer(node):
    node.set_parameter_value("looping", True)
    FakeClient.reject = ("loop",)
    with pytest.raises(RuntimeError, match="Update it"):
        node._run()
    assert FakeClient.calls == []


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_prompt_influence_must_be_between_0_and_1(node, value):
    node.set_parameter_value("prompt_influence", value)
    with pytest.raises(ValueError, match="between 0 and 1"):
        node._run()
