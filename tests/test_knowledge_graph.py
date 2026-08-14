import pytest
from pydantic import ValidationError

from learning_coach.ingestion import StudyChunkRecord
from learning_coach.knowledge_graph import (
    DeterministicGraphExtractor,
    ExtractedEntity,
    ExtractedRelation,
    GraphExtractionBatch,
    ModelAugmentedGraphExtractor,
    StructuredModelGraphExtractor,
    build_concept_graph,
    explain_prerequisites,
    select_seed_concepts,
    traverse_prerequisites,
    normalize_concept_name,
    resolve_concepts,
)
from learning_coach.schemas import (
    ConceptGraph,
    ConceptNode,
    ConceptRelation,
    GraphRAGReport,
    GroundedTeaching,
    PrerequisiteExplanation,
)


def _chunk(text: str, *, index: int = 1) -> StudyChunkRecord:
    token = f"{index:064x}"
    return StudyChunkRecord(
        source_id="a" * 64,
        source_key="upload:lesson.md",
        source_type="text",
        source_name="lesson.md",
        source_uri="lesson.md",
        mime_type="text/markdown",
        content_hash="b" * 64,
        location_type="heading",
        location=f"section {index}",
        heading="知识前置图",
        chunk_id=token,
        chunk_hash=token,
        chunk_index=index,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def test_graph_schemas_are_bounded_directional_and_backward_compatible() -> None:
    prerequisite = ConceptNode(
        concept_id="a" * 64,
        name="Reducer",
        normalized_name="reducer",
        kind="technology",
        aliases=["reducer"],
        chunk_ids=["chunk-1"],
    )
    target = ConceptNode(
        concept_id="b" * 64,
        name="State 更新",
        normalized_name="state更新",
        kind="concept",
        chunk_ids=["chunk-1"],
    )
    relation = ConceptRelation(
        relation_id="c" * 64,
        from_concept_id=prerequisite.concept_id,
        to_concept_id=target.concept_id,
        relation_type="prerequisite_of",
        confidence=0.9,
        evidence_chunk_ids=["chunk-1"],
    )
    explanation = PrerequisiteExplanation(
        target_concept_id=target.concept_id,
        target_name=target.name,
        prerequisite_concept_id=prerequisite.concept_id,
        prerequisite_name=prerequisite.name,
        path_concept_ids=[prerequisite.concept_id, target.concept_id],
        path_names=[prerequisite.name, target.name],
        reason="资料显示 State 更新依赖 Reducer。",
        evidence_chunk_ids=["chunk-1"],
    )
    report = GraphRAGReport(
        extraction_mode="deterministic",
        graph_used=True,
        nodes=[prerequisite, target],
        relations=[relation],
        seed_concepts=[target.concept_id],
        expanded_concepts=[prerequisite.concept_id],
        prerequisites=[explanation],
        hybrid_candidates=1,
        graph_candidates=1,
        selected_candidates=2,
    )

    legacy = GroundedTeaching(text="旧结果")
    teaching = GroundedTeaching(text="讲解", graph_report=report)

    assert relation.from_concept_id == prerequisite.concept_id
    assert explanation.path_names == ["Reducer", "State 更新"]
    assert legacy.graph_report is None
    assert teaching.graph_report == report


def test_graph_schemas_reject_self_loops_and_resource_overflow() -> None:
    with pytest.raises(ValidationError, match="自环"):
        ConceptRelation(
            relation_id="c" * 64,
            from_concept_id="a" * 64,
            to_concept_id="a" * 64,
            relation_type="related_to",
            confidence=0.5,
        )

    with pytest.raises(ValidationError):
        ConceptNode(
            concept_id="a" * 64,
            name="Reducer",
            normalized_name="reducer",
            kind="technology",
            aliases=[f"alias-{index}" for index in range(9)],
        )

    with pytest.raises(ValidationError):
        GraphRAGReport(
            extraction_mode="deterministic",
            graph_used=False,
            nodes=[],
            relations=[],
            seed_concepts=[],
            expanded_concepts=[],
            prerequisites=[],
            hybrid_candidates=0,
            graph_candidates=0,
            selected_candidates=4,
        )


def test_deterministic_extractor_finds_chinese_teaching_relations() -> None:
    chunk = _chunk(
        "# 条件路由\n"
        "Reducer 是 State 更新的前置知识。"
        "学习条件路由前需要先理解 State。"
        "StateGraph 包含 Node。LangGraph 与 LCEL 相关。"
    )

    batch = DeterministicGraphExtractor().extract([chunk])
    relations = {
        (relation.source, relation.target, relation.relation_type)
        for relation in batch.relations
    }
    entities = {entity.name for entity in batch.entities}

    assert ("Reducer", "State 更新", "prerequisite_of") in relations
    assert ("State", "条件路由", "prerequisite_of") in relations
    assert ("Node", "StateGraph", "part_of") in relations
    assert ("LangGraph", "LCEL", "related_to") in relations
    assert {"条件路由", "StateGraph", "Reducer"} <= entities
    assert all(entity.chunk_id == chunk.chunk_id for entity in batch.entities)
    assert all(
        relation.evidence_chunk_id == chunk.chunk_id
        for relation in batch.relations
    )


def test_deterministic_extractor_finds_english_and_code_concepts() -> None:
    chunk = _chunk(
        "## Routing\n"
        "StateGraph requires TypedDict. Reducer is a prerequisite for parallel state.\n"
        "def route_after_assessment(state):\n    return state['score']\n"
    )

    batch = DeterministicGraphExtractor().extract([chunk])
    relations = {
        (relation.source, relation.target, relation.relation_type)
        for relation in batch.relations
    }
    entities = {entity.name for entity in batch.entities}

    assert ("TypedDict", "StateGraph", "prerequisite_of") in relations
    assert ("Reducer", "parallel state", "prerequisite_of") in relations
    assert {"Routing", "route_after_assessment"} <= entities


def test_deterministic_extractor_keeps_entity_only_text_relation_free() -> None:
    batch = DeterministicGraphExtractor().extract(
        [_chunk("# Reducer\nReducer 合并并行状态。")]
    )

    assert "Reducer" in {entity.name for entity in batch.entities}
    assert batch.relations == []


def test_normalization_and_alias_resolution_merge_only_confident_variants() -> None:
    entities = [
        ExtractedEntity(
            name="StateGraph",
            kind="technology",
            chunk_id="chunk-1",
        ),
        ExtractedEntity(
            name="state_graph",
            kind="code",
            chunk_id="chunk-2",
        ),
        ExtractedEntity(
            name="LangChain Expression Language",
            kind="concept",
            aliases=["LCEL"],
            chunk_id="chunk-1",
        ),
        ExtractedEntity(
            name="LCEL",
            kind="abbreviation",
            chunk_id="chunk-2",
        ),
        ExtractedEntity(
            name="Java", kind="technology", chunk_id="chunk-1"
        ),
        ExtractedEntity(name="Java", kind="concept", chunk_id="chunk-2"),
    ]

    nodes, mention_ids = resolve_concepts(entities)

    assert normalize_concept_name(" State-Graph ") == "stategraph"
    assert len(nodes) == 4
    assert mention_ids[("stategraph", "chunk-1")] == mention_ids[
        ("stategraph", "chunk-2")
    ]
    assert mention_ids[("lcel", "chunk-2")] == mention_ids[
        ("langchainexpressionlanguage", "chunk-1")
    ]
    java_nodes = [node for node in nodes if node.normalized_name == "java"]
    assert len(java_nodes) == 2


class _FakeGraphRunnable:
    def __init__(self, result: object) -> None:
        self.result = result
        self.inputs: list[object] = []

    def invoke(self, value: object) -> object:
        self.inputs.append(value)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_structured_model_extractor_validates_provenance_and_is_opt_in() -> None:
    chunk = _chunk("GraphRAG connects concepts.")
    runnable = _FakeGraphRunnable(
        {
            "entities": [
                {
                    "name": "GraphRAG",
                    "kind": "technology",
                    "chunk_id": chunk.chunk_id,
                },
                {
                    "name": "secret",
                    "kind": "concept",
                    "chunk_id": "unknown-chunk",
                },
            ],
            "relations": [],
        }
    )

    batch = StructuredModelGraphExtractor(runnable).extract([chunk])

    assert [entity.name for entity in batch.entities] == ["GraphRAG"]
    assert len(runnable.inputs) == 1


def test_model_augmentation_falls_back_to_deterministic_extraction() -> None:
    chunk = _chunk("# Reducer\nReducer 合并状态。")
    extractor = ModelAugmentedGraphExtractor(
        model=StructuredModelGraphExtractor(
            _FakeGraphRunnable(RuntimeError("private backend detail"))
        )
    )

    batch = extractor.extract([chunk])

    assert "Reducer" in {entity.name for entity in batch.entities}
    assert extractor.model_succeeded is False


def test_model_augmentation_merges_valid_structured_results() -> None:
    chunk = _chunk("# Reducer\nReducer 合并状态。")
    model_batch = GraphExtractionBatch(
        entities=[
            ExtractedEntity(
                name="State",
                kind="technology",
                chunk_id=chunk.chunk_id,
            )
        ]
    )
    extractor = ModelAugmentedGraphExtractor(
        model=StructuredModelGraphExtractor(_FakeGraphRunnable(model_batch))
    )

    batch = extractor.extract([chunk])

    assert {"Reducer", "State"} <= {entity.name for entity in batch.entities}
    assert extractor.model_succeeded is True


class _FixedExtractor:
    def __init__(self, batch: GraphExtractionBatch) -> None:
        self.batch = batch
        self.received = 0

    def extract(self, chunks: object) -> GraphExtractionBatch:
        self.received = len(chunks)  # type: ignore[arg-type]
        return self.batch


def test_build_concept_graph_is_stable_deduplicated_and_evidenced() -> None:
    chunks = [_chunk("one", index=1), _chunk("two", index=2)]
    batch = GraphExtractionBatch(
        entities=[
            ExtractedEntity(
                name="Reducer", kind="technology", chunk_id=chunks[0].chunk_id
            ),
            ExtractedEntity(
                name="State", kind="technology", chunk_id=chunks[0].chunk_id
            ),
            ExtractedEntity(
                name="Reducer", kind="technology", chunk_id=chunks[1].chunk_id
            ),
            ExtractedEntity(
                name="State", kind="technology", chunk_id=chunks[1].chunk_id
            ),
        ],
        relations=[
            ExtractedRelation(
                source="Reducer",
                target="State",
                relation_type="prerequisite_of",
                confidence=0.8,
                evidence_chunk_id=chunks[0].chunk_id,
            ),
            ExtractedRelation(
                source="Reducer",
                target="State",
                relation_type="prerequisite_of",
                confidence=0.95,
                evidence_chunk_id=chunks[1].chunk_id,
            ),
            ExtractedRelation(
                source="State",
                target="State",
                relation_type="related_to",
                confidence=1,
                evidence_chunk_id=chunks[0].chunk_id,
            ),
        ],
    )

    first = build_concept_graph(chunks, extractor=_FixedExtractor(batch))
    second = build_concept_graph(chunks, extractor=_FixedExtractor(batch))

    assert isinstance(first, ConceptGraph)
    assert first == second
    assert len(first.nodes) == 2
    assert len(first.relations) == 1
    relation = first.relations[0]
    assert relation.confidence == 0.95
    assert relation.evidence_chunk_ids == [
        chunks[0].chunk_id,
        chunks[1].chunk_id,
    ]


def test_build_concept_graph_applies_input_node_and_relation_limits() -> None:
    chunks = [_chunk(f"chunk {index}", index=index) for index in range(1, 30)]
    entities = [
        ExtractedEntity(
            name=f"Concept{index}",
            kind="technology",
            chunk_id=chunks[index % len(chunks)].chunk_id,
        )
        for index in range(100)
    ]
    relations = [
        ExtractedRelation(
            source=f"Concept{index % 79}",
            target=f"Concept{(index + 1) % 79}",
            relation_type="related_to",
            confidence=0.5,
            evidence_chunk_id=chunks[index % len(chunks)].chunk_id,
        )
        for index in range(220)
    ]
    extractor = _FixedExtractor(
        GraphExtractionBatch(entities=entities, relations=relations)
    )

    graph = build_concept_graph(chunks, extractor=extractor)

    assert extractor.received == 24
    assert len(graph.nodes) <= 80
    assert len(graph.relations) <= 160


def test_seed_selection_uses_query_alias_context_and_hybrid_chunks() -> None:
    chunks = [
        _chunk(
            "LangChain Expression Language（LCEL） 是 Runnable 的前置知识。",
            index=1,
        ),
        _chunk("Reducer 是 State 更新的前置知识。", index=2),
    ]
    graph = build_concept_graph(chunks)
    by_name = {node.name: node for node in graph.nodes}

    seeds = select_seed_concepts(
        graph,
        query="我想掌握 LCEL",
        context=["Runnable 组合"],
        seed_chunk_ids=[chunks[1].chunk_id],
    )

    assert by_name["LangChain Expression Language"].concept_id in seeds
    assert by_name["Runnable"].concept_id in seeds
    assert by_name["Reducer"].concept_id in seeds


def test_prerequisite_traversal_handles_chains_branches_and_cycles() -> None:
    chunks = [
        _chunk("基础 A 是 State 的前置知识。", index=1),
        _chunk("基础 B 是 State 的前置知识。", index=2),
        _chunk("State 是 Reducer 的前置知识。", index=3),
        _chunk("Reducer 是 条件路由 的前置知识。", index=4),
        _chunk("条件路由 是 基础 A 的前置知识。", index=5),
    ]
    graph = build_concept_graph(chunks)
    target = next(
        node for node in graph.nodes if node.name == "条件路由"
    )

    paths = traverse_prerequisites(graph, [target.concept_id])

    assert paths
    assert len(paths) <= 5
    assert all(path.concept_ids[-1] == target.concept_id for path in paths)
    assert all(len(path.concept_ids) <= 4 for path in paths)
    assert all(len(set(path.concept_ids)) == len(path.concept_ids) for path in paths)
    assert any(len(path.concept_ids) == 4 for path in paths)
    assert paths == traverse_prerequisites(graph, [target.concept_id])


def test_prerequisite_traversal_returns_empty_for_unknown_or_unrelated_seed() -> None:
    graph = build_concept_graph([_chunk("LangGraph 与 LCEL 相关。")])
    known = graph.nodes[0].concept_id

    assert traverse_prerequisites(graph, ["f" * 64]) == []
    assert traverse_prerequisites(graph, [known]) == []


def test_prerequisite_explanations_connect_gap_path_and_source_location() -> None:
    chunks = [
        _chunk("State 是 Reducer 的前置知识。", index=1),
        _chunk("Reducer 是 条件路由 的前置知识。", index=2),
    ]
    graph = build_concept_graph(chunks)
    target = next(node for node in graph.nodes if node.name == "条件路由")

    explanations = explain_prerequisites(
        graph,
        [target.concept_id],
        gap_context={
            "missing_point": "State 的结构不清楚",
            "recent_errors": ["忘记 State 字段"],
        },
        chunks=chunks,
    )

    state = next(
        item for item in explanations if item.prerequisite_name == "State"
    )
    assert state.path_names == ["State", "Reducer", "条件路由"]
    assert "当前薄弱信息" in state.reason
    assert "State → Reducer → 条件路由" in state.reason
    assert state.evidence_chunk_ids == [chunks[0].chunk_id, chunks[1].chunk_id]
    assert state.evidence_locations == [
        "lesson.md · section 1",
        "lesson.md · section 2",
    ]


def test_prerequisite_explanations_are_empty_without_evidenced_path() -> None:
    node = ConceptNode(
        concept_id="a" * 64,
        name="孤立概念",
        normalized_name="孤立概念",
        kind="concept",
    )
    graph = ConceptGraph(
        extraction_mode="deterministic", nodes=[node], relations=[]
    )

    assert explain_prerequisites(graph, [node.concept_id], gap_context={}) == []
    build_concept_graph,
