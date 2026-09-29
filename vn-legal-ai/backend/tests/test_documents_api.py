from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import documents as api
from app.core.db import get_session


def client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router, prefix="/v1")

    async def no_db():
        yield None  # 검증 단계에서 막히므로 DB에 닿지 않는다

    app.dependency_overrides[get_session] = no_db
    return TestClient(app)


def test_paste_text_too_short_is_rejected():
    r = client().post("/v1/documents", data={"text": "short", "title": "x"})
    assert r.status_code == 422 and "30 characters" in r.json()["detail"]


def test_upload_needs_file_or_text_but_not_both():
    c = client()
    assert c.post("/v1/documents", data={"lang": "en"}).status_code == 422
    r = c.post("/v1/documents", data={"text": "a" * 40}, files={"file": ("a.txt", b"hello world " * 5, "text/plain")})
    assert r.status_code == 422 and "not both" in r.json()["detail"]


def test_facts_patch_rejects_unknown_shape():
    r = client().patch("/v1/documents/00000000-0000-0000-0000-000000000000/facts", json={"facts": [{"key": "amount"}]})
    assert r.status_code == 422  # value 누락
