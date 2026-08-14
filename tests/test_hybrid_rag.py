import math

import pytest
from pydantic import ValidationError

from learning_coach.hybrid_rag import (
    BoundedEmbeddingCache,
    LocalHashEmbeddings,
    RagSettings,
    bm25_retrieve,
    create_embeddings,
    dense_retrieve,
    reciprocal_rank_fusion,
    rerank_candidates,
)
from learning_coach.ingestion import StudyChunkRecord
from learning_coach.schemas import (
    GroundedTeaching,
    RetrievalAttempt,
    RetrievalReport,
    RetrievalScore,
    StudySource,
)


def _chunk(
    text: str,
    *,
    index: int,
    source_name: str = "notes.md",
) -> StudyChunkRecord:
    token = f"{index:064x}"
    return StudyChunkRecord(
        source_id="a" * 64,
        source_key=f"upload:{source_name}",
        source_type="text",
        source_name=source_name,
        source_uri=source_name,
        mime_type="text/markdown",
        content_hash="b" * 64,
        location_type="paragraph",
        location=f"paragraph {index}",
        chunk_id=token,
        chunk_hash=token,
        chunk_index=index,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def test_local_hash_embeddings_are_stable_normalized_and_ordered() -> None:
    embeddings = LocalHashEmbeddings(dimensions=64)

    first = embeddings.embed_query("LangGraph Reducer 合并状态")
    second = embeddings.embed_query("LangGraph Reducer 合并状态")
    different = embeddings.embed_query("CSS Grid 页面布局")
    batch = embeddings.embed_documents(
        ["LangGraph Reducer 合并状态", "CSS Grid 页面布局", ""]
    )

    assert first == second == batch[0]
    assert different == batch[1]
    assert first != different
    assert len(first) == 64
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)
    assert batch[2] == [0.0] * 64


def test_local_hash_embeddings_validate_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        LocalHashEmbeddings(dimensions=0)


def test_bounded_embedding_cache_hits_and_evicts_oldest_entry() -> None:
    cache = BoundedEmbeddingCache(max_entries=2)

    cache.put("model", "chunk-1", [1.0, 0.0])
    cache.put("model", "chunk-2", [0.0, 1.0])

    assert cache.get("model", "chunk-1") == [1.0, 0.0]
    cache.put("model", "chunk-3", [0.5, 0.5])

    assert cache.get("model", "chunk-1") is None
    assert cache.get("model", "chunk-2") == [0.0, 1.0]
    assert cache.get("model", "chunk-3") == [0.5, 0.5]

    with pytest.raises(ValueError, match="max_entries"):
        BoundedEmbeddingCache(max_entries=0)


def test_rag_settings_use_bounded_defaults() -> None:
    settings = RagSettings.from_environ({})

    assert settings.embedding_model_id == "local:hash-v1"
    assert settings.candidate_k == 8
    assert settings.top_k == 3
    assert settings.max_attempts == 2


def test_embedding_factory_keeps_local_default_offline() -> None:
    calls: list[str] = []

    embeddings = create_embeddings(
        RagSettings.from_environ({}),
        initializer=lambda model_id: calls.append(model_id),
    )

    assert isinstance(embeddings, LocalHashEmbeddings)
    assert calls == []


def test_embedding_factory_initializes_explicit_provider_model() -> None:
    provider = LocalHashEmbeddings(dimensions=32)
    calls: list[str] = []

    def initialize(model_id: str) -> LocalHashEmbeddings:
        calls.append(model_id)
        return provider

    settings = RagSettings.from_environ(
        {"EMBEDDING_MODEL_ID": "openai:text-embedding-3-small"}
    )
    embeddings = create_embeddings(settings, initializer=initialize)

    assert embeddings is provider
    assert calls == ["openai:text-embedding-3-small"]


@pytest.mark.parametrize(
    "model_id",
    ["", "hash-v1", "local:unknown"],
)
def test_embedding_settings_reject_invalid_model_ids(model_id: str) -> None:
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL_ID"):
        RagSettings.from_environ({"EMBEDDING_MODEL_ID": model_id})


