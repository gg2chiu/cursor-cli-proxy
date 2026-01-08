from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_list_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
    assert data["data"][0]["object"] == "model"
    # Check that we have some IDs
    model_ids = [m["id"] for m in data["data"]]
    assert len(model_ids) > 0