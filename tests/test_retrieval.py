import pytest

from learning_coach.retrieval import (
    MAX_STUDY_MATERIAL_CHARS,
    chunk_study_material,
    normalize_study_material,
    retrieve_study_sources,
)


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
