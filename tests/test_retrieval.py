import pytest

from learning_coach.ingestion import InMemoryStudyIndex, MaterialInput
from learning_coach.loaders import default_loader_registry
from learning_coach.retrieval import (
    MAX_STUDY_MATERIAL_CHARS,
    chunk_study_material,
    normalize_study_material,
    retrieve_study_sources,
    retrieve_study_sources_with_report,
)
from learning_coach.schemas import StudySource


def test_chunking_assigns_stable_source_ids_and_preserves_text() -> None:
    material = "Reducer 决定并行更新如何合并。\n\n条件边根据结构化状态选择节点。"

    chunks = chunk_study_material(material, chunk_size=18, overlap=4)

    assert [chunk.source_id for chunk in chunks] == [
        f"material-1#chunk-{index}" for index in range(1, len(chunks) + 1)
    ]
    assert all(chunk.text.strip() == chunk.text for chunk in chunks)
    assert all(len(chunk.text) <= 18 for chunk in chunks)
    assert "Reducer" in chunks[0].text


def test_retrieval_ranks_relevant_chinese_and_english_chunks_deterministically() -> None:
    material = """RunnableSequence 按顺序执行多个步骤。

RunnableParallel 会并行执行映射中的多个分支。

Reducer 用于合并 LangGraph 并行节点对同一 State 字段的更新。"""

    first = retrieve_study_sources(
        {"query": "LangGraph Reducer 合并状态", "study_material": material},
        chunk_size=45,
        overlap=0,
        top_k=2,
    )
    second = retrieve_study_sources(
        {"query": "LangGraph Reducer 合并状态", "study_material": material},
        chunk_size=45,
        overlap=0,
        top_k=2,
    )

    assert first == second
    assert first
    assert "Reducer" in first[0].text
    assert first[0].score > 0
    assert len(first) <= 2


def test_retrieval_returns_no_sources_without_positive_match() -> None:
    sources = retrieve_study_sources(
        {
            "query": "Python 装饰器",
            "study_material": "CSS Grid 定义二维页面布局。",
        }
    )

    assert sources == []


def test_study_material_is_trimmed_and_bounded() -> None:
    assert normalize_study_material("  一段资料  ") == "一段资料"
    assert normalize_study_material("   ") == ""

    with pytest.raises(ValueError, match="50000"):
        normalize_study_material("x" * (MAX_STUDY_MATERIAL_CHARS + 1))


def test_retrieval_uses_indexed_chunks_and_returns_source_location() -> None:
    registry = default_loader_registry()
    documents = registry.load(
        MaterialInput(
            "graph.py",
            "text/x-python",
            data=(
                b"def route(score):\n"
                b"    return 'finish' if score >= 80 else 'retry'\n"
            ),
        )
    )
    index = InMemoryStudyIndex()
    index.sync(documents)

    sources = retrieve_study_sources(
        {
            "query": "route score finish retry",
            "study_chunks": [chunk.model_dump() for chunk in index.chunks],
            "study_material": "这段旧文本不应覆盖结构化 Chunk。",
        }
    )

    assert sources
    assert sources[0].source_name == "graph.py"
    assert sources[0].source_type == "code"
    assert sources[0].source_uri == "graph.py"
    assert sources[0].location == "lines 1-2"
    assert len(sources[0].source_id) == 64
    assert len(sources[0].chunk_hash or "") == 64

    public = StudySource(
        source_id=sources[0].source_id,
        text=sources[0].text,
        score=sources[0].score,
        source_name=sources[0].source_name,
        source_uri=sources[0].source_uri,
        source_type=sources[0].source_type,
        location=sources[0].location,
        chunk_hash=sources[0].chunk_hash,
    )
    assert public.location == "lines 1-2"


def test_retrieval_falls_back_to_legacy_material_when_chunks_are_empty() -> None:
    sources = retrieve_study_sources(
        {
            "query": "Reducer 合并",
            "study_chunks": [],
            "study_material": "Reducer 用于合并并行状态。",
        }
    )

    assert sources[0].source_id == "material-1#chunk-1"
    assert sources[0].source_name is None
    assert sources[0].location is None


def test_retrieval_rejects_invalid_serialized_chunk() -> None:
    with pytest.raises(ValueError, match="study_chunks"):
        retrieve_study_sources(
            {
                "query": "Reducer",
                "study_chunks": [{"text": "missing metadata"}],
            }
        )


def test_retrieval_report_traces_hybrid_scores_and_bounded_attempts() -> None:
    result = retrieve_study_sources_with_report(
        {
            "query": "怎么合并并行状态",
            "topic": "LangGraph Reducer",
            "diagnostic_focus": "Reducer 合并",
            "study_material": "Reducer 决定 LangGraph 并行状态如何合并。",
        }
    )

    assert result.sources
    assert result.sources[0].retrieval_score is not None
    assert result.report.original_query == "怎么合并并行状态"
    assert 1 <= len(result.report.attempts) <= 2
    assert result.report.quality in {"sufficient", "insufficient"}
