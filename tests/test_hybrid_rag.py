import math

import pytest
from pydantic import ValidationError

from learning_coach.hybrid_rag import (
    BoundedEmbeddingCache,
    LocalHashEmbeddings,
    RagSettings,
    create_embeddings,
)
from learning_coach.schemas import (
    GroundedTeaching,
    RetrievalAttempt,
    RetrievalReport,
    RetrievalScore,
    StudySource,
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
