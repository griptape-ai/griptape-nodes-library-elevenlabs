"""Tests for the error construction shared by the ElevenLabs nodes."""

from __future__ import annotations

import httpx
import pytest
from elevenlabs_node_errors import (
    connection_error,
    error_from_http_error,
    error_from_response,
    missing_api_key_error,
    provider_errors,
)
from griptape_nodes.exe_types.core_types import NodeError
from pydantic import BaseModel

KEY_PAGE = "https://elevenlabs.io/app/settings/api-keys"


def _status_error(
    status: int, *, json_body: object = None, text: str = "", headers: dict[str, str] | None = None
) -> httpx.HTTPStatusError:
    """Reproduce what httpx raises for an error response, through raise_for_status()."""
    request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/abc")
    if json_body is not None:
        response = httpx.Response(status, json=json_body, headers=headers, request=request)
    else:
        response = httpx.Response(status, text=text, headers=headers, request=request)
    with pytest.raises(httpx.HTTPStatusError) as raised:
        response.raise_for_status()
    return raised.value


def test_missing_api_key_links_to_the_secret_and_the_key_page() -> None:
    error = missing_api_key_error()

    assert str(error) == (
        "ELEVEN_LABS_API_KEY is not set. Add it in Settings → API Keys & Secrets, then run the node again."
    )
    assert [(link.label, link.url) for link in error.links] == [
        ("Add the API key", "#settings-secrets?filter=ELEVEN_LABS_API_KEY"),
        ("Get an ElevenLabs API key", KEY_PAGE),
    ]


def test_a_detail_object_gives_the_message_status_code_request_id_and_response() -> None:
    body = {
        "detail": {
            "status": "voice_not_found",
            "message": "A voice with the voice_id abc was not found.",
            "request_id": "r-1",
        }
    }

    error = error_from_http_error(_status_error(404, json_body=body))

    assert str(error) == "A voice with the voice_id abc was not found."
    assert error.fields == {"status_code": 404, "request_id": "r-1", "error_code": "voice_not_found"}
    assert error.response == body
    assert error.links == []


def test_a_detail_string_is_the_message() -> None:
    error = error_from_http_error(_status_error(400, json_body={"detail": "Text is too long."}))

    assert str(error) == "Text is too long."
    assert error.fields == {"status_code": 400}


def test_a_validation_list_gives_one_entry_per_problem() -> None:
    body = {
        "detail": [
            {"loc": ["body", "text"], "msg": "Field required", "type": "missing"},
            {
                "loc": ["body", "voice_settings", "speed"],
                "msg": "Input should be at most 1.2",
                "type": "less_than_equal",
            },
        ]
    }

    error = error_from_http_error(_status_error(422, json_body=body))

    assert str(error) == "text: Field required; voice_settings.speed: Input should be at most 1.2"
    assert error.response == body


def test_the_trace_header_is_the_request_id_when_the_body_has_none() -> None:
    error = error_from_http_error(
        _status_error(500, json_body={"detail": "Internal error"}, headers={"X-Trace-Id": "trace-9"})
    )

    assert error.fields == {"status_code": 500, "request_id": "trace-9"}


def test_a_body_that_is_not_json_is_attached_as_text() -> None:
    error = error_from_http_error(_status_error(502, text="<html>Bad gateway</html>"))

    assert str(error) == "<html>Bad gateway</html>"
    assert error.response == {"body": "<html>Bad gateway</html>"}


def test_an_empty_body_describes_the_status() -> None:
    error = error_from_response(503, "")

    assert str(error) == "ElevenLabs returned an error (HTTP 503)."
    assert error.response is None


def test_a_refused_key_links_to_the_secret_and_the_key_page() -> None:
    body = {
        "detail": {
            "type": "authentication_error",
            "code": "unauthorized",
            "message": "Invalid API key",
            "status": "invalid_api_key",
            "request_id": "r-2",
        }
    }

    error = error_from_http_error(_status_error(401, json_body=body))

    assert str(error) == (
        "ElevenLabs rejected the API key: Invalid API key. "
        "Update ELEVEN_LABS_API_KEY in Settings → API Keys & Secrets, then run the node again."
    )
    assert error.fields == {"status_code": 401, "request_id": "r-2", "error_code": "invalid_api_key"}
    assert error.response == body
    assert [(link.label, link.url) for link in error.links] == [
        ("Update the API key", "#settings-secrets?filter=ELEVEN_LABS_API_KEY"),
        ("Get an ElevenLabs API key", KEY_PAGE),
    ]


def test_a_401_for_missing_permissions_does_not_offer_the_key_links() -> None:
    body = {
        "detail": {"status": "missing_permissions", "message": "The API key is missing the permission text_to_speech."}
    }

    error = error_from_http_error(_status_error(401, json_body=body))

    assert str(error) == "The API key is missing the permission text_to_speech."
    assert error.links == []


def test_music_terms_link_is_added_only_when_asked_for() -> None:
    body = {"detail": {"status": "limited_access", "message": "Accept the terms at https://elevenlabs.io/music-terms"}}

    with_link = error_from_http_error(_status_error(403, json_body=body), music_terms=True)
    without = error_from_http_error(_status_error(403, json_body=body))

    assert str(with_link) == (
        "Accept the terms at https://elevenlabs.io/music-terms. Accept the Eleven Music terms, then run the node again."
    )
    assert [link.url for link in with_link.links] == ["https://elevenlabs.io/music-terms"]
    assert without.links == []


def test_a_pydantic_body_from_the_sdk_is_attached_as_a_dict() -> None:
    class Validation(BaseModel):
        detail: list[dict[str, object]]

    body = Validation(detail=[{"loc": ["body", "text"], "msg": "Field required"}])

    error = error_from_response(422, body)

    assert str(error) == "text: Field required"
    assert error.response == {"detail": [{"loc": ["body", "text"], "msg": "Field required"}]}


def test_an_oversized_body_is_cut_down_to_text() -> None:
    error = error_from_response(400, {"detail": "Too big.", "padding": "x" * 20_000})

    assert str(error) == "Too big."
    assert error.response is not None
    assert set(error.response) == {"body"}


def test_a_timeout_says_elevenlabs_did_not_respond() -> None:
    assert str(connection_error(httpx.ReadTimeout(""))) == "ElevenLabs did not respond in time. Run the node again."


def test_a_connection_failure_gives_the_reason() -> None:
    error = connection_error(httpx.ConnectError("no route to host"))

    assert str(error) == "Could not reach ElevenLabs: no route to host. Check your connection and run the node again."
    assert error.fields == {}


def test_provider_errors_leaves_other_exceptions_alone() -> None:
    with pytest.raises(KeyError), provider_errors():
        raise KeyError("x")


def test_provider_errors_keeps_the_original_exception_as_the_cause() -> None:
    original = _status_error(
        429, json_body={"detail": {"status": "too_many_concurrent_requests", "message": "Slow down."}}
    )

    with pytest.raises(NodeError) as raised, provider_errors():
        raise original

    assert raised.value.__cause__ is original
    assert str(raised.value) == "Slow down."
