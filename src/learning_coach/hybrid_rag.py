import hashlib
import math
import os
import re
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings

from learning_coach.schemas import (
    GraphRAGReport,
    RetrievalAttempt,
    RetrievalQuality,
    RetrievalReport,
    RetrievalScore,
    StudySource,
)

DEFAULT_EMBEDDING_MODEL_ID = "local:hash-v1"
DEFAULT_EMBEDDING_DIMENSIONS = 256
DEFAULT_RAG_CANDIDATE_K = 8
DEFAULT_RAG_TOP_K = 3
MAX_RAG_ATTEMPTS = 2
MAX_EMBEDDING_CACHE_ENTRIES = 2_048

_LATIN_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True)
class RagSettings:
    """Environment-backed, bounded Hybrid RAG settings."""

    embedding_model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    candidate_k: int = DEFAULT_RAG_CANDIDATE_K
    top_k: int = DEFAULT_RAG_TOP_K
    max_attempts: int = MAX_RAG_ATTEMPTS

    def __post_init__(self) -> None:
        if not self.embedding_model_id.strip():
            raise ValueError("embedding_model_id 不能为空。")
        if self.embedding_model_id != DEFAULT_EMBEDDING_MODEL_ID and (
            ":" not in self.embedding_model_id
            or self.embedding_model_id.startswith("local:")
        ):
            raise ValueError(
                "embedding_model_id 必须是 local:hash-v1 或 provider:model。"
            )
        if not 1 <= self.candidate_k <= DEFAULT_RAG_CANDIDATE_K:
            raise ValueError("candidate_k 必须在 1 到 8 之间。")
        if not 1 <= self.top_k <= DEFAULT_RAG_TOP_K:
            raise ValueError("top_k 必须在 1 到 3 之间。")
        if self.max_attempts != MAX_RAG_ATTEMPTS:
            raise ValueError("max_attempts 固定为 2。")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "RagSettings":
        model_id = environ.get(
            "EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID
        ).strip()
        if not model_id:
            raise RuntimeError("EMBEDDING_MODEL_ID 不能为空。")
        if model_id != DEFAULT_EMBEDDING_MODEL_ID and (
            ":" not in model_id or model_id.startswith("local:")
        ):
            raise RuntimeError(
                "EMBEDDING_MODEL_ID 必须是 local:hash-v1 或 provider:model。"
            )
        return cls(embedding_model_id=model_id)


@dataclass(frozen=True)
class RankedChunk:
    """One retrieval-channel result with a normalized score."""

    chunk: "StudyChunkRecord"
    score: float


@dataclass(frozen=True)
class DenseRetrievalResult:
    """Dense channel output with a safe degradation signal."""

    ranked: list[RankedChunk]
    degraded: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class FusedChunk:
    """One candidate carrying normalized scores from both recall channels."""

    chunk: "StudyChunkRecord"
    keyword_score: float
    embedding_score: float
    fusion_score: float


@dataclass(frozen=True)
class EvidenceQualityResult:
    """Deterministic evidence sufficiency decision for one attempt."""

    quality: RetrievalQuality
    reason: str
    top_score: float
    coverage: float
    candidate_count: int
    source_count: int


@dataclass(frozen=True)
class HybridRetrievalResult:
    """Selected teaching evidence and its bounded retrieval trace."""

    sources: list[StudySource]
    report: RetrievalReport
    graph_report: GraphRAGReport | None = None


@dataclass(frozen=True)
class _AttemptResult:
    query: str
    sources: list[StudySource]
    quality: EvidenceQualityResult
    trace: RetrievalAttempt


def _embedding_features(text: str) -> Counter[str]:
    normalized = text.casefold()
    features = Counter(_LATIN_TOKEN.findall(normalized))
    for run in _CJK_RUN.findall(normalized):
        for character in run:
            features[f"c:{character}"] += 1
        for size in (2, 3):
            for index in range(len(run) - size + 1):
                features[f"c{size}:{run[index:index + size]}"] += 1
    return features


