"""YouTube Data API v3 — thin REST client."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://www.googleapis.com/youtube/v3"


class YoutubeAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"YouTube API {status_code}: {detail[:500]}")


class YoutubeClient:
    def __init__(self, access_token: str, *, timeout: float = 60.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise YoutubeAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise YoutubeAPIError(503, "YouTube API retries exhausted")

    async def list_my_channels(self, *, page_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"part": "snippet,contentDetails,statistics", "mine": "true"}
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/channels", params=params)

    async def list_playlist_items(
        self,
        playlist_id: str,
        *,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(max(1, max_results), 50),
        }
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/playlistItems", params=params)

    async def list_playlists(
        self,
        channel_id: str,
        *,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "channelId": channel_id,
            "maxResults": min(max(1, max_results), 50),
        }
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/playlists", params=params)

    async def search_videos(
        self,
        *,
        channel_id: str | None = None,
        q: str | None = None,
        page_token: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "maxResults": min(max(1, max_results), 50),
        }
        if channel_id:
            params["channelId"] = channel_id
        if q:
            params["q"] = q
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/search", params=params)

    async def list_videos(
        self,
        video_ids: list[str],
        *,
        parts: str = "snippet,contentDetails,statistics,status",
    ) -> dict[str, Any]:
        if not video_ids:
            return {"items": []}
        # API allows up to 50 ids per request
        chunk = video_ids[:50]
        params = {"part": parts, "id": ",".join(chunk)}
        return await self._request("GET", "/videos", params=params)

    async def update_video_snippet(
        self,
        video_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        cur = await self.list_videos([video_id], parts="snippet")
        items = cur.get("items") or []
        if not items:
            raise YoutubeAPIError(404, f"video not found: {video_id}")
        snippet = dict((items[0].get("snippet") or {}))
        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        if category_id is not None:
            snippet["categoryId"] = category_id
        body = {"id": video_id, "snippet": snippet}
        return await self._request(
            "PUT",
            "/videos?part=snippet",
            params=None,
            json_body=body,
        )

    async def resumable_upload_video(
        self,
        *,
        title: str,
        description: str,
        video_bytes: bytes,
        mime_type: str = "video/mp4",
        privacy_status: str = "private",
    ) -> dict[str, Any]:
        """Upload bytes via resumable protocol (quota-heavy)."""
        upload_url = "https://www.googleapis.com/upload/youtube/v3/videos"
        meta: dict[str, Any] = {
            "snippet": {"title": title[:100], "description": description[:5000]},
            "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
        }
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.post(
                upload_url,
                params={"uploadType": "resumable", "part": "snippet,status"},
                json=meta,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Upload-Content-Length": str(len(video_bytes)),
                    "X-Upload-Content-Type": mime_type,
                },
            )
        if r.status_code not in (200, 201):
            raise YoutubeAPIError(r.status_code, r.text)
        location = r.headers.get("Location")
        if not location:
            raise YoutubeAPIError(r.status_code, "resumable upload missing Location header")
        async with httpx.AsyncClient(timeout=600.0) as client:
            r2 = await client.put(
                location,
                content=video_bytes,
                headers={"Content-Length": str(len(video_bytes)), "Content-Type": mime_type},
            )
        if r2.status_code >= 400:
            raise YoutubeAPIError(r2.status_code, r2.text)
        if not r2.content:
            return {}
        return r2.json()
