import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings
from app.knowledge.index import KnowledgeChunk, KnowledgeIndex
from app.models.graph import GapAssessment, GapStatus
from app.models.knowledge import (
    GapAnalyzeRequest,
    GapAnalyzeResponse,
    KnowledgeEvidence,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

MIN_EVIDENCE_SCORE = 0.3


class KnowledgeService:
    def __init__(
        self,
        root: Path,
        index: KnowledgeIndex,
        *,
        allow_pending: bool,
    ) -> None:
        self.root = root
        self.index = index
        self.allow_pending = allow_pending
        self.chunks = self._load_chunks()
        self.indexed_chunks = self.index.sync(self.chunks)
        self.chunk_by_id = {chunk.chunk_id: chunk for chunk in self.indexed_chunks}

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
        terms = _query_terms(request.query)
        candidates: list[tuple[float, KnowledgeChunk]] = []
        release_mismatch = False
        vector_scores = {
            hit.chunk_id: hit.score
            for hit in self.index.search(
                request.query,
                module=request.module,
                process_scope=request.process_scope,
                sap_release=request.sap_context.release,
                top_k=request.top_k,
            )
        }

        for chunk in self.indexed_chunks:
            metadata = chunk.metadata
            if str(metadata.get("module", "")).upper() != request.module.upper():
                continue
            if str(metadata.get("process_scope", "")).upper() != request.process_scope.upper():
                continue
            knowledge_release = str(metadata.get("sap_release", ""))
            if knowledge_release and knowledge_release != request.sap_context.release:
                release_mismatch = True
                continue

            lexical_score = _score_chunk(chunk, terms, request.query)
            vector_score = vector_scores.get(chunk.chunk_id, 0.0)
            if lexical_score > 0 or vector_score >= 0.2:
                score = min(1.0, lexical_score * 0.55 + vector_score * 0.45)
                candidates.append((score, chunk))

        candidates.sort(key=lambda item: item[0], reverse=True)
        top = (
            candidates[: request.top_k]
            if candidates and candidates[0][0] >= MIN_EVIDENCE_SCORE
            else []
        )
        evidence = [
            self._to_evidence(chunk, score, request.query) for score, chunk in top
        ]
        warnings: list[str] = []
        if release_mismatch:
            warnings.append("存在其他 SAP Release 的知识条目，已从本次结果中排除。")
        if any(item.review_status != "approved" for item in evidence):
            warnings.append("检索结果尚未完成顾问审核，只能作为待确认建议。")
        if not evidence:
            warnings.append("未检索到足够证据，请补充需求或由 SAP 顾问确认。")

        return KnowledgeSearchResponse(
            status="results" if evidence else "insufficient_evidence",
            evidence=evidence,
            warnings=warnings,
        )

    def analyze_gap(self, request: GapAnalyzeRequest) -> GapAnalyzeResponse:
        search_result = self.search(
            KnowledgeSearchRequest(
                module=request.module,
                process_scope=request.process_scope,
                query=request.business_requirement,
                sap_context=request.sap_context,
                top_k=5,
            )
        )
        if not search_result.evidence:
            return GapAnalyzeResponse(
                outcome="insufficient_evidence",
                gap=None,
                evidence=[],
                warnings=search_result.warnings,
            )

        requirement = request.business_requirement.lower()
        for chunk in self.indexed_chunks:
            metadata = chunk.metadata
            if str(metadata.get("module", "")).upper() != request.module.upper():
                continue
            if str(metadata.get("process_scope", "")).upper() != request.process_scope.upper():
                continue
            knowledge_release = str(metadata.get("sap_release", ""))
            if knowledge_release and knowledge_release != request.sap_context.release:
                continue
            for pattern in metadata.get("gap_patterns", []) or []:
                keywords = [str(item).lower() for item in pattern.get("keywords", [])]
                matches = [keyword for keyword in keywords if keyword in requirement]
                if not matches:
                    continue
                source_id = str(metadata.get("source_id", "knowledge"))
                pattern_ref = f"{source_id}#gap-{pattern.get('id', 'candidate')}"
                evidence_refs = [pattern_ref, *[item.evidence_ref for item in search_result.evidence]]
                gap = GapAssessment(
                    status=GapStatus.CANDIDATE,
                    category=str(pattern.get("category") or "待分类"),
                    description=str(pattern.get("description") or request.business_requirement),
                    recommendation=str(pattern.get("recommendation") or "由 SAP 顾问评估标准能力与增强方案。"),
                    confidence=min(0.8, 0.5 + len(matches) * 0.08),
                    evidence_refs=list(dict.fromkeys(evidence_refs)),
                    owner=None,
                )
                return GapAnalyzeResponse(
                    outcome="candidate",
                    gap=gap,
                    evidence=search_result.evidence,
                    warnings=[
                        *search_result.warnings,
                        "该结果是 GAP 候选，必须由顾问确认后才能进入正式 GAP List。",
                    ],
                )

        return GapAnalyzeResponse(
            outcome="no_candidate",
            gap=None,
            evidence=search_result.evidence,
            warnings=[*search_result.warnings, "当前证据未触发已配置的 GAP 候选规则。"],
        )

    def _load_chunks(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        if not self.root.exists():
            return chunks
        for path in sorted(self.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            metadata, body = _parse_document(text)
            if not metadata.get("source_id"):
                continue
            for section, content in _split_sections(body):
                chunks.append(
                    KnowledgeChunk(
                        metadata=metadata,
                        section=section,
                        body=content,
                        source_path=path.relative_to(self.root).as_posix(),
                    )
                )
        return chunks

    @staticmethod
    def _to_evidence(
        chunk: KnowledgeChunk,
        raw_score: float,
        query: str,
    ) -> KnowledgeEvidence:
        metadata = chunk.metadata
        source_id = str(metadata["source_id"])
        section_slug = re.sub(r"[^a-z0-9]+", "-", chunk.section.lower()).strip("-") or "section"
        return KnowledgeEvidence(
            evidence_ref=f"{source_id}#{section_slug}",
            source_id=source_id,
            title=str(metadata.get("source_title") or source_id),
            section=chunk.section,
            excerpt=_best_excerpt(chunk.body, query),
            source_path=chunk.source_path,
            source_url=metadata.get("source_url") or None,
            sap_release=str(metadata.get("sap_release") or "") or None,
            review_status=str(metadata.get("review_status") or "pending_consultant"),
            score=min(1.0, round(raw_score, 4)),
        )


def _default_knowledge_root() -> Path:
    configured = get_settings().knowledge_root.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "SAP_Knowledge"


def _default_index_path() -> Path:
    configured = get_settings().knowledge_index_path.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "output" / "chroma"


@lru_cache
def get_knowledge_service() -> KnowledgeService:
    settings = get_settings()
    allow_pending = settings.app_env == "development"
    index = KnowledgeIndex.persistent(
        _default_index_path(),
        settings.knowledge_collection_name,
        settings.knowledge_embedding_dimensions,
        allow_pending=allow_pending,
    )
    return KnowledgeService(
        _default_knowledge_root(),
        index,
        allow_pending=allow_pending,
    )


def _parse_document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text
    metadata = yaml.safe_load(parts[1]) or {}
    return metadata if isinstance(metadata, dict) else {}, parts[2].strip()


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = "Overview"
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if lines:
                sections.append((heading, "\n".join(lines).strip()))
            heading = line[3:].strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        sections.append((heading, "\n".join(lines).strip()))
    return [(title, content) for title, content in sections if content]


def _query_terms(query: str) -> set[str]:
    normalized = query.lower().strip()
    terms = set(re.findall(r"[a-z0-9_/-]+", normalized))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        terms.add(sequence)
        terms.update(sequence[index : index + 2] for index in range(max(0, len(sequence) - 1)))
    return {term for term in terms if term}


def _score_chunk(chunk: KnowledgeChunk, terms: set[str], query: str) -> float:
    title = f"{chunk.metadata.get('source_title', '')} {chunk.section}".lower()
    body = chunk.body.lower()
    score = 0.0
    for term in terms:
        if term in title:
            score += 0.25
        if term in body:
            score += 0.12 + min(body.count(term), 3) * 0.03
    if query.lower().strip() in body:
        score += 0.35
    return min(score, 1.0)


def _best_excerpt(body: str, query: str) -> str:
    lines = [line.strip(" -") for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    terms = _query_terms(query)
    scored = [
        (
            sum(
                (0.4 if len(term) > 3 else 0.2) * line.lower().count(term)
                for term in terms
            ),
            index,
        )
        for index, line in enumerate(lines)
    ]
    best_score, best_index = max(scored)
    if best_score == 0:
        excerpt_lines = lines[:3]
    else:
        start = max(0, best_index - 1)
        end = min(len(lines), best_index + 2)
        excerpt_lines = lines[start:end]
    excerpt = " ".join(excerpt_lines)
    return excerpt[:500]
