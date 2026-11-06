"""What the ElevenLabs nodes share when they turn a failure into a `NodeError`.

The SDK raises `ApiError`, which is not an httpx error. `request_error` hands its status, headers and
body to `NodeError.from_http_response`, which reads ElevenLabs' `detail` (a string, an object with
`message` and `status`, or a list of validation problems).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import httpx
from griptape_nodes.exe_types.core_types import NodeError, NodeErrorLink
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

from elevenlabs.core.api_error import ApiError

API_KEY_NAME = "ELEVEN_LABS_API_KEY"
API_KEY_URL = "https://elevenlabs.io/app/settings/api-keys"
MUSIC_TERMS_URL = "https://elevenlabs.io/music-terms"
PROVIDER = "ElevenLabs"
REQUEST_ERRORS = (ApiError, httpx.HTTPError)


def api_key() -> str:
    key = GriptapeNodes.SecretsManager().get_secret(API_KEY_NAME, should_error_on_not_found=False)
    if not key:
        raise NodeError.from_missing_secret(API_KEY_NAME, key_url=API_KEY_URL)
    return key


def validate_api_key() -> list[Exception] | None:
    """For `validate_before_node_run`: a missing key, reported first and alone."""
    try:
        api_key()
    except NodeError as e:
        return [e]
    return None


def parameter_error(message: str, parameter: str) -> NodeError:
    """An input problem, with the parameter's label in `fields`."""
    return NodeError(message, fields={"parameter": parameter})


def request_error(exc: Exception) -> NodeError:
    """The `NodeError` for a failed ElevenLabs call. Only a 401 is a refused key."""
    if isinstance(exc, ApiError):
        response = httpx.Response(exc.status_code or 0, headers=exc.headers, json=exc.body)
        error = NodeError.from_http_response(
            response, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=response.status_code == 401
        )
    else:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        error = NodeError.from_request_exception(
            exc, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=status == 401
        )
    text = f"{error} {error.response}".lower()
    if "music-terms" in text or "limited_access" in text:
        error.links.append(NodeErrorLink(label="Accept the Eleven Music terms", url=MUSIC_TERMS_URL))
    return error


def raises_node_error(run: Callable[..., Any]) -> Callable[..., Any]:
    """Decorate a node's `_run` so a failed ElevenLabs call raises `NodeError`."""

    @functools.wraps(run)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return run(*args, **kwargs)
        except REQUEST_ERRORS as exc:
            raise request_error(exc) from exc

    return wrapper
