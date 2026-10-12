"""Configuration loading, validation and secret redaction.

Secrets are read from the environment (optionally from a local .env file) and are
never printed. `redact()` must wrap anything that might contain a secret before logging.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_KEYS = {
    "GOOGLE_ACCESS_TOKEN",
    "CLARITY_API_TOKEN",
    "BING_WEBMASTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "ANTHROPIC_API_KEY",
}


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: does not override variables already set."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    env: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, use_dotenv: bool = True) -> "Config":
        if use_dotenv:
            load_dotenv()
        return cls(env=dict(os.environ))

    def get(self, key: str, default: str = "") -> str:
        return (self.env.get(key) or default).strip()

    def flag(self, key: str) -> bool:
        return self.get(key).lower() in {"1", "true", "yes", "on"}

    @property
    def db_path(self) -> Path:
        p = Path(self.get("GEO_DB_PATH", "var/geo.sqlite3"))
        return p if p.is_absolute() else ROOT / p

    @property
    def site_url(self) -> str:
        return self.get("GEO_SITE_URL", "https://mujassam.net/")

    def secret_values(self) -> list[str]:
        return [self.env[k] for k in SECRET_KEYS if self.env.get(k) and len(self.env[k]) >= 6]

    def redact(self, text: str) -> str:
        return redact(text, self.secret_values())


_TOKEN_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|access_token|apikey|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,}]{4,}"),
    re.compile(r"ya29\.[A-Za-z0-9._\-]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str, known_secrets: list[str] | None = None) -> str:
    if text is None:
        return text
    out = str(text)
    for s in known_secrets or []:
        out = out.replace(s, "***REDACTED***")
    for pat in _TOKEN_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + "***REDACTED***", out)
        else:
            out = pat.sub("***REDACTED***", out)
    return out
