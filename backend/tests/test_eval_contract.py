from fastapi.testclient import TestClient

from app.main import app


def test_eval_run_returns_initial_metrics_shape() -> None:
    client = TestClient(app)

    response = client.post("/eval/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["eval_run_id"].startswith("EVAL_")
    assert payload["status"] == "RECEIVED"
    assert payload["metrics"]["total_cases"] == 12
    assert payload["metrics"]["completed_cases"] == 0
    assert payload["cases"] == []


def test_latest_eval_returns_eval_shape() -> None:
    client = TestClient(app)

    response = client.get("/eval/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["eval_run_id"].startswith("EVAL_")
    assert payload["metrics"]["total_cases"] == 12

