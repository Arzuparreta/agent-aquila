"""iCloud contacts client — vCard parse + XML helpers (no live Apple)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.connectors import icloud_contacts_client as mod


def test_parse_vcard_simple_extracts_fn_email_tel() -> None:
    raw = """BEGIN:VCARD
VERSION:3.0
UID:abc-1
FN:Jane Doe
EMAIL;TYPE=INTERNET:jane@example.com
TEL;TYPE=CELL:+1-555-0100
END:VCARD
"""
    p = mod._parse_vcard_simple(raw)
    assert p["name"] == "Jane Doe"
    assert "jane@example.com" in p["emails"]
    assert any("555" in t for t in p["phones"])


def test_first_href_under_finds_principal() -> None:
    xml = """<?xml version="1.0"?>
<multistatus xmlns="DAV:">
  <response>
    <propstat>
      <prop>
        <current-user-principal>
          <href>/123456/principal/</href>
        </current-user-principal>
      </prop>
    </propstat>
  </response>
</multistatus>
"""
    root = ET.fromstring(xml)
    href = mod._first_href_under(root, "current-user-principal")
    assert href == "/123456/principal/"
