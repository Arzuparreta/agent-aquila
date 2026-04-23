"""iCloud CardDAV contacts — list/search via app-specific password (read-only)."""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin

import httpx


class ICloudContactsError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"iCloud Contacts {status_code}: {detail[:500]}")


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _first_href_under(root: ET.Element, parent_local: str) -> str | None:
    """Return first ``href`` text inside an element whose local name is ``parent_local``."""
    for node in root.iter():
        if _local_tag(node.tag) != parent_local:
            continue
        for child in node.iter():
            if _local_tag(child.tag) == "href" and (child.text or "").strip():
                return child.text.strip()
    return None


def _response_hrefs_for_multistatus(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    out: list[str] = []
    for node in root.iter():
        if _local_tag(node.tag) != "response":
            continue
        for child in node.iter():
            if _local_tag(child.tag) == "href" and (child.text or "").strip():
                out.append(child.text.strip())
                break
    return out


def _unfold_vcard_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        if not line:
            continue
        if lines and (line.startswith(" ") or line.startswith("\t")):
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _parse_vcard_simple(raw: str) -> dict[str, Any]:
    """Extract FN, EMAIL, TEL from a vCard 3/4 body (best-effort)."""
    lines = _unfold_vcard_lines(raw)
    fn = ""
    emails: list[str] = []
    phones: list[str] = []
    uid = ""
    for line in lines:
        u = line.upper()
        if u.startswith("FN:"):
            fn = line[3:].strip()
        elif u.startswith("FN;"):
            m = re.search(r":(.+)$", line)
            if m:
                fn = m.group(1).strip()
        elif u.startswith("UID:"):
            uid = line[4:].strip()
        elif u.startswith("EMAIL") and ":" in line:
            emails.append(line.split(":", 1)[1].strip())
        elif u.startswith("TEL") and ":" in line:
            phones.append(line.split(":", 1)[1].strip())
    return {
        "uid": uid or None,
        "name": fn or None,
        "emails": emails,
        "phones": phones,
    }


_PROPFIND_PRINCIPAL = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:current-user-principal/>
  </d:prop>
</d:propfind>"""

_PROPFIND_HOME = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <card:addressbook-home-set/>
  </d:prop>
</d:propfind>"""

_PROPFIND_LIST = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:getcontenttype/>
  </d:prop>
</d:propfind>"""


def _base_url(china_mainland: bool) -> str:
    if china_mainland:
        return "https://contacts.icloud.com.cn"
    return "https://contacts.icloud.com"


class ICloudContactsClient:
    def __init__(
        self,
        username: str,
        app_password: str,
        *,
        china_mainland: bool = False,
        timeout: float = 60.0,
    ) -> None:
        self._user = username.strip()
        self._password = app_password
        self._base = _base_url(china_mainland).rstrip("/")
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(
            auth=(self._user, self._password),
            timeout=self._timeout,
            follow_redirects=True,
        )

    def _propfind(self, client: httpx.Client, url: str, body: str, depth: str) -> str:
        r = client.request(
            "PROPFIND",
            url,
            content=body.encode("utf-8"),
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "Depth": depth,
            },
        )
        if r.status_code >= 400:
            raise ICloudContactsError(r.status_code, r.text)
        return r.text

    def _get_text(self, client: httpx.Client, url: str) -> str:
        r = client.get(url)
        if r.status_code >= 400:
            raise ICloudContactsError(r.status_code, r.text)
        return r.text

    def _discover_addressbook_url(self, client: httpx.Client) -> str:
        xml1 = self._propfind(client, f"{self._base}/", _PROPFIND_PRINCIPAL, "0")
        root1 = ET.fromstring(xml1)
        cup = _first_href_under(root1, "current-user-principal")
        if not cup:
            raise ICloudContactsError(500, "Could not discover current-user-principal for contacts")
        principal_url = urljoin(self._base + "/", cup)
        xml2 = self._propfind(client, principal_url, _PROPFIND_HOME, "0")
        root2 = ET.fromstring(xml2)
        home = _first_href_under(root2, "addressbook-home-set")
        if not home:
            raise ICloudContactsError(500, "Could not discover addressbook-home-set")
        home_url = urljoin(self._base + "/", home)
        xml3 = self._propfind(client, home_url, _PROPFIND_LIST, "1")
        hrefs = _response_hrefs_for_multistatus(xml3)
        for h in hrefs:
            if h.rstrip("/") == home_url.rstrip("/"):
                continue
            child_url = urljoin(self._base + "/", h)
            try:
                xml4 = self._propfind(client, child_url, _PROPFIND_LIST, "0")
            except ICloudContactsError:
                continue
            if "addressbook" in xml4.lower():
                return child_url
        raise ICloudContactsError(500, "No addressbook collection found under home set")

    def list_contacts_sync(self, *, max_results: int = 200) -> dict[str, Any]:
        max_results = max(1, min(max_results, 2000))

        def _run() -> dict[str, Any]:
            with self._client() as client:
                ab_url = self._discover_addressbook_url(client)
                xml_list = self._propfind(client, ab_url, _PROPFIND_LIST, "1")
                hrefs = _response_hrefs_for_multistatus(xml_list)
                vcard_hrefs: list[str] = []
                for h in hrefs:
                    if h.rstrip("/") == ab_url.rstrip("/"):
                        continue
                    low = h.lower()
                    if low.endswith(".vcf") or "/card/" in low or "vcard" in low:
                        vcard_hrefs.append(h)
                    else:
                        child = urljoin(self._base + "/", h)
                        try:
                            body = self._get_text(client, child)
                        except ICloudContactsError:
                            continue
                        if "BEGIN:VCARD" in body.upper():
                            vcard_hrefs.append(h)

                contacts: list[dict[str, Any]] = []
                for h in vcard_hrefs:
                    if len(contacts) >= max_results:
                        break
                    href_full = urljoin(self._base + "/", h)
                    try:
                        raw = self._get_text(client, href_full)
                    except ICloudContactsError:
                        continue
                    if "BEGIN:VCARD" not in raw.upper():
                        continue
                    parsed = _parse_vcard_simple(raw)
                    parsed["href"] = href_full
                    contacts.append(parsed)
                return {
                    "addressbook_url": ab_url,
                    "contacts": contacts,
                    "truncated": len(vcard_hrefs) > len(contacts),
                }

        try:
            return _run()
        except ICloudContactsError:
            raise
        except Exception as exc:
            raise ICloudContactsError(400, str(exc)) from exc

    def search_contacts_sync(self, query: str, *, max_results: int = 50) -> dict[str, Any]:
        q = (query or "").strip().lower()
        if not q:
            return {"error": "query is required", "contacts": []}
        all_rows = self.list_contacts_sync(max_results=500)
        contacts = all_rows.get("contacts") or []
        out: list[dict[str, Any]] = []
        for c in contacts:
            blob = " ".join(
                [
                    str(c.get("name") or ""),
                    " ".join(c.get("emails") or []),
                    " ".join(c.get("phones") or []),
                ]
            ).lower()
            if q in blob:
                out.append(c)
            if len(out) >= max_results:
                break
        return {"contacts": out, "query": query}


def verify_contacts_sync(
    username: str,
    password: str,
    *,
    china_mainland: bool = False,
    connection_id: int | None = None,
) -> dict[str, Any]:
    """Lightweight health probe: list at most one contact."""
    del connection_id
    client = ICloudContactsClient(username, password, china_mainland=china_mainland)
    data = client.list_contacts_sync(max_results=1)
    n = len(data.get("contacts") or [])
    return {"ok": True, "sample_contact_count": n}


async def list_contacts(
    username: str,
    password: str,
    *,
    china_mainland: bool = False,
    max_results: int = 200,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        ICloudContactsClient(username, password, china_mainland=china_mainland).list_contacts_sync,
        max_results=max_results,
    )


async def search_contacts(
    username: str,
    password: str,
    query: str,
    *,
    china_mainland: bool = False,
    max_results: int = 50,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        ICloudContactsClient(username, password, china_mainland=china_mainland).search_contacts_sync,
        query,
        max_results=max_results,
    )
