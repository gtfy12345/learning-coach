import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from learning_coach.hybrid_rag import (
    HybridRetrievalResult,
    HybridStudyRetriever,
    RagSettings,
)
from learning_coach.ingestion import StudyChunkRecord
from learning_coach.knowledge_graph import GraphStudyRetriever
from learning_coach.schemas import GraphRAGReport, RetrievalScore, StudySource

MAX_STUDY_MATERIAL_CHARS = 50_000
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_TOP_K = 3

@dataclass(frozen=True)
class StudyChunk:
    """A stable in-memory chunk created from one pasted study material."""

    source_id: str
    text: str


@dataclass(frozen=True)
class RetrievedStudySource:
    """A relevant chunk with optional Hybrid RAG trace scores."""

    source_id: str
    text: str
    score: float
    source_name: str | None = None
    source_uri: str | None = None
    source_type: str | None = None
    location: str | None = None
    chunk_hash: str | None = None
    retrieval_score: RetrievalScore | None = None
    retrieval_attempt: int | None = None


def normalize_study_material(value: str | None) -> str:
    """Normalize and bound untrusted study material before it enters state."""

    normalized = (value or "").strip()
    if len(normalized) > MAX_STUDY_MATERIAL_CHARS:
        raise ValueError(
            f"学习资料不能超过 {MAX_STUDY_MATERIAL_CHARS} 个字符。"
        )
    return normalized


def chunk_study_material(
    material: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[StudyChunk]:
    """Split plain text into stable bounded chunks without external storage."""

    normalized = normalize_study_material(material)
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须是正整数。")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0 且小于 chunk_size。")

    chunks: list[StudyChunk] = []
    start = 0
    while start < len(normalized):
        hard_end = min(start + chunk_size, len(normalized))
        end = hard_end
        if hard_end < len(normalized):
            window = normalized[start:hard_end]
            boundary = max(
                window.rfind("\n\n"),
                window.rfind("\n"),
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
            )
            if boundary >= chunk_size // 2:
                end = start + boundary + 1

        text = normalized[start:end].strip()
        if text:
            chunks.append(
                StudyChunk(
                    source_id=f"material-1#chunk-{len(chunks) + 1}",
                    text=text,
                )
            )
        if end >= len(normalized):
            break
        next_start = max(start + 1, end - overlap)
        while next_start < len(normalized) and normalized[next_start].isspace():
            next_start += 1
        start = next_start
    return chunks


def retrieve_study_sources(
    values: Mapping[str, Any],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedStudySource]:
    """Backward-compatible source list backed by the Hybrid RAG engine."""

    if top_k <= 0:
        raise ValueError("top_k 必须是正整数。")
    query = str(values.get("query", "")).strip()
    if not query:
        return []

    result = retrieve_study_sources_with_report(
        values,
        chunk_size=chunk_size,
        overlap=overlap,
        top_k=top_k,
    )
    return [
        RetrievedStudySource(
            source_id=source.source_id,
            text=source.text,
            score=source.score,
            source_name=source.source_name,
            source_uri=source.source_uri,
            source_type=source.source_type,
            location=source.location,
            chunk_hash=source.chunk_hash,
            retrieval_score=source.retrieval_score,
            retrieval_attempt=source.retrieval_attempt,
        )
        for source in result.sources
    ]


