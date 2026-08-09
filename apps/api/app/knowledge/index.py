import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.errors import NotFoundError

INDEX_SCHEMA = "hash-char-ngram-v2"


@dataclass(frozen=True)
class KnowledgeChunk:
    metadata: dict[str, Any]
    section: str
    body: str
    source_path: str

    @property
    def document(self) -> str:
        title = str(self.metadata.get("source_title") or self.metadata.get("source_id") or "")
        return f"{title}\n{self.section}\n{self.body}".strip()

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.document.encode("utf-8")).hexdigest()

    @property
    def chunk_id(self) -> str:
        identity = (
            f"{self.metadata.get('source_id', '')}|{self.source_path}|{self.section}|"
            f"{self.content_hash}"
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @property
    def production_eligible(self) -> bool:
        license_status = str(self.metadata.get("license_status") or "").lower()
        review_status = str(self.metadata.get("review_status") or "").lower()
        return license_status in {"approved", "project_provided"} and review_status == "approved"

    def index_metadata(self) -> dict[str, str | int | float | bool]:
        return {
            "source_id": str(self.metadata.get("source_id") or ""),
            "source_path": self.source_path,
            "source_title": str(self.metadata.get("source_title") or ""),
            "section": self.section,
            "module": str(self.metadata.get("module") or "").upper(),
            "process_scope": str(self.metadata.get("process_scope") or "").upper(),
            "sap_release": str(self.metadata.get("sap_release") or ""),
            "review_status": str(self.metadata.get("review_status") or "pending_consultant"),
            "license_status": str(self.metadata.get("license_status") or "unknown"),
            "content_hash": self.content_hash,
            "production_eligible": self.production_eligible,
        }


@dataclass(frozen=True)
class IndexHit:
    chunk_id: str
    score: float


class HashedNgramEmbedding:
    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens = _embedding_tokens(text)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest, "big") % self.dimensions
            values[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            return [value / norm for value in values]
        return values


class KnowledgeIndex:
    def __init__(
        self,
        client: Any,
        collection_name: str,
        dimensions: int,
        *,
        allow_pending: bool,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.dimensions = dimensions
        self.allow_pending = allow_pending
        self.embedding = HashedNgramEmbedding(dimensions)
        self.collection = self._get_collection()

    @classmethod
    def persistent(
        cls,
        path: Path,
        collection_name: str,
        dimensions: int,
        *,
        allow_pending: bool,
    ) -> "KnowledgeIndex":
        path.mkdir(parents=True, exist_ok=True)
        return cls(
            chromadb.PersistentClient(path=str(path)),
            collection_name,
            dimensions,
            allow_pending=allow_pending,
        )

    def sync(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
        indexed = [chunk for chunk in chunks if self.allow_pending or chunk.production_eligible]
        desired_ids = {chunk.chunk_id for chunk in indexed}
        existing_ids = set(self.collection.get(include=[])["ids"])
        stale_ids = sorted(existing_ids - desired_ids)
        if stale_ids:
            self.collection.delete(ids=stale_ids)
        if indexed:
            self.collection.upsert(
                ids=[chunk.chunk_id for chunk in indexed],
                documents=[chunk.document for chunk in indexed],
                metadatas=[chunk.index_metadata() for chunk in indexed],
                embeddings=self.embedding.embed([chunk.document for chunk in indexed]),
            )
        return indexed

    def search(
        self,
        query: str,
        *,
        module: str,
        process_scope: str,
        sap_release: str,
        top_k: int,
    ) -> list[IndexHit]:
        count = self.collection.count()
        if count == 0:
            return []
        where: dict[str, Any] = {
            "$and": [
                {"module": {"$eq": module.upper()}},
                {"process_scope": {"$eq": process_scope.upper()}},
                {"sap_release": {"$eq": sap_release}},
            ]
        }
        result = self.collection.query(
            query_embeddings=self.embedding.embed([query]),
            n_results=min(count, max(top_k * 4, top_k)),
            where=where,
            include=["distances"],
        )
        ids = result.get("ids") or [[]]
        distances = result.get("distances") or [[]]
        return [
            IndexHit(chunk_id=chunk_id, score=max(0.0, min(1.0, 1.0 - float(distance))))
            for chunk_id, distance in zip(ids[0], distances[0], strict=True)
        ]

    def _get_collection(self):
        expected = {
            "hnsw:space": "cosine",
            "embedding_schema": INDEX_SCHEMA,
            "embedding_dimensions": self.dimensions,
        }
        try:
            collection = self.client.get_collection(self.collection_name)
        except NotFoundError:
            return self.client.create_collection(self.collection_name, metadata=expected)
        metadata = collection.metadata or {}
        if (
            metadata.get("embedding_schema") != INDEX_SCHEMA
            or metadata.get("embedding_dimensions") != self.dimensions
        ):
            self.client.delete_collection(self.collection_name)
            return self.client.create_collection(self.collection_name, metadata=expected)
        return collection


def _embedding_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = re.findall(r"[a-z0-9_/-]+", normalized)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        for size in (2, 3):
            tokens.extend(
                sequence[index : index + size]
                for index in range(max(0, len(sequence) - size + 1))
            )
    return tokens
