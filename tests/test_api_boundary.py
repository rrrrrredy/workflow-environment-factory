from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from workflow_environment_factory.app import create_app


def test_api_is_loopback_session_protected(services) -> None:
    app = create_app(services)
    token = services.settings.token_path.read_text(encoding="utf-8").strip()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/meta").status_code == 401
        authorized = client.get("/api/meta", headers={"authorization": f"Bearer {token}"})
        assert authorized.status_code == 200
        assert authorized.json()["engine"] == "local-test-only"
        synthetic_run = json.loads(
            Path(__file__).with_name("fixtures").joinpath("agent.run.synthetic.json").read_text(encoding="utf-8")
        )
        assert client.post("/api/protocol/imports", json={"document": synthetic_run}).status_code == 401
        session = client.get(f"/session/{token}", follow_redirects=False)
        assert session.status_code == 302
        cookie = session.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie

        imported = client.post(
            "/api/protocol/imports",
            headers={"authorization": f"Bearer {token}"},
            json={"document": synthetic_run},
        )
        assert imported.status_code == 201
        record = imported.json()
        assert record["schema_version"] == "agent.run.v1"
        assert record["document"]["events"][0]["data"]["api_token"] == "[REDACTED:secret-field]"
        repeated = client.post(
            "/api/protocol/imports",
            headers={"authorization": f"Bearer {token}"},
            json={"document": synthetic_run},
        )
        assert repeated.json()["document_id"] == record["document_id"]
        library = client.get("/api/protocol/imports", headers={"authorization": f"Bearer {token}"})
        assert len(library.json()["documents"]) == 1
