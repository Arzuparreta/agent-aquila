from __future__ import annotations


class OAuthError(Exception):
    """Raised when the OAuth exchange or refresh fails for a reason other than invalid user input."""


class ConnectorNeedsReauth(OAuthError):
    """Raised when a stored refresh token is no longer valid (revoked / expired).

    Callers should surface a reconnect banner in the UI instead of retrying blindly.
    """

    def __init__(self, connection_id: int | None, provider: str, detail: str) -> None:
        self.connection_id = connection_id
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} connection needs re-auth: {detail}")
