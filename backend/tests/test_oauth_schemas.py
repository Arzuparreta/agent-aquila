from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.oauth import GoogleOAuthAppCredentialsUpdate


def test_google_redirect_base_accepts_public_domain() -> None:
    payload = GoogleOAuthAppCredentialsUpdate(redirect_base="https://app.example.com")
    assert payload.redirect_base == "https://app.example.com"


def test_google_redirect_base_accepts_localhost() -> None:
    payload = GoogleOAuthAppCredentialsUpdate(redirect_base="http://localhost:3002")
    assert payload.redirect_base == "http://localhost:3002"


@pytest.mark.parametrize(
    "redirect_base",
    [
        "http://100.91.167.48:3002",
        "http://192.168.1.20:3002",
        "my-machine",
    ],
)
def test_google_redirect_base_rejects_non_public_hosts(redirect_base: str) -> None:
    with pytest.raises(ValidationError):
        GoogleOAuthAppCredentialsUpdate(redirect_base=redirect_base)
