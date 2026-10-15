"""Shared error construction for the ElevenLabs nodes.

Every node that calls the ElevenLabs API turns failures into a NodeError here, so the editor shows
ElevenLabs' own message with the status code, request ID and response body attached.

ElevenLabs reports an error under a top-level ``detail`` key. ``detail`` is a string, an object with
``message``, ``status``, ``code`` and ``request_id``, or a list of validation problems.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import httpx
from griptape_nodes.exe_types.core_types import NodeError, NodeErrorLink

API_KEY_NAME = "ELEVEN_LABS_API_KEY"
API_KEY_PAGE_URL = "https://elevenlabs.io/app/settings/api-keys"
MUSIC_TERMS_URL = "https://elevenlabs.io/music-terms"

# ElevenLabs sends the request ID in the body. The trace header is the fallback.
TRACE_HEADER = "x-trace-id"

# Error codes ElevenLabs uses when it does not accept the API key it was sent.
KEY_REFUSED_CODES = {"invalid_api_key", "needs_authorization"}

MAX_RESPONSE_TEXT = 2000
MAX_RESPONSE_BYTES = 12_000


def api_key_link(label: str) -> NodeErrorLink:
    """Link that opens the API key secret in the editor's settings."""
    return NodeErrorLink(label=label, url=f"#settings-secrets?filter={quote(API_KEY_NAME)}")


def missing_api_key_error() -> NodeError:
    """Error for a run that has no ElevenLabs API key."""
    return NodeError(
        f"{API_KEY_NAME} is not set. Add it in Settings → API Keys & Secrets, then run the node again.",
        links=[
            api_key_link("Add the API key"),
            NodeErrorLink(label="Get an ElevenLabs API key", url=API_KEY_PAGE_URL),
        ],
    )


def resolve_api_key(node: Any) -> str | None:
    """The API key from the node's config, then from the environment."""
    try:
        key = node.get_config_value(value=API_KEY_NAME)
    except Exception:
        key = None
    return key or os.environ.get(API_KEY_NAME)


def parameter_error(message: str, parameter: str) -> NodeError:
    """Error about one parameter's value, naming it in `fields`."""
    return NodeError(message, fields={"parameter": parameter})


def error_from_response(
    status_code: int | None,
    body: Any,
    headers: Mapping[str, str] | None = None,
    *,
    music_terms: bool = False,
) -> NodeError:
    """Build a NodeError from an ElevenLabs error response.

    Args:
        status_code: HTTP status code of the response.
        body: Parsed JSON body, or the raw text when the body is not JSON.
        headers: Response headers, used to find the request ID when the body has none.
        music_terms: Add the Eleven Music terms link when the response says the terms are not accepted.
    """
    body = _plain(body)
    message, error_code, request_id = _read_detail(body)
    if request_id is None:
        request_id = _header(headers, TRACE_HEADER)

    if not message:
        message = (
            f"ElevenLabs returned an error (HTTP {status_code})." if status_code else "ElevenLabs returned an error."
        )

    fields: dict[str, str | int | float | bool] = {}
    if status_code is not None:
        fields["status_code"] = status_code
    if request_id:
        fields["request_id"] = request_id
    if error_code:
        fields["error_code"] = error_code

    links: list[NodeErrorLink] = []
    key_refused = status_code == 401 and (error_code is None or error_code in KEY_REFUSED_CODES)
    if key_refused:
        message = f"ElevenLabs rejected the API key: {message.rstrip('.')}. Update {API_KEY_NAME} in Settings → API Keys & Secrets, then run the node again."
        links = [
            api_key_link("Update the API key"),
            NodeErrorLink(label="Get an ElevenLabs API key", url=API_KEY_PAGE_URL),
        ]
    elif music_terms and _mentions_music_terms(body):
        message = f"{message.rstrip('.')}. Accept the Eleven Music terms, then run the node again."
        links = [NodeErrorLink(label="Eleven Music terms", url=MUSIC_TERMS_URL)]

    return NodeError(message, fields=fields, response=_response_dict(body), links=links)


def error_from_http_error(error: httpx.HTTPStatusError, *, music_terms: bool = False) -> NodeError:
    """Build a NodeError from an httpx status error."""
    response = error.response
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return error_from_response(response.status_code, body, response.headers, music_terms=music_terms)


