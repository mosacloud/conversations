"""
HTTP-level tests for ScaiMatrixRagBackend.

Mocks the ScaiMatrix REST API at the wire level (`responses` for the sync
`requests` paths) and exercises the real backend class. Verifies:

- create_collection binds the returned id and posts the configured embedding /
  chunking settings
- store_document uploads markdown, then polls until the document is `indexed`
  (pending -> indexed), and returns the backend document id
- store_document raises on a terminal ingestion error state
- search fans out across the managed collection + read-only collections and
  merges results by score, capped to results_count
- search applies client-side document_id / document_name scoping
- delete_document / delete_collection hit the right URLs
"""

import json

import pytest
import responses
import respx
from httpx import Response

from chat.agent_rag.document_rag_backends.scaimatrix_rag_backend import (
    ScaiMatrixIndexingError,
    ScaiMatrixRagBackend,
)

BASE_URL = "https://scaimatrix.test"
COLLECTIONS_URL = f"{BASE_URL}/v1/modules/scaimatrix/collections"


@pytest.fixture(name="settings_scaimatrix")
def settings_scaimatrix_fixture(settings):
    """Point the backend at a test API with a fast poll cadence."""
    settings.SCAIMATRIX_API_URL = BASE_URL
    settings.SCAIMATRIX_API_KEY = "test-key"
    settings.SCAIMATRIX_EMBEDDING_MODEL = "mistralai/mistral-embed"
    settings.SCAIMATRIX_CHUNKING_STRATEGY = "semantic"
    settings.SCAIMATRIX_CHUNK_SIZE = 800
    settings.SCAIMATRIX_CHUNK_OVERLAP = 100
    settings.SCAIMATRIX_SEARCH_TYPE = "vector"
    settings.SCAIMATRIX_INDEX_POLL_TIMEOUT = 10
    settings.SCAIMATRIX_INDEX_POLL_INTERVAL = 0
    return settings


def _envelope(data):
    return {"status": "success", "data": data}


def _search_response(results):
    return _envelope({"results": results, "total": len(results)})


# -- create_collection -------------------------------------------------------


@responses.activate
def test_create_collection_binds_id_and_sends_config(settings_scaimatrix):
    responses.post(COLLECTIONS_URL, json=_envelope({"id": "col-1"}), status=201)

    backend = ScaiMatrixRagBackend()
    collection_id = backend.create_collection(name="conversation-42")

    assert collection_id == "col-1"
    assert backend.collection_id == "col-1"
    payload = json.loads(responses.calls[0].request.body)
    assert payload["name"] == "conversation-42"
    assert payload["embedding_model"] == "mistralai/mistral-embed"
    assert payload["chunking_strategy"] == "semantic"
    assert payload["graph_enabled"] is False
    assert payload["default_access"] == "restricted"


# -- store_document ----------------------------------------------------------


