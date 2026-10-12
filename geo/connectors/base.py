"""Connector base: status vocabulary, HTTP transport (injectable for tests), honest health reporting.

A connector is only CONNECTED_AND_TESTED after a real authorised request returned success.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..config import Config
from .. import db

CONNECTED_AND_TESTED = "CONNECTED_AND_TESTED"
CONFIGURED_NOT_TESTED = "CONFIGURED_NOT_TESTED"
REQUIRES_CREDENTIALS = "REQUIRES_CREDENTIALS"
REQUIRES_PERMISSION = "REQUIRES_PERMISSION"
UNSUPPORTED_OR_UNAVAILABLE = "UNSUPPORTED_OR_UNAVAILABLE"
FAILED_WITH_EVIDENCE = "FAILED_WITH_EVIDENCE"
STATUSES = (CONNECTED_AND_TESTED, CONFIGURED_NOT_TESTED, REQUIRES_CREDENTIALS, REQUIRES_PERMISSION,
            UNSUPPORTED_OR_UNAVAILABLE, FAILED_WITH_EVIDENCE)


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict = field(default_factory=dict)

    def json(self):
        return json.loads(self.body.decode("utf-8") or "null")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Transport:
    """Thin urllib wrapper. Tests replace it with a fake; never mocked in production."""

    def __init__(self, user_agent: str = "MujassamGEO/1.0", timeout: int = 30):
        self.user_agent = user_agent
        self.timeout = timeout

    def request(self, method: str, url: str, headers: dict | None = None, params: dict | None = None,
                json_body=None, data: bytes | None = None, follow_redirects: bool = True) -> HttpResponse:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        hdrs = {"User-Agent": self.user_agent, **(headers or {})}
        if json_body is not None:
            data = json.dumps(json_body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        handlers = [] if follow_redirects else [_NoRedirect()]
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), *handlers)
        try:
            with opener.open(req, timeout=self.timeout) as r:
                return HttpResponse(r.status, r.read(), {k.lower(): v for k, v in r.headers.items()})
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, e.read() if e.fp else b"", {k.lower(): v for k, v in (e.headers or {}).items()})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class ConnectorError(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Connector:
    name = "base"
    required_env: tuple[str, ...] = ()
    docs_url = ""

    def __init__(self, config: Config, conn=None, transport: Transport | None = None):
        self.config = config
        self.conn = conn
        self.transport = transport or Transport(config.get("GEO_USER_AGENT", "MujassamGEO/1.0"))

    def missing_env(self) -> list[str]:
        return [k for k in self.required_env if not self.config.get(k)]

    def validate_config(self) -> tuple[str, str]:
        missing = self.missing_env()
        if missing:
            return REQUIRES_CREDENTIALS, "Missing: " + ", ".join(missing) + f" (see docs/SETUP_INTEGRATIONS.md, {self.docs_url})"
        return CONFIGURED_NOT_TESTED, "Configuration present; not yet verified by a live request."

    def test(self) -> tuple[str, str]:
        """Perform one real, cheap, authorised request. Subclasses override `_probe`."""
        status, detail = self.validate_config()
        if status != CONFIGURED_NOT_TESTED:
            self._record(status, detail)
            return status, detail
        try:
            detail = self._probe()
            self._record(CONNECTED_AND_TESTED, detail, success=True)
            return CONNECTED_AND_TESTED, detail
        except ConnectorError as e:
            d = self.config.redact(e.detail)
            self._record(e.status, d, error=d)
            return e.status, d
        except Exception as e:  # network errors, DNS, proxy denials
            d = self.config.redact(f"{type(e).__name__}: {e}")
            self._record(FAILED_WITH_EVIDENCE, d, error=d)
            return FAILED_WITH_EVIDENCE, d

    def _probe(self) -> str:
        raise ConnectorError(UNSUPPORTED_OR_UNAVAILABLE, "No probe implemented")

    def _record(self, status, detail, success=False, error=None):
        if self.conn is not None:
            db.set_health(self.conn, self.name, status, detail, success=success, error=error)

    @staticmethod
    def classify_http(resp: HttpResponse, context: str) -> None:
        if 200 <= resp.status < 300:
            return
        snippet = resp.text[:300]
        if resp.status in (401,):
            raise ConnectorError(REQUIRES_CREDENTIALS, f"{context}: HTTP 401 (invalid/expired credentials): {snippet}")
        if resp.status == 403:
            raise ConnectorError(REQUIRES_PERMISSION, f"{context}: HTTP 403 (no permission on this resource): {snippet}")
        if resp.status == 429:
            raise ConnectorError(FAILED_WITH_EVIDENCE, f"{context}: HTTP 429 (quota/rate limit): {snippet}")
        raise ConnectorError(FAILED_WITH_EVIDENCE, f"{context}: HTTP {resp.status}: {snippet}")