def is_sdk_api_error(error: BaseException) -> bool:
    """True for the ElevenLabs SDK's ApiError and its subclasses (they carry status_code, body, headers)."""
    return isinstance(getattr(error, "status_code", None), int) and hasattr(error, "body")


def error_from_sdk_error(error: BaseException, *, music_terms: bool = False) -> NodeError:
    """Build a NodeError from an ElevenLabs SDK ApiError."""
    return error_from_response(
        getattr(error, "status_code", None),
        getattr(error, "body", None),
        getattr(error, "headers", None),
        music_terms=music_terms,
    )


def connection_error(error: httpx.RequestError) -> NodeError:
    """Build a NodeError for a request that never got an answer from ElevenLabs."""
    if isinstance(error, httpx.TimeoutException):
        return NodeError("ElevenLabs did not respond in time. Run the node again.")
    reason = str(error) or type(error).__name__
    return NodeError(f"Could not reach ElevenLabs: {reason}. Check your connection and run the node again.")


@contextmanager
def provider_errors(*, music_terms: bool = False) -> Iterator[None]:
    """Turn ElevenLabs failures raised inside the block into NodeError.

    Covers httpx status and connection errors and the SDK's ApiError. Any other exception propagates unchanged.
    """
    try:
        yield
    except NodeError:
        raise
    except httpx.HTTPStatusError as e:
        raise error_from_http_error(e, music_terms=music_terms) from e
    except httpx.RequestError as e:
        raise connection_error(e) from e
    except Exception as e:
        if is_sdk_api_error(e):
            raise error_from_sdk_error(e, music_terms=music_terms) from e
        raise


def _plain(body: Any) -> Any:
    """Reduce an SDK body object (pydantic model) to plain JSON types."""
    if hasattr(body, "model_dump"):
        try:
            return body.model_dump(mode="json")
        except Exception:
            return str(body)
    return body


def _read_detail(body: Any) -> tuple[str | None, str | None, str | None]:
    """Return (message, error_code, request_id) read from an ElevenLabs error body."""
    if isinstance(body, str):
        return (body.strip() or None), None, None
    if not isinstance(body, dict):
        return None, None, None

    detail = body.get("detail")
    if isinstance(detail, str):
        return detail or None, None, None
    if isinstance(detail, dict):
        message = detail.get("message")
        code = detail.get("status") or detail.get("code")
        request_id = detail.get("request_id")
        return (
            message if isinstance(message, str) and message else None,
            code if isinstance(code, str) and code else None,
            request_id if isinstance(request_id, str) and request_id else None,
        )
    if isinstance(detail, list):
        return _validation_message(detail), None, None

    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value, None, None
    return None, None, None


def _validation_message(problems: list[Any]) -> str | None:
    """Join a validation list into one message, one problem per entry."""
    parts: list[str] = []
    for problem in problems:
        if isinstance(problem, dict):
            text = problem.get("msg") or problem.get("message")
            loc = problem.get("loc")
            if text and isinstance(loc, list) and loc:
                where = ".".join(str(p) for p in loc if p != "body")
                parts.append(f"{where}: {text}" if where else str(text))
            elif text:
                parts.append(str(text))
        elif isinstance(problem, str):
            parts.append(problem)
    return "; ".join(parts) or None


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value) or None
    return None


def _mentions_music_terms(body: Any) -> bool:
    text = body if isinstance(body, str) else json.dumps(body, default=str)
    text = text.lower()
    return "music-terms" in text or "limited_access" in text


def _response_dict(body: Any) -> dict[str, Any] | None:
    """Shape a body for NodeError.response: a JSON dict well under the 16 KB limit."""
    if body is None or body == "":
        return None
    if isinstance(body, dict):
        candidate: dict[str, Any] = body
    elif isinstance(body, list):
        candidate = {"detail": body}
    else:
        candidate = {"body": str(body)[:MAX_RESPONSE_TEXT]}
    try:
        if len(json.dumps(candidate)) <= MAX_RESPONSE_BYTES:
            return candidate
    except (TypeError, ValueError):
        pass
    return {"body": str(body)[:MAX_RESPONSE_TEXT]}
