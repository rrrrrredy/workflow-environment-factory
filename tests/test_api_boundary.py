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


def test_import_preserves_usage_counts_and_requires_an_observation_gap(services):
    app = create_app(services)
    headers = {"authorization": "Bearer " + services.settings.token_path.read_text().strip()}
    doc = json.loads((Path(__file__).parent / "fixtures/agent.run.synthetic.json").read_text())
    doc["resource_usage"].update(input_tokens=17, output_tokens=0, cached_input_tokens=3)
    doc["events"][0]["data"]["input_tokens"] = "private"
    doc["capture"]["sources"][0]["status"] = "unavailable"
    with TestClient(app) as client:
        imported = client.post("/api/protocol/imports", headers=headers, json={"document": doc})
        assert imported.status_code == 201, imported.text
        stored = imported.json()["document"]
        assert stored["resource_usage"] == doc["resource_usage"]
        assert stored["events"][0]["data"]["input_tokens"] == "[REDACTED:secret-field]"
        doc["capture"]["gaps"].clear()
        assert client.post("/api/protocol/imports", headers=headers, json={"document": doc}).status_code == 422


def test_protocol_date_time_and_uri_formats(services):
    from workflow_environment_factory.protocol import FORMAT_CHECKER

    for value in ["2024-02-29T23:59:59Z", "2017-01-01T00:59:60+01:00"]:
        assert FORMAT_CHECKER.conforms(value, "date-time")
    for value in ["yesterday", "2023-02-29T00:00:00Z", "2024-02-01T12:00:00", "2024-02-01T12:00:61Z"]:
        assert not FORMAT_CHECKER.conforms(value, "date-time")
    for value in ["urn:example:case", "https://[::1]/a%20b?q=x#ref", "file:///tmp/example"]:
        assert FORMAT_CHECKER.conforms(value, "uri")
    for value in ["relative/path", "https://bad host/", "https://host/%XY", "https://[missing/"]:
        assert not FORMAT_CHECKER.conforms(value, "uri")


def test_blocking_case_generation_leaves_health_responsive(services, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from uuid import uuid4

    app = create_app(services)
    headers = {"authorization": "Bearer " + services.settings.token_path.read_text().strip()}
    entering, release = Event(), Event()

    def generate(_):
        entering.set()
        assert release.wait(8)
        return []

    monkeypatch.setattr(services.factory, "generate_cases", generate)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(client.post, f"/api/blueprints/{uuid4()}/generate", headers=headers)
        try:
            assert entering.wait(4)
            assert pool.submit(client.get, "/health").result(timeout=3).status_code == 200
        finally:
            release.set()
        assert request.result().is_success
