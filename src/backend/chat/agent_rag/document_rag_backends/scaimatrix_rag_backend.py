"""RAG backend backed by ScaiGrid's ScaiMatrix knowledge platform.

ScaiMatrix (``/v1/modules/scaimatrix/`` on the ScaiGrid API) is a sovereign
vector + graph knowledge service. This backend maps the RAG document lifecycle
(create collection, ingest, search, delete) onto its REST endpoints so that
conversation/project attachments can be indexed and searched without leaving
the ScaiGrid stack.

Three behaviours differ from :class:`AlbertRagBackend` and shape this code:

- **Asynchronous ingestion.** A stored document starts ``pending`` and moves
  ``pending -> processing -> chunking -> embedding -> indexed``. ``store_document``
  polls until the document reaches ``indexed`` (or a terminal error), so a search
  issued right after upload actually sees the content. Albert indexes inline.
- **Per-collection search.** ScaiMatrix scopes ``/search`` to a single collection
  in the URL, whereas Albert accepts a list of collections in one call. So
  :meth:`search` fans out over ``get_all_collection_ids`` and merges by score.
- **No server-side document filter.** ``/search`` has no ``document_ids`` /
  metadata filter, so ``document_id`` / ``document_name`` scoping is applied
  client-side on the merged results.
"""

import asyncio
import json
import logging
import time
from io import BytesIO
from typing import List, Optional
from urllib.parse import urljoin

from django.conf import settings
from django.utils.module_loading import import_string

import httpx
import requests

from chat.agent_rag.constants import RAGWebResult, RAGWebResults, RAGWebUsage
from chat.agent_rag.document_rag_backends.base_rag_backend import BaseRagBackend

logger = logging.getLogger(__name__)

# Document ingestion is async; these are the states we stop polling on.
_INDEXED_STATE = "indexed"
_TERMINAL_ERROR_STATES = {"failed", "error"}


class ScaiMatrixIndexingError(RuntimeError):
    """Raised when a ScaiMatrix document fails to reach the ``indexed`` state.

    Either the backend reported a terminal error state, or the document was
    still not indexed when the poll budget (``SCAIMATRIX_INDEX_POLL_TIMEOUT``)
    ran out. Surfaced loudly so a half-indexed attachment is not silently
    treated as searchable.
    """


class ScaiMatrixMissingIdError(RuntimeError):
    """Raised when a create/ingest response lacks the expected ``id``.

    A 2xx without an id would leave chunks indexed upstream with no handle to
    search or delete them, so the failure is raised instead of persisted.
    """


