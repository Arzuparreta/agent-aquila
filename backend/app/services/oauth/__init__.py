"""OAuth 2.0 flows for external connector providers (Google Workspace, Microsoft Graph, ...)."""

# Use relative imports and lazy ``TokenManager`` to avoid a circular import:
# ``oauth`` → ``token_manager`` → ``connector_service`` → ``oauth`` (incomplete).
from . import google_oauth, microsoft_oauth
from .base import OAuthProvider, get_provider, register_provider
from .errors import ConnectorNeedsReauth, OAuthError


def __getattr__(name: str):
    if name == "TokenManager":
        from .token_manager import TokenManager

        return TokenManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

register_provider(
    OAuthProvider(
        name="google",
        build_authorize_url=google_oauth.build_authorize_url,
        exchange_code=google_oauth.exchange_code,
        refresh_access_token=google_oauth.refresh_access_token,
        fetch_userinfo=google_oauth.fetch_userinfo,
        scopes_for_intent=google_oauth.scopes_for_intent,
        provider_ids_for_scopes=google_oauth.provider_ids_for_scopes,
        redirect_uri=google_oauth.redirect_uri,
        is_configured=google_oauth.is_configured,
        compute_expires_at=google_oauth.compute_expires_at,
    )
)
register_provider(
    OAuthProvider(
        name="microsoft",
        build_authorize_url=microsoft_oauth.build_authorize_url,
        exchange_code=microsoft_oauth.exchange_code,
        refresh_access_token=microsoft_oauth.refresh_access_token,
        fetch_userinfo=microsoft_oauth.fetch_userinfo,
        scopes_for_intent=microsoft_oauth.scopes_for_intent,
        provider_ids_for_scopes=microsoft_oauth.provider_ids_for_scopes,
        redirect_uri=microsoft_oauth.redirect_uri,
        is_configured=microsoft_oauth.is_configured,
        compute_expires_at=microsoft_oauth.compute_expires_at,
    )
)


__all__ = [
    "ConnectorNeedsReauth",
    "OAuthError",
    "OAuthProvider",
    "TokenManager",
    "get_provider",
]