def _lexical_terms(text: str) -> Counter[str]:
    normalized = text.casefold()
    terms = Counter(_LATIN_TOKEN.findall(normalized))
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            terms[run] += 1
            continue
        for size in (2, 3):
            for index in range(len(run) - size + 1):
                terms[run[index : index + size]] += 1
    return terms


def _query_coverage(query: str, text: str) -> float:
    text_terms = set(_lexical_terms(text))
    coverages: list[float] = []
    for clause in query.split("；"):
        query_terms = set(_lexical_terms(clause))
        if query_terms:
            coverages.append(len(query_terms & text_terms) / len(query_terms))
    return max(coverages, default=0.0)


def bm25_retrieve(
    query: str,
    chunks: Sequence["StudyChunkRecord"],
    *,
    limit: int = DEFAULT_RAG_CANDIDATE_K,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[RankedChunk]:
    """Rank in-memory chunks with deterministic BM25 keyword relevance."""

    if limit <= 0:
        raise ValueError("limit 必须是正整数。")
    query_terms = _lexical_terms(query)
    if not query_terms or not chunks:
        return []

    documents = [_lexical_terms(chunk.text) for chunk in chunks]
    lengths = [sum(terms.values()) for terms in documents]
    average_length = sum(lengths) / len(lengths) or 1.0
    document_frequency = {
        term: sum(term in terms for terms in documents)
        for term in query_terms
    }
    raw: list[tuple[int, "StudyChunkRecord", float]] = []
    document_count = len(chunks)
    for order, (chunk, terms, length) in enumerate(
        zip(chunks, documents, lengths, strict=True)
    ):
        score = 0.0
        for term, query_count in query_terms.items():
            frequency = terms.get(term, 0)
            if frequency == 0:
                continue
            frequency_in_documents = document_frequency[term]
            inverse_document_frequency = math.log(
                1
                + (document_count - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * length / average_length
            )
            score += (
                inverse_document_frequency
                * frequency
                * (k1 + 1)
                / denominator
                * query_count
            )
        if score > 0:
            raw.append((order, chunk, score))

    if not raw:
        return []
    maximum = max(score for _, _, score in raw)
    raw.sort(key=lambda item: (-item[2], item[0]))
    return [
        RankedChunk(chunk=chunk, score=round(score / maximum, 6))
        for _, chunk, score in raw[:limit]
    ]


def _valid_vector(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("invalid embedding vector")
    return values


def dense_retrieve(
    query: str,
    chunks: Sequence["StudyChunkRecord"],
    *,
    embeddings: Embeddings,
    embedding_model_id: str,
    cache: "BoundedEmbeddingCache",
    limit: int = DEFAULT_RAG_CANDIDATE_K,
) -> DenseRetrievalResult:
    """Rank chunks by cosine similarity and degrade safely on backend errors."""

    if limit <= 0:
        raise ValueError("limit 必须是正整数。")
    if not query.strip() or not chunks:
        return DenseRetrievalResult(ranked=[])
    try:
        vectors: list[list[float] | None] = [
            cache.get(embedding_model_id, chunk.chunk_hash) for chunk in chunks
        ]
        missing_indexes = [
            index for index, vector in enumerate(vectors) if vector is None
        ]
        if missing_indexes:
            embedded = embeddings.embed_documents(
                [chunks[index].text for index in missing_indexes]
            )
            if len(embedded) != len(missing_indexes):
                raise ValueError("embedding count mismatch")
            validated = [_valid_vector(vector) for vector in embedded]
            for index, vector in zip(missing_indexes, validated, strict=True):
                vectors[index] = vector

        document_vectors = [
            _valid_vector(vector or []) for vector in vectors
        ]
        dimensions = {len(vector) for vector in document_vectors}
        if len(dimensions) != 1:
            raise ValueError("embedding dimension mismatch")
        query_vector = _valid_vector(embeddings.embed_query(query))
        if len(query_vector) not in dimensions:
            raise ValueError("embedding dimension mismatch")

        for chunk, vector in zip(chunks, document_vectors, strict=True):
            if cache.get(embedding_model_id, chunk.chunk_hash) is None:
                cache.put(embedding_model_id, chunk.chunk_hash, vector)

        query_norm = math.sqrt(
            sum(value * value for value in query_vector)
        )
        if query_norm == 0:
            return DenseRetrievalResult(ranked=[])
        raw: list[tuple[int, "StudyChunkRecord", float]] = []
        for order, (chunk, vector) in enumerate(
            zip(chunks, document_vectors, strict=True)
        ):
            document_norm = math.sqrt(sum(value * value for value in vector))
            if document_norm == 0:
                continue
            similarity = sum(
                query_value * document_value
                for query_value, document_value in zip(
                    query_vector, vector, strict=True
                )
            ) / (query_norm * document_norm)
            if similarity > 0:
                raw.append((order, chunk, min(1.0, similarity)))
        raw.sort(key=lambda item: (-item[2], item[0]))
        return DenseRetrievalResult(
            ranked=[
                RankedChunk(chunk=chunk, score=round(score, 6))
                for _, chunk, score in raw[:limit]
            ]
        )
    except Exception:
        return DenseRetrievalResult(
            ranked=[],
            degraded=True,
            reason="embedding_unavailable",
        )


def reciprocal_rank_fusion(
    keyword: Sequence[RankedChunk],
    embedding: Sequence[RankedChunk],
    *,
    limit: int = DEFAULT_RAG_CANDIDATE_K,
    rank_constant: int = 60,
) -> list[FusedChunk]:
    """Fuse keyword and dense ranks without mixing their raw score scales."""

    if limit <= 0:
        raise ValueError("limit 必须是正整数。")
    if rank_constant <= 0:
        raise ValueError("rank_constant 必须是正整数。")
    candidates: dict[str, dict[str, object]] = {}
    encounter_order = 0
    for channel, ranked in (("keyword", keyword), ("embedding", embedding)):
        for rank, item in enumerate(ranked, start=1):
            key = item.chunk.chunk_id
            if key not in candidates:
                candidates[key] = {
                    "chunk": item.chunk,
                    "keyword_score": 0.0,
                    "embedding_score": 0.0,
                    "fusion_raw": 0.0,
                    "order": encounter_order,
                }
                encounter_order += 1
            candidate = candidates[key]
            candidate[f"{channel}_score"] = item.score
            candidate["fusion_raw"] = float(candidate["fusion_raw"]) + 1 / (
                rank_constant + rank
            )

    if not candidates:
        return []
    maximum = max(float(item["fusion_raw"]) for item in candidates.values())
    ordered = sorted(
        candidates.values(),
        key=lambda item: (-float(item["fusion_raw"]), int(item["order"])),
    )
    return [
        FusedChunk(
            chunk=item["chunk"],  # type: ignore[arg-type]
            keyword_score=float(item["keyword_score"]),
            embedding_score=float(item["embedding_score"]),
            fusion_score=round(float(item["fusion_raw"]) / maximum, 6),
        )
        for item in ordered[:limit]
    ]


def rerank_candidates(
    query: str,
    candidates: Sequence[FusedChunk],
    *,
    top_k: int = DEFAULT_RAG_TOP_K,
    attempt: int = 1,
) -> list[StudySource]:
    """Apply a bounded deterministic second-stage reranker."""

    if top_k <= 0:
        raise ValueError("top_k 必须是正整数。")
    if attempt not in {1, 2}:
        raise ValueError("attempt 必须是 1 或 2。")
    normalized_query = " ".join(query.casefold().split())
    ranked: list[tuple[int, FusedChunk, float]] = []
    for order, candidate in enumerate(candidates):
        coverage = _query_coverage(query, candidate.chunk.text)
        normalized_text = " ".join(candidate.chunk.text.casefold().split())
        phrase = float(bool(normalized_query and normalized_query in normalized_text))
        agreement = float(
            candidate.keyword_score > 0 and candidate.embedding_score > 0
        )
        channel_peak = max(
            candidate.keyword_score, candidate.embedding_score
        )
        score = min(
            1.0,
            0.45 * candidate.fusion_score
            + 0.25 * coverage
            + 0.15 * channel_peak
            + 0.10 * agreement
            + 0.05 * phrase,
        )
        if score > 0:
            ranked.append((order, candidate, score))
    ranked.sort(key=lambda item: (-item[2], item[0]))

    sources: list[StudySource] = []
    for _, candidate, score in ranked[:top_k]:
        chunk = candidate.chunk
        normalized_score = round(score, 6)
        sources.append(
            StudySource(
                source_id=chunk.chunk_id,
                text=chunk.text,
                score=normalized_score,
                source_name=chunk.source_name,
                source_uri=chunk.source_uri,
                source_type=chunk.source_type,
                location=chunk.location,
                chunk_hash=chunk.chunk_hash,
                retrieval_score=RetrievalScore(
                    keyword=candidate.keyword_score,
                    embedding=candidate.embedding_score,
                    fusion=candidate.fusion_score,
                    rerank=normalized_score,
                ),
                retrieval_attempt=attempt,
            )
        )
    return sources


def assess_evidence_quality(
    query: str,
    sources: Sequence[StudySource],
    *,
    minimum_score: float = 0.6,
    minimum_coverage: float = 0.4,
) -> EvidenceQualityResult:
    """Judge whether selected evidence is relevant enough for teaching."""

    if not sources:
        return EvidenceQualityResult(
            quality="empty",
            reason="没有检索到正相关证据",
            top_score=0.0,
            coverage=0.0,
            candidate_count=0,
            source_count=0,
        )
    coverage = max(
        _query_coverage(query, source.text)
        for source in sources
    )
    top_score = max(source.score for source in sources)
    source_count = len(
        {
            source.source_uri or source.source_name or source.source_id
            for source in sources
        }
    )
    sufficient = (
        top_score >= minimum_score and coverage >= minimum_coverage
    )
    if sufficient:
        reason = "相关度和查询覆盖率达到阈值"
        quality: RetrievalQuality = "sufficient"
    elif top_score < minimum_score and coverage < minimum_coverage:
        reason = "相关度和查询覆盖率均不足"
        quality = "insufficient"
    elif top_score < minimum_score:
        reason = "最高重排分不足"
        quality = "insufficient"
    else:
        reason = "查询词覆盖率不足"
        quality = "insufficient"
    return EvidenceQualityResult(
        quality=quality,
        reason=reason,
        top_score=round(top_score, 6),
        coverage=round(coverage, 6),
        candidate_count=len(sources),
        source_count=source_count,
    )


def rewrite_retrieval_query(
    query: str,
    context: Mapping[str, Any],
    *,
    max_chars: int = 1_000,
) -> str:
    """Expand a weak query with bounded, deduplicated teaching context."""

    if max_chars <= 0:
        raise ValueError("max_chars 必须是正整数。")
    ignored = {"", "暂无", "none", "无", "n/a", "[]"}
    clauses: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for item in value:
                add(item)
            return
        normalized = " ".join(str(value or "").split())
        key = normalized.casefold()
        if key in ignored or key in seen:
            return
        seen.add(key)
        clauses.append(normalized)

    add(query)
    for field in (
        "topic",
        "diagnostic_focus",
        "feedback",
        "missing_point",
        "recent_errors",
        "learning_goal",
    ):
        add(context.get(field))
    return "；".join(clauses)[:max_chars].rstrip("； ")


class HybridStudyRetriever:
    """Run bounded Hybrid RAG with one deterministic corrective retry."""

    def __init__(
        self,
        *,
        settings: RagSettings | None = None,
        embeddings: Embeddings | None = None,
        cache: "BoundedEmbeddingCache | None" = None,
    ) -> None:
        self.settings = settings or RagSettings()
        self.embeddings = embeddings or create_embeddings(self.settings)
        self.cache = cache or BoundedEmbeddingCache()

    def retrieve(
        self,
        query: str,
        chunks: Sequence["StudyChunkRecord"],
        *,
        rewrite_context: Mapping[str, Any] | None = None,
    ) -> HybridRetrievalResult:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("检索查询不能为空。")

        attempts = [self._attempt(normalized_query, chunks, attempt=1)]
        if (
            attempts[0].quality.quality != "sufficient"
            and chunks
            and self.settings.max_attempts > 1
        ):
            rewritten = rewrite_retrieval_query(
                normalized_query, rewrite_context or {}
            )
            if rewritten and rewritten != normalized_query:
                attempts.append(self._attempt(rewritten, chunks, attempt=2))

        quality_rank = {"empty": 0, "insufficient": 1, "sufficient": 2}
        best = max(
            attempts,
            key=lambda item: (
                quality_rank[item.quality.quality],
                item.quality.top_score,
            ),
        )
        report = RetrievalReport(
            original_query=normalized_query,
            final_query=best.query,
            rewritten=len(attempts) == 2,
            quality=best.quality.quality,
            embedding_model_id=self.settings.embedding_model_id,
            attempts=[item.trace for item in attempts],
        )
        return HybridRetrievalResult(sources=best.sources, report=report)

    def _attempt(
        self,
        query: str,
        chunks: Sequence["StudyChunkRecord"],
        *,
        attempt: int,
    ) -> _AttemptResult:
        keyword = bm25_retrieve(
            query, chunks, limit=self.settings.candidate_k
        )
        dense = dense_retrieve(
            query,
            chunks,
            embeddings=self.embeddings,
            embedding_model_id=self.settings.embedding_model_id,
            cache=self.cache,
            limit=self.settings.candidate_k,
        )
        fused = reciprocal_rank_fusion(
            keyword, dense.ranked, limit=self.settings.candidate_k
        )
        sources = rerank_candidates(
            query,
            fused,
            top_k=self.settings.top_k,
            attempt=attempt,
        )
        quality = assess_evidence_quality(query, sources)
        trace = RetrievalAttempt(
            attempt=attempt,
            query=query,
            keyword_candidates=len(keyword),
            embedding_candidates=len(dense.ranked),
            selected_candidates=len(sources),
            quality=quality.quality,
            reason=quality.reason,
            embedding_degraded=dense.degraded,
            degradation_reason=dense.reason,
        )
        return _AttemptResult(
            query=query,
            sources=sources,
            quality=quality,
            trace=trace,
        )


class LocalHashEmbeddings(Embeddings):
    """Deterministic signed feature hashing for offline Hybrid RAG."""

    def __init__(self, *, dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions 必须是正整数。")
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature, count in _embedding_features(text).items():
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign * float(count)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class BoundedEmbeddingCache:
    """Insertion-ordered process cache keyed by model and chunk hash."""

    def __init__(self, *, max_entries: int = MAX_EMBEDDING_CACHE_ENTRIES) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries 必须是正整数。")
        self._max_entries = max_entries
        self._values: OrderedDict[tuple[str, str], tuple[float, ...]] = OrderedDict()

    def get(self, model_id: str, chunk_hash: str) -> list[float] | None:
        value = self._values.get((model_id, chunk_hash))
        return list(value) if value is not None else None

    def put(
        self,
        model_id: str,
        chunk_hash: str,
        vector: Sequence[float],
    ) -> None:
        key = (model_id, chunk_hash)
        if key not in self._values and len(self._values) >= self._max_entries:
            self._values.popitem(last=False)
        self._values[key] = tuple(float(value) for value in vector)


def create_embeddings(
    settings: RagSettings,
    *,
    initializer: Callable[[str], Embeddings] | None = None,
) -> Embeddings:
    """Create offline embeddings or an explicitly configured LangChain model."""

    if settings.embedding_model_id == DEFAULT_EMBEDDING_MODEL_ID:
        return LocalHashEmbeddings()
    if initializer is None:
        from langchain.embeddings import init_embeddings

        initializer = init_embeddings
    return initializer(settings.embedding_model_id)


def create_hybrid_retriever(
    environ: Mapping[str, str] | None = None,
    *,
    initializer: Callable[[str], Embeddings] | None = None,
) -> HybridStudyRetriever:
    """Create the shared retriever from the explicit process configuration."""

    settings = RagSettings.from_environ(environ if environ is not None else os.environ)
    return HybridStudyRetriever(
        settings=settings,
        embeddings=create_embeddings(settings, initializer=initializer),
    )