class ScaiMatrixRagBackend(BaseRagBackend):
    """RAG backend talking to the ScaiMatrix REST API."""

    def __init__(
        self,
        collection_id: Optional[str] = None,
        read_only_collection_id: Optional[List[str]] = None,
    ):
        super().__init__(collection_id, read_only_collection_id)
        self._base_url = settings.SCAIMATRIX_API_URL
        self._headers = {
            "Authorization": f"Bearer {settings.SCAIMATRIX_API_KEY}",
        }
        # ScaiMatrix nests every payload under a top-level "data" key.
        self._collections_endpoint = urljoin(
            self._base_url, "/v1/modules/scaimatrix/collections"
        )
        parser_class = import_string(settings.RAG_DOCUMENT_PARSER)
        self.parser = parser_class()

    # -- URL helpers ---------------------------------------------------------

    def _collection_url(self, collection_id: str) -> str:
        return f"{self._collections_endpoint}/{collection_id}"

    def _documents_url(self, collection_id: str) -> str:
        return f"{self._collection_url(collection_id)}/documents"

    def _search_url(self, collection_id: str) -> str:
        return f"{self._collection_url(collection_id)}/search"

    @staticmethod
    def _data(response) -> dict:
        """Return the ``data`` envelope of a ScaiMatrix response body."""
        body = response.json()
        return body.get("data", body)

    # -- collection lifecycle ------------------------------------------------

    def _create_collection_payload(self, name: str, description: Optional[str]) -> dict:
        # slug is derived server-side from name when omitted; names are unique
        # per tenant (indexing uses "project-<pk>" / "conversation-<pk>"), so a
        # duplicate name yields 409 SLUG_CONFLICT rather than a silent alias.
        return {
            "name": name,
            "description": description or self._default_collection_description,
            "embedding_model": settings.SCAIMATRIX_EMBEDDING_MODEL,
            "chunking_strategy": settings.SCAIMATRIX_CHUNKING_STRATEGY,
            "chunk_size": settings.SCAIMATRIX_CHUNK_SIZE,
            "chunk_overlap": settings.SCAIMATRIX_CHUNK_OVERLAP,
            "graph_enabled": False,
            "default_access": "restricted",
        }

    def create_collection(self, name: str, description: Optional[str] = None) -> str:
        """Create a private collection and bind this backend to it."""
        response = requests.post(
            self._collections_endpoint,
            headers=self._headers,
            json=self._create_collection_payload(name, description),
            timeout=settings.SCAIMATRIX_API_TIMEOUT,
        )
        response.raise_for_status()
        return self._set_collection_id(self._data(response))

    async def acreate_collection(self, name: str, description: Optional[str] = None) -> str:
        """Async variant of :meth:`create_collection`."""
        async with httpx.AsyncClient(timeout=settings.SCAIMATRIX_API_TIMEOUT) as client:
            response = await client.post(
                self._collections_endpoint,
                headers=self._headers,
                json=self._create_collection_payload(name, description),
            )
            response.raise_for_status()
            return self._set_collection_id(self._data(response))

    def _set_collection_id(self, data: dict) -> str:
        collection_id = data.get("id")
        if collection_id is None:
            raise ScaiMatrixMissingIdError(
                f"ScaiMatrix create-collection response is missing an 'id': {data!r}"
            )
        self.collection_id = str(collection_id)
        return self.collection_id

    def delete_collection(self, **kwargs) -> None:
        """Delete the managed collection (drops all its documents)."""
        response = requests.delete(
            self._collection_url(self.collection_id),
            headers=self._headers,
            timeout=settings.SCAIMATRIX_API_TIMEOUT,
        )
        response.raise_for_status()

    async def adelete_collection(self, **kwargs) -> None:
        """Async variant of :meth:`delete_collection`."""
        async with httpx.AsyncClient(timeout=settings.SCAIMATRIX_API_TIMEOUT) as client:
            response = await client.delete(
                self._collection_url(self.collection_id),
                headers=self._headers,
            )
            response.raise_for_status()

    def delete_document(self, document_id: str, **kwargs) -> None:
        """Remove a single document from the managed collection."""
        response = requests.delete(
            f"{self._documents_url(self.collection_id)}/{document_id}",
            headers=self._headers,
            timeout=settings.SCAIMATRIX_API_TIMEOUT,
        )
        response.raise_for_status()

    # -- ingestion -----------------------------------------------------------

    def store_document(self, name: str, content: str, **kwargs) -> Optional[str]:
        """Upload markdown content and block until it is indexed.

        Returns the ScaiMatrix document id, later used to scope search to a
        single document and as the target of :meth:`delete_document`.
        """
        response = requests.post(
            self._documents_url(self.collection_id),
            headers=self._headers,
            files={
                "file": (f"{name}.md", BytesIO(content.encode("utf-8")), "text/markdown"),
            },
            data={
                "name": name,
                "metadata": json.dumps({"document_name": name}),
            },
            timeout=settings.SCAIMATRIX_API_TIMEOUT,
        )
        logger.debug(response.text)
        response.raise_for_status()
        document_id = self._document_id(self._data(response))
        self._wait_until_indexed(document_id)
        return document_id

    async def astore_document(self, name: str, content: str, **kwargs) -> Optional[str]:
        """Async variant of :meth:`store_document`."""
        async with httpx.AsyncClient(timeout=settings.SCAIMATRIX_API_TIMEOUT) as client:
            response = await client.post(
                self._documents_url(self.collection_id),
                headers=self._headers,
                files={
                    "file": (f"{name}.md", content.encode("utf-8"), "text/markdown"),
                },
                data={
                    "name": name,
                    "metadata": json.dumps({"document_name": name}),
                },
            )
            logger.debug(response.text)
            response.raise_for_status()
            document_id = self._document_id(self._data(response))
            await self._await_until_indexed(client, document_id)
            return document_id

    @staticmethod
    def _document_id(data: dict) -> str:
        document_id = data.get("id")
        if document_id is None:
            raise ScaiMatrixMissingIdError(
                f"ScaiMatrix ingest response is missing an 'id': {data!r}"
            )
        return str(document_id)

    def _document_status(self, data: dict, document_id: str) -> str:
        status = data.get("status")
        if status in _TERMINAL_ERROR_STATES:
            raise ScaiMatrixIndexingError(
                f"ScaiMatrix document {document_id} failed to index: "
                f"{data.get('error_message') or status}"
            )
        return status

    def _wait_until_indexed(self, document_id: str) -> None:
        """Poll the document until it is ``indexed`` (sync path)."""
        deadline = settings.SCAIMATRIX_INDEX_POLL_TIMEOUT
        interval = settings.SCAIMATRIX_INDEX_POLL_INTERVAL
        url = f"{self._documents_url(self.collection_id)}/{document_id}"
        waited = 0
        while waited <= deadline:
            response = requests.get(
                url, headers=self._headers, timeout=settings.SCAIMATRIX_API_TIMEOUT
            )
            response.raise_for_status()
            if self._document_status(self._data(response), document_id) == _INDEXED_STATE:
                return
            time.sleep(interval)
            waited += interval
        raise ScaiMatrixIndexingError(
            f"ScaiMatrix document {document_id} not indexed within {deadline}s."
        )

    async def _await_until_indexed(self, client, document_id: str) -> None:
        """Poll the document until it is ``indexed`` (async path)."""
        deadline = settings.SCAIMATRIX_INDEX_POLL_TIMEOUT
        interval = settings.SCAIMATRIX_INDEX_POLL_INTERVAL
        url = f"{self._documents_url(self.collection_id)}/{document_id}"
        waited = 0
        while waited <= deadline:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            if self._document_status(self._data(response), document_id) == _INDEXED_STATE:
                return
            await asyncio.sleep(interval)
            waited += interval
        raise ScaiMatrixIndexingError(
            f"ScaiMatrix document {document_id} not indexed within {deadline}s."
        )

    # -- search --------------------------------------------------------------

    def _search_payload(self, query: str, results_count: int) -> dict:
        return {
            "query": query,
            "top_k": results_count,
            "search_type": settings.SCAIMATRIX_SEARCH_TYPE,
        }

    @staticmethod
    def _keep(result: dict, document_name: Optional[str], document_id: Optional[str]) -> bool:
        """Client-side document scoping (ScaiMatrix has no server-side filter)."""
        if document_id:
            return str(result.get("document_id")) == str(document_id)
        if document_name:
            return result.get("document_name") == document_name
        return True

    def _merge_results(
        self,
        raw_results: List[dict],
        results_count: int,
        document_name: Optional[str],
        document_id: Optional[str],
    ) -> RAGWebResults:
        """Filter, sort by score, cap, and map to :class:`RAGWebResults`.

        ScaiMatrix does not report token usage, so usage is left at zero.
        """
        filtered = [r for r in raw_results if self._keep(r, document_name, document_id)]
        filtered.sort(key=lambda r: r.get("score", 0.0), reverse=True)

        if not filtered and (document_name or document_id):
            logger.info(
                "RAG search with document_name=%r document_id=%r returned no results.",
                document_name,
                document_id,
            )

        return RAGWebResults(
            data=[
                RAGWebResult(
                    url=result.get("document_name", ""),
                    content=result.get("content", ""),
                    score=result.get("score", 0.0),
                )
                for result in filtered[:results_count]
            ],
            usage=RAGWebUsage(),
        )

    def search(
        self,
        query: str,
        results_count: int = 4,
        document_name: Optional[str] = None,
        document_id: Optional[str] = None,
        **kwargs,
    ) -> RAGWebResults:
        """Search every bound collection and merge the results by score."""
        payload = self._search_payload(query, results_count)
        raw: List[dict] = []
        for collection_id in self.get_all_collection_ids():  # might raise RuntimeError
            response = requests.post(
                self._search_url(collection_id),
                headers=self._headers,
                json=payload,
                timeout=settings.SCAIMATRIX_API_TIMEOUT,
            )
            response.raise_for_status()
            raw.extend(self._data(response).get("results", []))
        return self._merge_results(raw, results_count, document_name, document_id)

    async def asearch(
        self,
        query: str,
        results_count: int = 4,
        document_name: Optional[str] = None,
        document_id: Optional[str] = None,
        **kwargs,
    ) -> RAGWebResults:
        """Async variant of :meth:`search`."""
        payload = self._search_payload(query, results_count)
        raw: List[dict] = []
        async with httpx.AsyncClient(timeout=settings.SCAIMATRIX_API_TIMEOUT) as client:
            for collection_id in self.get_all_collection_ids():
                response = await client.post(
                    self._search_url(collection_id),
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
                raw.extend(self._data(response).get("results", []))
        return self._merge_results(raw, results_count, document_name, document_id)