@responses.activate
def test_store_document_uploads_and_polls_until_indexed(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    docs_url = f"{COLLECTIONS_URL}/col-1/documents"

    responses.post(docs_url, json=_envelope({"id": "doc-9", "status": "pending"}), status=201)
    # First poll still pending, second poll indexed.
    responses.get(f"{docs_url}/doc-9", json=_envelope({"status": "pending"}), status=200)
    responses.get(f"{docs_url}/doc-9", json=_envelope({"status": "indexed"}), status=200)

    document_id = backend.store_document(name="Report", content="# Report\n\nbody")

    assert document_id == "doc-9"
    upload = responses.calls[0].request
    assert upload.url == docs_url
    # multipart body carries the markdown filename and the document_name metadata
    body = upload.body.decode("utf-8", "ignore") if isinstance(upload.body, bytes) else upload.body
    assert "Report.md" in body
    assert "document_name" in body


@responses.activate
def test_parse_and_store_uploads_raw_file_and_returns_empty_parsed(settings_scaimatrix):
    """Raw bytes go straight to ScaiMatrix (native parse); parsed_content is empty."""
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    docs_url = f"{COLLECTIONS_URL}/col-1/documents"

    responses.post(docs_url, json=_envelope({"id": "doc-7", "status": "pending"}), status=201)
    responses.get(f"{docs_url}/doc-7", json=_envelope({"status": "indexed"}), status=200)

    parsed, document_id = backend.parse_and_store_document(
        name="sla.pdf", content_type="application/pdf", content=b"%PDF-1.4 ..."
    )

    assert parsed == ""
    assert document_id == "doc-7"
    body = responses.calls[0].request.body
    body = body.decode("utf-8", "ignore") if isinstance(body, bytes) else body
    # the original filename is used, not a .md-wrapped name
    assert "sla.pdf" in body
    assert "sla.pdf.md" not in body


@responses.activate
def test_parse_and_store_without_collection_raises(settings_scaimatrix):
    backend = ScaiMatrixRagBackend()
    with pytest.raises(RuntimeError, match="collection_id"):
        backend.parse_and_store_document(name="x", content_type="text/plain", content=b"x")


@responses.activate
def test_store_document_raises_on_terminal_error(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    docs_url = f"{COLLECTIONS_URL}/col-1/documents"

    responses.post(docs_url, json=_envelope({"id": "doc-9", "status": "pending"}), status=201)
    responses.get(
        f"{docs_url}/doc-9",
        json=_envelope({"status": "failed", "error_message": "bad file"}),
        status=200,
    )

    with pytest.raises(ScaiMatrixIndexingError, match="bad file"):
        backend.store_document(name="Report", content="x")


# -- search ------------------------------------------------------------------


@responses.activate
def test_search_merges_collections_and_sorts_by_score(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(
        collection_id="col-1", read_only_collection_id=["col-2"]
    )
    responses.post(
        f"{COLLECTIONS_URL}/col-1/search",
        json=_search_response(
            [{"document_id": "d1", "document_name": "a.md", "content": "A", "score": 0.4}]
        ),
        status=200,
    )
    responses.post(
        f"{COLLECTIONS_URL}/col-2/search",
        json=_search_response(
            [{"document_id": "d2", "document_name": "b.md", "content": "B", "score": 0.9}]
        ),
        status=200,
    )

    result = backend.search("q", results_count=4)

    assert [r.url for r in result.data] == ["b.md", "a.md"]  # sorted by score desc
    assert result.data[0].score == 0.9
    assert result.usage.prompt_tokens == 0


@responses.activate
def test_search_caps_to_results_count(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    responses.post(
        f"{COLLECTIONS_URL}/col-1/search",
        json=_search_response(
            [
                {"document_id": f"d{i}", "document_name": f"{i}.md", "content": "x", "score": i / 10}
                for i in range(6)
            ]
        ),
        status=200,
    )

    result = backend.search("q", results_count=2)

    assert len(result.data) == 2
    assert [r.score for r in result.data] == [0.5, 0.4]


@responses.activate
def test_search_filters_by_document_id(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    responses.post(
        f"{COLLECTIONS_URL}/col-1/search",
        json=_search_response(
            [
                {"document_id": "d1", "document_name": "a.md", "content": "A", "score": 0.8},
                {"document_id": "d2", "document_name": "b.md", "content": "B", "score": 0.9},
            ]
        ),
        status=200,
    )

    result = backend.search("q", document_id="d1")

    assert len(result.data) == 1
    assert result.data[0].url == "a.md"


@responses.activate
def test_search_without_collection_raises(settings_scaimatrix):
    backend = ScaiMatrixRagBackend()  # no collection bound
    with pytest.raises(RuntimeError, match="collection_id"):
        backend.search("q")


# -- deletes -----------------------------------------------------------------


@responses.activate
def test_delete_document_hits_document_url(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    url = f"{COLLECTIONS_URL}/col-1/documents/doc-9"
    responses.delete(url, json=_envelope({"deleted": True}), status=200)

    backend.delete_document("doc-9")

    assert responses.calls[0].request.url == url


@responses.activate
def test_delete_collection_hits_collection_url(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    url = f"{COLLECTIONS_URL}/col-1"
    responses.delete(url, json=_envelope({"deleted": True}), status=200)

    backend.delete_collection()

    assert responses.calls[0].request.url == url


# -- async paths (used by the live chat flow) --------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_astore_document_uploads_and_polls(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(collection_id="col-1")
    docs_url = f"{COLLECTIONS_URL}/col-1/documents"

    respx.post(docs_url).mock(
        return_value=Response(201, json=_envelope({"id": "doc-9", "status": "pending"}))
    )
    respx.get(f"{docs_url}/doc-9").mock(
        side_effect=[
            Response(200, json=_envelope({"status": "pending"})),
            Response(200, json=_envelope({"status": "indexed"})),
        ]
    )

    document_id = await backend.astore_document(name="Report", content="# Report")

    assert document_id == "doc-9"


@pytest.mark.asyncio
@respx.mock
async def test_asearch_merges_and_sorts(settings_scaimatrix):
    backend = ScaiMatrixRagBackend(
        collection_id="col-1", read_only_collection_id=["col-2"]
    )
    respx.post(f"{COLLECTIONS_URL}/col-1/search").mock(
        return_value=Response(
            200,
            json=_search_response(
                [{"document_id": "d1", "document_name": "a.md", "content": "A", "score": 0.4}]
            ),
        )
    )
    respx.post(f"{COLLECTIONS_URL}/col-2/search").mock(
        return_value=Response(
            200,
            json=_search_response(
                [{"document_id": "d2", "document_name": "b.md", "content": "B", "score": 0.9}]
            ),
        )
    )

    result = await backend.asearch("q", results_count=4)

    assert [r.url for r in result.data] == ["b.md", "a.md"]
    assert result.usage.prompt_tokens == 0