def test_retrieval_schemas_are_bounded_and_backward_compatible() -> None:
    score = RetrievalScore(
        keyword=0.8,
        embedding=0.6,
        fusion=0.7,
        rerank=0.75,
    )
    attempt = RetrievalAttempt(
        attempt=1,
        query="Reducer 合并状态",
        keyword_candidates=3,
        embedding_candidates=3,
        selected_candidates=2,
        quality="sufficient",
        reason="相关度和覆盖率达到阈值",
    )
    report = RetrievalReport(
        original_query="Reducer 合并状态",
        final_query="Reducer 合并状态",
        rewritten=False,
        quality="sufficient",
        embedding_model_id="local:hash-v1",
        attempts=[attempt],
    )
    legacy = StudySource(source_id="legacy", text="Reducer", score=0.8)
    traced = StudySource(
        source_id="chunk-1",
        text="Reducer 合并并行状态",
        score=0.75,
        retrieval_score=score,
        retrieval_attempt=1,
    )
    teaching = GroundedTeaching(
        text="讲解",
        sources=[traced],
        retrieval_report=report,
    )

    assert legacy.retrieval_score is None
    assert legacy.retrieval_attempt is None
    assert teaching.retrieval_report == report
    assert teaching.sources[0].retrieval_score == score


def test_retrieval_schemas_reject_invalid_scores_attempts_and_vectors() -> None:
    with pytest.raises(ValidationError):
        RetrievalScore(keyword=1.1, embedding=0, fusion=0, rerank=0)
    with pytest.raises(ValidationError):
        RetrievalReport(
            original_query="query",
            final_query="query",
            rewritten=False,
            quality="insufficient",
            embedding_model_id="local:hash-v1",
            attempts=[
                RetrievalAttempt(
                    attempt=index,
                    query="query",
                    keyword_candidates=0,
                    embedding_candidates=0,
                    selected_candidates=0,
                    quality="empty",
                    reason="没有候选",
                )
                for index in (1, 2, 2)
            ],
        )


def test_bm25_retrieval_ranks_terms_and_normalizes_scores() -> None:
    chunks = [
        _chunk("LangGraph Reducer 合并并行 State 更新。", index=1),
        _chunk("Reducer 是一个函数。", index=2),
        _chunk("CSS Grid 定义二维页面布局。", index=3),
    ]

    ranked = bm25_retrieve("LangGraph Reducer 合并状态", chunks, limit=2)

    assert [item.chunk.chunk_id for item in ranked] == [
        chunks[0].chunk_id,
        chunks[1].chunk_id,
    ]
    assert ranked[0].score == pytest.approx(1.0)
    assert 0 < ranked[1].score < ranked[0].score


def test_bm25_retrieval_applies_length_normalization_and_stable_ties() -> None:
    short = _chunk("Reducer", index=1)
    long = _chunk("Reducer " + "无关内容 " * 30, index=2)
    tie = _chunk("Reducer", index=3, source_name="second.md")

    ranked = bm25_retrieve("Reducer", [short, long, tie], limit=8)

    assert [item.chunk.chunk_id for item in ranked] == [
        short.chunk_id,
        tie.chunk_id,
        long.chunk_id,
    ]


def test_bm25_retrieval_handles_chinese_no_match_and_limits() -> None:
    chunks = [
        _chunk("条件边根据分数选择补救或总结。", index=1),
        _chunk("条件路由必须覆盖全部分支。", index=2),
        _chunk("CSS Grid 页面布局。", index=3),
    ]

    assert len(bm25_retrieve("条件", chunks, limit=1)) == 1
    assert bm25_retrieve("数据库事务", chunks, limit=8) == []
    with pytest.raises(ValueError, match="limit"):
        bm25_retrieve("条件", chunks, limit=0)


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [
            [1.0, 0.0] if "Reducer" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [1.0, 0.0]


def test_dense_retrieval_uses_cosine_similarity_and_document_cache() -> None:
    chunks = [
        _chunk("Reducer 合并状态。", index=1),
        _chunk("CSS Grid 页面布局。", index=2),
    ]
    embeddings = _FakeEmbeddings()
    cache = BoundedEmbeddingCache(max_entries=8)

    first = dense_retrieve(
        "如何合并并行状态",
        chunks,
        embeddings=embeddings,
        embedding_model_id="fake:model",
        cache=cache,
        limit=8,
    )
    second = dense_retrieve(
        "再次查询",
        chunks,
        embeddings=embeddings,
        embedding_model_id="fake:model",
        cache=cache,
        limit=8,
    )

    assert not first.degraded
    assert [item.chunk.chunk_id for item in first.ranked] == [chunks[0].chunk_id]
    assert first.ranked[0].score == pytest.approx(1.0)
    assert second.ranked[0].chunk.chunk_id == chunks[0].chunk_id
    assert embeddings.document_calls == 1
    assert embeddings.query_calls == 2


@pytest.mark.parametrize("mode", ["error", "dimension", "non_finite"])
def test_dense_retrieval_degrades_safely_for_embedding_failures(mode: str) -> None:
    class BrokenEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            if mode == "error":
                raise RuntimeError("secret-api-key")
            if mode == "dimension":
                return [[1.0, 0.0], [1.0]]
            return [[math.nan, 0.0], [0.0, 1.0]]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0]

    result = dense_retrieve(
        "Reducer",
        [_chunk("Reducer", index=1), _chunk("CSS", index=2)],
        embeddings=BrokenEmbeddings(),
        embedding_model_id="broken:model",
        cache=BoundedEmbeddingCache(max_entries=8),
        limit=8,
    )

    assert result.ranked == []
    assert result.degraded
    assert result.reason == "embedding_unavailable"
    assert "secret" not in result.reason


