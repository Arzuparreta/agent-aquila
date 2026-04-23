"""Google Sheets/Docs OAuth scope → provider mapping."""

from __future__ import annotations

from app.services.oauth import google_oauth


def test_provider_ids_for_scopes_includes_sheets_and_docs() -> None:
    scopes = [
        "openid",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
    ids = google_oauth.provider_ids_for_scopes(scopes)
    assert "google_sheets" in ids
    assert "google_docs" in ids


def test_scopes_for_intent_all_includes_sheets_docs_scopes() -> None:
    scopes = google_oauth.scopes_for_intent("all")
    joined = " ".join(scopes)
    assert "/auth/spreadsheets" in joined
    assert "/auth/documents" in joined


def test_scopes_for_intent_sheets_only() -> None:
    scopes = google_oauth.scopes_for_intent("sheets")
    assert any("spreadsheets" in s for s in scopes)
    assert not any("documents" in s for s in scopes)


def test_scopes_for_intent_docs_only() -> None:
    scopes = google_oauth.scopes_for_intent("docs")
    assert any("documents" in s for s in scopes)
