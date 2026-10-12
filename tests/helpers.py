import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo import db  # noqa: E402
from geo.config import Config  # noqa: E402
from geo.connectors.base import HttpResponse  # noqa: E402


class FakeTransport:
    """Routes (method, url-prefix) -> HttpResponse or Exception. Records calls. Test-only."""

    user_agent = "TestUA"

    def __init__(self, routes=None, default=None):
        self.routes = routes or []
        self.default = default
        self.calls = []

    def add(self, method, prefix, status=200, body=None, headers=None, exc=None):
        self.routes.append((method, prefix, status, body, headers or {}, exc))
        return self

    def request(self, method, url, headers=None, params=None, json_body=None, data=None, follow_redirects=True):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params, "json": json_body})
        for m, prefix, status, body, hdrs, exc in self.routes:
            if m == method and url.startswith(prefix):
                if exc:
                    raise exc
                raw = body if isinstance(body, (bytes, str)) else json.dumps(body)
                return HttpResponse(status, raw.encode() if isinstance(raw, str) else raw, hdrs)
        if self.default:
            raise self.default
        return HttpResponse(404, b"not found", {})


def make_config(**env):
    base = {"GEO_SITE_URL": "https://mujassam.net/", "GEO_CRAWL_DELAY_SECONDS": "0"}
    base.update(env)
    return Config(env=base)


def mem_db():
    return db.connect(":memory:")


def tmpdir():
    return Path(tempfile.mkdtemp())
