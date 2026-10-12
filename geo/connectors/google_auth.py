"""Google access tokens: either GOOGLE_ACCESS_TOKEN, or a service-account key via the optional google-auth package."""
from __future__ import annotations

from .base import ConnectorError, REQUIRES_CREDENTIALS, UNSUPPORTED_OR_UNAVAILABLE

GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def has_google_credentials(config) -> bool:
    return bool(config.get("GOOGLE_ACCESS_TOKEN") or config.get("GOOGLE_APPLICATION_CREDENTIALS"))


def get_access_token(config, scope: str) -> str:
    token = config.get("GOOGLE_ACCESS_TOKEN")
    if token:
        return token
    key_path = config.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_path:
        raise ConnectorError(REQUIRES_CREDENTIALS, "Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_ACCESS_TOKEN")
    try:
        from google.oauth2 import service_account  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
    except ImportError:
        raise ConnectorError(UNSUPPORTED_OR_UNAVAILABLE,
                             "Service-account auth needs `pip install google-auth requests`; or provide GOOGLE_ACCESS_TOKEN")
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=[scope])
    creds.refresh(Request())
    return creds.token