def test_rrf_fuses_duplicate_candidates_and_normalizes_ranks() -> None:
    first = _chunk("Reducer 合并状态。", index=1)
    shared = _chunk("Reducer 并行更新。", index=2)
    semantic = _chunk("并发写入需要组合规则。", index=3)

    keyword = bm25_retrieve("Reducer", [first, shared, semantic], limit=8)
    dense = [
        type(keyword[0])(chunk=shared, score=1.0),
        type(keyword[0])(chunk=semantic, score=0.8),
    ]
    fused = reciprocal_rank_fusion(keyword, dense, limit=8)

    assert fused[0].chunk.chunk_id == shared.chunk_id
    assert fused[0].fusion_score == pytest.approx(1.0)
    assert fused[0].keyword_score > 0
    assert fused[0].embedding_score == 1.0
    assert len({item.chunk.chunk_id for item in fused}) == len(fused)


def test_reranker_uses_query_coverage_phrase_and_channel_agreement() -> None:
    exact = _chunk("Reducer 合并并行状态。", index=1)
    partial = _chunk("Reducer 是一个函数。", index=2)
    keyword = bm25_retrieve("Reducer 合并", [partial, exact], limit=8)
    dense = [
        type(keyword[0])(chunk=partial, score=1.0),
        type(keyword[0])(chunk=exact, score=0.7),
    ]

    fused = reciprocal_rank_fusion(keyword, dense, limit=8)
    sources = rerank_candidates("Reducer 合并", fused, top_k=1, attempt=2)

    assert len(sources) == 1
    assert sources[0].source_id == exact.chunk_id
    assert sources[0].source_name == exact.source_name
    assert sources[0].location == exact.location
    assert sources[0].retrieval_attempt == 2
    assert sources[0].retrieval_score is not None
    assert sources[0].score == sources[0].retrieval_score.rerank
    assert 0 < sources[0].retrieval_score.fusion <= 1


def test_rrf_and_reranker_validate_limits_and_keep_stable_ties() -> None:
    first = _chunk("Reducer", index=1)
    second = _chunk("Reducer", index=2, source_name="other.md")
    ranked = bm25_retrieve("Reducer", [first, second], limit=8)

    fused = reciprocal_rank_fusion(ranked, [], limit=8)
    sources = rerank_candidates("Reducer", fused, top_k=2, attempt=1)

    assert [source.source_id for source in sources] == [
        first.chunk_id,
        second.chunk_id,
    ]
    with pytest.raises(ValueError, match="limit"):
        reciprocal_rank_fusion(ranked, [], limit=0)
    with pytest.raises(ValueError, match="top_k"):
        rerank_candidates("Reducer", fused, top_k=0, attempt=1)
    with pytest.raises(ValidationError, match="vector"):
        RetrievalAttempt.model_validate(
            {
                "attempt": 1,
                "query": "query",
                "keyword_candidates": 1,
                "embedding_candidates": 1,
                "selected_candidates": 1,
                "quality": "sufficient",
                "reason": "ok",
                "vector": [0.1, 0.2],
            }
        )