def retrieve_study_sources_with_report(
    values: Mapping[str, Any],
    *,
    retriever: HybridStudyRetriever | GraphStudyRetriever | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    top_k: int = DEFAULT_TOP_K,
) -> HybridRetrievalResult:
    """Adapt structured or legacy material into one traced Hybrid retrieval."""

    if top_k <= 0 or top_k > DEFAULT_TOP_K:
        raise ValueError(f"top_k 必须在 1 到 {DEFAULT_TOP_K} 之间。")
    query = str(values.get("query", "")).strip()
    if not query:
        raise ValueError("检索查询不能为空。")

    raw_chunks = values.get("study_chunks")
    legacy_ids: dict[str, str] = {}
    if raw_chunks:
        if not isinstance(raw_chunks, list):
            raise ValueError("study_chunks 必须是列表。")
        try:
            indexed_chunks = [
                chunk
                if isinstance(chunk, StudyChunkRecord)
                else StudyChunkRecord.model_validate(chunk)
                for chunk in raw_chunks
            ]
        except (TypeError, ValidationError, ValueError) as exc:
            raise ValueError("study_chunks 包含无效的 Chunk。") from exc
    else:
        material = normalize_study_material(str(values.get("study_material", "")))
        if not material:
            if raw_chunks not in (None, []):
                raise ValueError("study_chunks 必须是列表。")
            indexed_chunks = []
        else:
            indexed_chunks, legacy_ids = _legacy_study_chunks(
                material,
                chunk_size=chunk_size,
                overlap=overlap,
            )

    engine = retriever or GraphStudyRetriever(
        hybrid=HybridStudyRetriever(settings=RagSettings(top_k=top_k))
    )
    result = engine.retrieve(
        query,
        indexed_chunks,
        rewrite_context=values,
    )
    if not legacy_ids:
        return result
    return HybridRetrievalResult(
        sources=[
            source.model_copy(
                update={
                    "source_id": legacy_ids.get(
                        source.source_id, source.source_id
                    ),
                    "source_name": None,
                    "source_uri": None,
                    "source_type": None,
                    "location": None,
                    "chunk_hash": None,
                }
            )
            for source in result.sources
        ],
        report=result.report,
        graph_report=_remap_graph_report(result.graph_report, legacy_ids),
    )


def _remap_graph_report(
    report: GraphRAGReport | None,
    legacy_ids: Mapping[str, str],
) -> GraphRAGReport | None:
    if report is None:
        return None

    def remap(values: list[str]) -> list[str]:
        return [legacy_ids.get(value, value) for value in values]

    return report.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"chunk_ids": remap(node.chunk_ids)})
                for node in report.nodes
            ],
            "relations": [
                relation.model_copy(
                    update={
                        "evidence_chunk_ids": remap(
                            relation.evidence_chunk_ids
                        )
                    }
                )
                for relation in report.relations
            ],
            "prerequisites": [
                explanation.model_copy(
                    update={
                        "evidence_chunk_ids": remap(
                            explanation.evidence_chunk_ids
                        )
                    }
                )
                for explanation in report.prerequisites
            ],
        }
    )


def _legacy_study_chunks(
    material: str,
    *,
    chunk_size: int,
    overlap: int,
) -> tuple[list[StudyChunkRecord], dict[str, str]]:
    content_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    source_key = "legacy:pasted-text"
    source_id = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    records: list[StudyChunkRecord] = []
    public_ids: dict[str, str] = {}
    for index, chunk in enumerate(
        chunk_study_material(
            material,
            chunk_size=chunk_size,
            overlap=overlap,
        ),
        start=1,
    ):
        chunk_hash = hashlib.sha256(
            f"{source_id}\0{index}\0{chunk.text}".encode("utf-8")
        ).hexdigest()
        chunk_id = hashlib.sha256(
            f"{source_id}\0{chunk_hash}".encode("utf-8")
        ).hexdigest()
        public_ids[chunk_id] = chunk.source_id
        records.append(
            StudyChunkRecord(
                source_id=source_id,
                source_key=source_key,
                source_type="text",
                source_name="pasted-text.txt",
                source_uri="pasted-text.txt",
                mime_type="text/plain",
                content_hash=content_hash,
                location_type="paragraph",
                location=f"chunk {index}",
                chunk_id=chunk_id,
                chunk_hash=chunk_hash,
                chunk_index=index,
                char_start=0,
                char_end=len(chunk.text),
                text=chunk.text,
            )
        )
    return records, public_ids
