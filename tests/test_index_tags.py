from copy import deepcopy

import pytest

from app.api.routes import index as index_route
from app.api.schemas.index import IndexRequest
from app.rag.index import store_pg


class FakeStore:
    instances: list["FakeStore"] = []

    def __init__(self) -> None:
        self.rebuilt = False
        self.documents: list[dict] = []
        self.chunk_batches: list[list[dict]] = []
        self.__class__.instances.append(self)

    def rebuild(self) -> None:
        self.rebuilt = True

    def ensure_schema(self) -> None:
        return None

    def upsert_document(self, **document: object) -> None:
        self.documents.append(document)

    def upsert_chunks(self, *, doc_id: str, chunks: list[dict]) -> None:
        assert doc_id
        self.chunk_batches.append(deepcopy(chunks))


@pytest.fixture(autouse=True)
def reset_fake_store() -> None:
    FakeStore.instances.clear()


def test_index_request_tags_defaults_to_independent_empty_lists() -> None:
    first = IndexRequest()
    second = IndexRequest()

    assert first.tags == []
    assert second.tags == []
    assert first.tags is not second.tags


def test_index_request_preserves_explicit_tags() -> None:
    assert IndexRequest(tags=["mdn_http"]).tags == ["mdn_http"]


@pytest.mark.asyncio
async def test_index_route_forwards_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_load_jsonl_records(path: str) -> list[dict]:
        captured["path"] = path
        return [{"doc_id": "doc-1", "text": "body"}]

    async def fake_index_records_to_pg(
        records: list[dict],
        *,
        rebuild: bool,
        tags: list[str] | None = None,
    ) -> tuple[int, int]:
        captured["records"] = records
        captured["rebuild"] = rebuild
        captured["tags"] = tags
        return 1, 1

    monkeypatch.setattr(index_route, "load_jsonl_records", fake_load_jsonl_records)
    monkeypatch.setattr(index_route, "index_records_to_pg", fake_index_records_to_pg)

    response = await index_route.index_documents(
        IndexRequest(path="/tmp/input.jsonl", tags=["mdn_http"])
    )

    assert response.docs == 1
    assert response.chunks == 1
    assert captured["path"] == "/tmp/input.jsonl"
    assert captured["rebuild"] is False
    assert captured["tags"] == ["mdn_http"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_tags", "expected_tags"),
    [
        (["mdn_http"], ["mdn_http"]),
        (None, []),
    ],
)
async def test_index_records_stores_requested_or_default_tags(
    monkeypatch: pytest.MonkeyPatch,
    requested_tags: list[str] | None,
    expected_tags: list[str],
) -> None:
    async def fake_embed_chunks(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(store_pg, "PgVectorStore", FakeStore)
    monkeypatch.setattr(store_pg, "embed_chunks", fake_embed_chunks)
    monkeypatch.setattr(store_pg, "extract_keywords", lambda text, limit: ["keyword"])

    docs, chunks = await store_pg.index_records_to_pg(
        [{"doc_id": "doc-1", "title": "title", "text": "first\n\nsecond"}],
        rebuild=False,
        tags=requested_tags,
    )

    assert (docs, chunks) == (1, 2)
    stored_chunks = FakeStore.instances[-1].chunk_batches[0]
    assert [chunk["tags"] for chunk in stored_chunks] == [
        expected_tags,
        expected_tags,
    ]
    assert stored_chunks[0]["tags"] is not stored_chunks[1]["tags"]
