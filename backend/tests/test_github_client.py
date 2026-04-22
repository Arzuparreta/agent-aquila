"""GitHubClient — mocked HTTP (no real PAT)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.connectors import github_client as gh_mod
from app.services.connectors.github_client import GitHubClient


@pytest.mark.asyncio
async def test_get_authenticated_user_returns_dict() -> None:
    sample = {"login": "octocat", "id": 1}

    async def on_request(method, url, *, params=None, json=None, headers=None):
        assert method == "GET"
        assert str(url).endswith("/user") or "/user" in str(url)
        return httpx.Response(200, json=sample)

    mock_inner = MagicMock()
    mock_inner.request = AsyncMock(side_effect=on_request)

    class _ACM:
        async def __aenter__(self):
            return mock_inner

        async def __aexit__(self, *args):
            return None

    with patch.object(gh_mod.httpx, "AsyncClient", return_value=_ACM()):
        g = GitHubClient("pat-test-token")
        out = await g.get_authenticated_user()
    assert out == sample


@pytest.mark.asyncio
async def test_list_user_repos_returns_json_list() -> None:
    sample = [{"id": 1, "name": "hello", "full_name": "acme/hello"}]

    async def on_request(method, url, *, params=None, json=None, headers=None):
        assert "/user/repos" in str(url)
        return httpx.Response(200, json=sample)

    mock_inner = MagicMock()
    mock_inner.request = AsyncMock(side_effect=on_request)

    class _ACM:
        async def __aenter__(self):
            return mock_inner

        async def __aexit__(self, *args):
            return None

    with patch.object(gh_mod.httpx, "AsyncClient", return_value=_ACM()):
        g = GitHubClient("pat-test-token")
        out = await g.list_user_repos(page=1, per_page=10)
    assert out == sample
