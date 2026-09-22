"""Read-only client for https://x1.ninja/developers."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NinjaError(Exception):
    """Safe user-facing API error, without credentials or response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer credential to a redirect destination.
        return None


class NinjaClient:
    def __init__(self, api_key: str | None = None):
        self._key = (os.environ.get("X1_API_KEY", "") if api_key is None else api_key).strip()
        if not self._key:
            raise NinjaError("Set X1_API_KEY in your local environment first.")
        if any(ord(char) < 33 or ord(char) > 126 for char in self._key):
            raise NinjaError("X1_API_KEY contains invalid characters.")
        self._opener = build_opener(NoRedirect())

    def pools(self, limit: int = 10) -> dict:
        if not 1 <= limit <= 100:
            raise NinjaError("Pool list limit must be between 1 and 100.")
        result = self._get(f"/v1/pools?limit={limit}")
        if not isinstance(result.get("pools"), list):
            raise NinjaError("Pool list response is missing the pools array.")
        return result

    def pool(self, address: str) -> dict:
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address):
            raise NinjaError("Pool address must be an SVM base58 address.")
        return self._get(f"/v1/pools/{address}")

    def _get(self, path: str) -> dict:
        request = Request(
            "https://api.x1.ninja" + path,
            headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                result = json.load(response)
        except HTTPError as exc:
            messages = {
                401: "API key was rejected.",
                403: "API key does not have access to this endpoint.",
                429: "API rate limit reached; wait before trying again.",
                503: "API upstream is unavailable; try again later.",
            }
            raise NinjaError(messages.get(exc.code, f"API returned HTTP {exc.code}.")) from None
        except (URLError, OSError):
            raise NinjaError("Unable to reach X1.Ninja within the request timeout.") from None
        except (ValueError, UnicodeError):
            raise NinjaError("API returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise NinjaError("API returned an unexpected response structure.")
        return result
