from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from learning_coach.hybrid_rag import (
    HybridRetrievalResult,
    HybridStudyRetriever,
    RankedChunk,
    create_hybrid_retriever,
)
from learning_coach.ingestion import StudyChunkRecord
from learning_coach.schemas import (
    ConceptGraph,
    ConceptKind,
    ConceptNode,
    ConceptRelation,
    ConceptRelationType,
    GraphExtractionMode,
    GraphRAGReport,
    PrerequisiteExplanation,
    RetrievalScore,
    StudySource,
)

MAX_GRAPH_INPUT_CHUNKS = 24
MAX_GRAPH_CHUNK_CHARS = 4_000
MAX_GRAPH_NODES = 80
MAX_GRAPH_RELATIONS = 160
MAX_GRAPH_DEPTH = 3
MAX_GRAPH_VISITED_NODES = 24
MAX_PREREQUISITE_PATHS = 5

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_CODE_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_ENGLISH_CONCEPT = r"[A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z][A-Za-z0-9_.-]*){0,3}"
_STOP_IDENTIFIERS = {
    "and",
    "are",
    "before",
    "class",
    "def",
    "else",
    "for",
    "from",
    "import",
    "into",
    "return",
    "the",
    "then",
    "this",
    "with",
}
_EXPLICIT_ALIAS = re.compile(
    r"^(.{2,100}?)\s*[（(]([A-Za-z][A-Za-z0-9_.-]{1,20})[）)]$"
)


class ExtractedEntity(BaseModel):
    """One extractor mention before cross-chunk disambiguation."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    kind: ConceptKind = "concept"
    chunk_id: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list, max_length=8)


class ExtractedRelation(BaseModel):
    """One named relation before concept IDs are assigned."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    relation_type: ConceptRelationType
    confidence: float = Field(ge=0, le=1)
    evidence_chunk_id: str = Field(min_length=1)


class GraphExtractionBatch(BaseModel):
    """Validated intermediate output shared by deterministic and model extractors."""

    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=256)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=256)


class EntityRelationExtractor(Protocol):
    """Injectable contract for bounded entity and relation extraction."""

    def extract(
        self, chunks: Sequence[StudyChunkRecord]
    ) -> GraphExtractionBatch: ...


def _clean_concept(value: str) -> str:
    cleaned = value.strip().strip("`*_#'\"()[]{}<>，,：:；;。.!！？?")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned[:128].strip()


def normalize_concept_name(value: str) -> str:
    """Create a Unicode- and identifier-stable concept lookup key."""

    normalized = unicodedata.normalize("NFKC", _clean_concept(value)).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)[:128]


def _concept_and_aliases(value: str) -> tuple[str, list[str]]:
    concept = _clean_concept(value)
    match = _EXPLICIT_ALIAS.match(concept)
    if match is None:
        return concept, []
    name = _clean_concept(match.group(1))
    alias = _clean_concept(match.group(2))
    return name, [alias] if alias and alias.casefold() != name.casefold() else []


def _concept_kind(value: str) -> ConceptKind:
    if "_" in value or "." in value:
        return "code"
    letters = "".join(character for character in value if character.isalpha())
    if letters and letters.isupper() and len(letters) <= 12:
        return "abbreviation"
    if re.search(r"[a-z][A-Z]|[A-Z].*[A-Z]", value):
        return "technology"
    return "concept"


class DeterministicGraphExtractor:
    """Extract explicit teaching relations without model or network calls."""

    def extract(
        self, chunks: Sequence[StudyChunkRecord]
    ) -> GraphExtractionBatch:
        entities: list[ExtractedEntity] = []
        relations: list[ExtractedRelation] = []
        seen_entities: set[tuple[str, str]] = set()
        seen_relations: set[tuple[str, str, ConceptRelationType, str]] = set()

        for chunk in chunks[:MAX_GRAPH_INPUT_CHUNKS]:
            text = chunk.text[:MAX_GRAPH_CHUNK_CHARS]

            def add_entity(name: str) -> str:
                concept, aliases = _concept_and_aliases(name)
                if not concept:
                    return ""
                key = (concept.casefold(), chunk.chunk_id)
                if key not in seen_entities:
                    seen_entities.add(key)
                    entities.append(
                        ExtractedEntity(
                            name=concept,
                            kind=_concept_kind(concept),
                            chunk_id=chunk.chunk_id,
                            aliases=aliases,
                        )
                    )
                return concept

            def add_relation(
                source: str,
                target: str,
                relation_type: ConceptRelationType,
                confidence: float,
            ) -> None:
                source_name = add_entity(source)
                target_name = add_entity(target)
                if (
                    not source_name
                    or not target_name
                    or source_name.casefold() == target_name.casefold()
                ):
                    return
                key = (
                    source_name.casefold(),
                    target_name.casefold(),
                    relation_type,
                    chunk.chunk_id,
                )
                if key in seen_relations:
                    return
                seen_relations.add(key)
                relations.append(
                    ExtractedRelation(
                        source=source_name,
                        target=target_name,
                        relation_type=relation_type,
                        confidence=confidence,
                        evidence_chunk_id=chunk.chunk_id,
                    )
                )

            for heading in _HEADING.findall(text):
                add_entity(heading)

            sentences = [
                sentence.strip()
                for sentence in re.split(r"[。！？!?;；\n]+|(?<=\w)\.\s+", text)
                if sentence.strip() and not sentence.lstrip().startswith("#")
            ]
            for sentence in sentences:
                self._extract_sentence(sentence, add_relation)

            for identifier in _CODE_IDENTIFIER.findall(text):
                if identifier.casefold() in _STOP_IDENTIFIERS:
                    continue
                if (
                    "_" in identifier
                    or identifier.isupper()
                    or re.search(r"[a-z][A-Z]|[A-Z].*[A-Z]", identifier)
                ):
                    add_entity(identifier)

        return GraphExtractionBatch(entities=entities, relations=relations)

    @staticmethod
    def _extract_sentence(
        sentence: str,
        add_relation: Callable[[str, str, ConceptRelationType, float], None],
    ) -> None:
        patterns: tuple[
            tuple[re.Pattern[str], str, str, ConceptRelationType, float], ...
        ] = (
            (
                re.compile(r"^(.{1,64}?)\s*是\s*(.{1,64}?)\s*的前置(?:知识|概念)?$"),
                "source",
                "target",
                "prerequisite_of",
                0.95,
            ),
            (
                re.compile(r"^学习\s*(.{1,64}?)\s*前(?:需要|应当|要)?\s*先?(?:理解|掌握|学习)\s*(.{1,64}?)$"),
                "second",
                "first",
                "prerequisite_of",
                0.95,
            ),
            (
                re.compile(r"^(.{1,64}?)\s*(?:依赖|建立在)\s*(.{1,64}?)$"),
                "second",
                "first",
                "prerequisite_of",
                0.9,
            ),
            (
                re.compile(r"^(.{1,64}?)\s*包含\s*(.{1,64}?)$"),
                "second",
                "first",
                "part_of",
                0.9,
            ),
            (
                re.compile(r"^(.{1,64}?)\s*是\s*(.{1,64}?)\s*的组成部分$"),
                "first",
                "second",
                "part_of",
                0.9,
            ),
            (
                re.compile(r"^(.{1,64}?)\s*与\s*(.{1,64}?)\s*(?:相关|关联)$"),
                "first",
                "second",
                "related_to",
                0.75,
            ),
            (
                re.compile(
                    rf"^({_ENGLISH_CONCEPT})\s+requires\s+({_ENGLISH_CONCEPT})$",
                    re.IGNORECASE,
                ),
                "second",
                "first",
                "prerequisite_of",
                0.95,
            ),
            (
                re.compile(
                    rf"^({_ENGLISH_CONCEPT})\s+is\s+(?:a|an)\s+prerequisite\s+for\s+({_ENGLISH_CONCEPT})$",
                    re.IGNORECASE,
                ),
                "first",
                "second",
                "prerequisite_of",
                0.95,
            ),
        )
        for pattern, source_key, target_key, relation_type, confidence in patterns:
            match = pattern.match(sentence)
            if match is None:
                continue
            first, second = match.group(1), match.group(2)
            values = {
                "first": first,
                "second": second,
                "source": first,
                "target": second,
            }
            add_relation(
                values[source_key],
                values[target_key],
                relation_type,
                confidence,
            )
            return


def resolve_concepts(
    entities: Sequence[ExtractedEntity],
) -> tuple[list[ConceptNode], dict[tuple[str, str], str]]:
    """Resolve confident aliases while keeping incompatible same names apart."""

    if not entities:
        return [], {}
    parents = list(range(len(entities)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    by_normalized: dict[str, list[int]] = {}
    alias_owners: dict[str, list[int]] = {}
    for index, entity in enumerate(entities):
        normalized = normalize_concept_name(entity.name)
        if normalized:
            by_normalized.setdefault(normalized, []).append(index)
        for alias in entity.aliases:
            alias_key = normalize_concept_name(alias)
            if alias_key:
                alias_owners.setdefault(alias_key, []).append(index)

    for indexes in by_normalized.values():
        for left_offset, left in enumerate(indexes):
            for right in indexes[left_offset + 1 :]:
                left_entity = entities[left]
                right_entity = entities[right]
                identifier_variant = any(
                    separator in left_entity.name or separator in right_entity.name
                    for separator in ("_", "-", ".", " ")
                )
                if left_entity.kind == right_entity.kind or identifier_variant:
                    union(left, right)

    for alias, owners in alias_owners.items():
        targets = by_normalized.get(alias, [])
        for owner in owners:
            for target in targets:
                union(owner, target)
        for owner in owners[1:]:
            union(owners[0], owner)

    groups: dict[int, list[int]] = {}
    for index in range(len(entities)):
        groups.setdefault(find(index), []).append(index)

    kind_order = {"technology": 0, "concept": 1, "code": 2, "abbreviation": 3}
    nodes: list[ConceptNode] = []
    group_ids: dict[int, str] = {}
    for root, indexes in groups.items():
        ordered = sorted(
            (entities[index] for index in indexes),
            key=lambda entity: (
                kind_order[entity.kind],
                sum(separator in entity.name for separator in ("_", "-", ".")),
                -len(entity.name),
                entity.name.casefold(),
            ),
        )
        canonical = ordered[0]
        normalized = normalize_concept_name(canonical.name)
        concept_id = hashlib.sha256(
            f"{normalized}\0{canonical.kind}".encode("utf-8")
        ).hexdigest()
        aliases = sorted(
            {
                alias
                for entity in ordered
                for alias in [entity.name, *entity.aliases]
                if alias.casefold() != canonical.name.casefold()
            },
            key=lambda alias: (alias.casefold(), alias),
        )[:8]
        chunk_ids = list(
            dict.fromkeys(entity.chunk_id for entity in ordered)
        )[:12]
        nodes.append(
            ConceptNode(
                concept_id=concept_id,
                name=canonical.name,
                normalized_name=normalized,
                kind=canonical.kind,
                aliases=aliases,
                chunk_ids=chunk_ids,
            )
        )
        group_ids[root] = concept_id

    nodes.sort(key=lambda node: (node.normalized_name, node.kind, node.concept_id))
    mention_ids = {
        (normalize_concept_name(entity.name), entity.chunk_id): group_ids[find(index)]
        for index, entity in enumerate(entities)
    }
    for index, entity in enumerate(entities):
        for alias in entity.aliases:
            mention_ids[(normalize_concept_name(alias), entity.chunk_id)] = group_ids[
                find(index)
            ]
    return nodes, mention_ids


class StructuredModelGraphExtractor:
    """Validate explicitly injected structured model output and its provenance."""

    def __init__(self, runnable: Any) -> None:
        self._runnable = runnable
        self.last_succeeded = False

    def extract(
        self, chunks: Sequence[StudyChunkRecord]
    ) -> GraphExtractionBatch:
        selected = list(chunks[:MAX_GRAPH_INPUT_CHUNKS])
        allowed_chunk_ids = {chunk.chunk_id for chunk in selected}
        payload = {
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "source_name": chunk.source_name,
                    "location": chunk.location,
                    "text": chunk.text[:MAX_GRAPH_CHUNK_CHARS],
                }
                for chunk in selected
            ],
            "relation_types": [
                "prerequisite_of",
                "part_of",
                "related_to",
            ],
        }
        try:
            raw = self._runnable.invoke(payload)
            batch = (
                raw
                if isinstance(raw, GraphExtractionBatch)
                else GraphExtractionBatch.model_validate(raw)
            )
        except Exception:
            self.last_succeeded = False
            return GraphExtractionBatch()
        self.last_succeeded = True
        return GraphExtractionBatch(
            entities=[
                entity
                for entity in batch.entities
                if entity.chunk_id in allowed_chunk_ids
            ],
            relations=[
                relation
                for relation in batch.relations
                if relation.evidence_chunk_id in allowed_chunk_ids
            ],
        )


class ModelAugmentedGraphExtractor:
    """Merge deterministic evidence with an opt-in model extractor."""

    def __init__(
        self,
        *,
        model: StructuredModelGraphExtractor,
        deterministic: DeterministicGraphExtractor | None = None,
    ) -> None:
        self._deterministic = deterministic or DeterministicGraphExtractor()
        self._model = model
        self.model_succeeded = False

    def extract(
        self, chunks: Sequence[StudyChunkRecord]
    ) -> GraphExtractionBatch:
        deterministic = self._deterministic.extract(chunks)
        augmented = self._model.extract(chunks)
        self.model_succeeded = self._model.last_succeeded
        entities = list(deterministic.entities)
        entity_keys = {
            (entity.name.casefold(), entity.kind, entity.chunk_id)
            for entity in entities
        }
        for entity in augmented.entities:
            key = (entity.name.casefold(), entity.kind, entity.chunk_id)
            if key not in entity_keys:
                entity_keys.add(key)
                entities.append(entity)
        relations = list(deterministic.relations)
        relation_keys = {
            (
                relation.source.casefold(),
                relation.target.casefold(),
                relation.relation_type,
                relation.evidence_chunk_id,
            )
            for relation in relations
        }
        for relation in augmented.relations:
            key = (
                relation.source.casefold(),
                relation.target.casefold(),
                relation.relation_type,
                relation.evidence_chunk_id,
            )
            if key not in relation_keys:
                relation_keys.add(key)
                relations.append(relation)
        return GraphExtractionBatch(entities=entities, relations=relations)


def _relation_concept_id(
    name: str,
    chunk_id: str,
    nodes: Sequence[ConceptNode],
    mention_ids: dict[tuple[str, str], str],
) -> str | None:
    normalized = normalize_concept_name(name)
    direct = mention_ids.get((normalized, chunk_id))
    if direct is not None:
        return direct
    candidates = [
        node
        for node in nodes
        if normalized
        in {
            node.normalized_name,
            *(normalize_concept_name(alias) for alias in node.aliases),
        }
    ]
    candidates.sort(
        key=lambda node: (
            chunk_id not in node.chunk_ids,
            node.kind,
            node.concept_id,
        )
    )
    return candidates[0].concept_id if candidates else None


def build_concept_graph(
    chunks: Sequence[StudyChunkRecord],
    *,
    extractor: EntityRelationExtractor | None = None,
) -> ConceptGraph:
    """Build a stable, bounded graph without mutating source chunks."""

    selected = list(chunks[:MAX_GRAPH_INPUT_CHUNKS])
    active_extractor = extractor or DeterministicGraphExtractor()
    extraction_mode: GraphExtractionMode = "deterministic"
    try:
        batch = active_extractor.extract(selected)
        if isinstance(active_extractor, ModelAugmentedGraphExtractor):
            extraction_mode = (
                "model_augmented"
                if active_extractor.model_succeeded
                else "fallback"
            )
    except Exception:
        batch = DeterministicGraphExtractor().extract(selected)
        extraction_mode = "fallback"

    nodes, mention_ids = resolve_concepts(batch.entities)
    nodes = nodes[:MAX_GRAPH_NODES]
    allowed_ids = {node.concept_id for node in nodes}
    aggregated: dict[
        tuple[str, str, ConceptRelationType], dict[str, object]
    ] = {}
    for extracted in batch.relations:
        source_id = _relation_concept_id(
            extracted.source,
            extracted.evidence_chunk_id,
            nodes,
            mention_ids,
        )
        target_id = _relation_concept_id(
            extracted.target,
            extracted.evidence_chunk_id,
            nodes,
            mention_ids,
        )
        if (
            source_id is None
            or target_id is None
            or source_id == target_id
            or source_id not in allowed_ids
            or target_id not in allowed_ids
        ):
            continue
        key = (source_id, target_id, extracted.relation_type)
        item = aggregated.setdefault(
            key,
            {
                "confidence": 0.0,
                "evidence_chunk_ids": [],
            },
        )
        item["confidence"] = max(
            float(item["confidence"]), extracted.confidence
        )
        evidence = item["evidence_chunk_ids"]
        assert isinstance(evidence, list)
        if (
            extracted.evidence_chunk_id not in evidence
            and len(evidence) < 8
        ):
            evidence.append(extracted.evidence_chunk_id)

    relations: list[ConceptRelation] = []
    for (source_id, target_id, relation_type), item in sorted(
        aggregated.items(), key=lambda pair: pair[0]
    )[:MAX_GRAPH_RELATIONS]:
        relation_id = hashlib.sha256(
            f"{source_id}\0{target_id}\0{relation_type}".encode("utf-8")
        ).hexdigest()
        evidence = item["evidence_chunk_ids"]
        assert isinstance(evidence, list)
        relations.append(
            ConceptRelation(
                relation_id=relation_id,
                from_concept_id=source_id,
                to_concept_id=target_id,
                relation_type=relation_type,
                confidence=float(item["confidence"]),
                evidence_chunk_ids=evidence,
            )
        )
    return ConceptGraph(
        extraction_mode=extraction_mode,
        nodes=nodes,
        relations=relations,
    )


@dataclass(frozen=True)
class PrerequisitePath:
    """One cycle-free path ordered from prerequisite to target."""

    concept_ids: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]
    confidence: float


def select_seed_concepts(
    graph: ConceptGraph,
    *,
    query: str,
    context: Sequence[str] = (),
    seed_chunk_ids: Sequence[str] = (),
    limit: int = 12,
) -> list[str]:
    """Select query, learning-context and Hybrid-hit concepts as graph seeds."""

    if limit <= 0 or limit > 12:
        raise ValueError("limit 必须在 1 到 12 之间。")
    normalized_query = normalize_concept_name(query)
    normalized_context = normalize_concept_name(" ".join(context))
    chunk_ids = set(seed_chunk_ids)
    ranked: list[tuple[int, str]] = []
    for node in graph.nodes:
        names = [node.normalized_name, *map(normalize_concept_name, node.aliases)]
        score = 0
        if any(name and name in normalized_query for name in names):
            score += 4
        if any(name and name in normalized_context for name in names):
            score += 2
        if chunk_ids.intersection(node.chunk_ids):
            score += 1
        if score:
            ranked.append((score, node.concept_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [concept_id for _, concept_id in ranked[:limit]]


def traverse_prerequisites(
    graph: ConceptGraph,
    target_concept_ids: Sequence[str],
    *,
    max_depth: int = MAX_GRAPH_DEPTH,
    max_visited: int = MAX_GRAPH_VISITED_NODES,
    max_paths: int = MAX_PREREQUISITE_PATHS,
) -> list[PrerequisitePath]:
    """Walk incoming prerequisite edges with hard depth and visit limits."""

    if not 1 <= max_depth <= MAX_GRAPH_DEPTH:
        raise ValueError(f"max_depth 必须在 1 到 {MAX_GRAPH_DEPTH} 之间。")
    if not 1 <= max_visited <= MAX_GRAPH_VISITED_NODES:
        raise ValueError(
            f"max_visited 必须在 1 到 {MAX_GRAPH_VISITED_NODES} 之间。"
        )
    if not 1 <= max_paths <= MAX_PREREQUISITE_PATHS:
        raise ValueError(
            f"max_paths 必须在 1 到 {MAX_PREREQUISITE_PATHS} 之间。"
        )

    known_ids = {node.concept_id for node in graph.nodes}
    incoming: dict[str, list[ConceptRelation]] = {}
    for relation in graph.relations:
        if relation.relation_type == "prerequisite_of":
            incoming.setdefault(relation.to_concept_id, []).append(relation)
    for relations in incoming.values():
        relations.sort(
            key=lambda relation: (
                relation.from_concept_id,
                -relation.confidence,
                relation.relation_id,
            )
        )

    targets = sorted(
        dict.fromkeys(
            concept_id
            for concept_id in target_concept_ids
            if concept_id in known_ids
        )
    )
    queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], float, int]] = deque(
        (target, (target,), (), 1.0, 0) for target in targets
    )
    visited = set(targets)
    paths: list[PrerequisitePath] = []
    while queue and len(paths) < max_paths:
        current, current_path, evidence, confidence, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for relation in incoming.get(current, []):
            prerequisite = relation.from_concept_id
            if prerequisite in current_path:
                continue
            next_path = (prerequisite, *current_path)
            next_evidence = tuple(
                dict.fromkeys((*relation.evidence_chunk_ids, *evidence))
            )[:8]
            next_confidence = min(confidence, relation.confidence)
            paths.append(
                PrerequisitePath(
                    concept_ids=next_path,
                    evidence_chunk_ids=next_evidence,
                    confidence=round(next_confidence, 6),
                )
            )
            if len(paths) >= max_paths:
                break
            if prerequisite not in visited and len(visited) < max_visited:
                visited.add(prerequisite)
                queue.append(
                    (
                        prerequisite,
                        next_path,
                        next_evidence,
                        next_confidence,
                        depth + 1,
                    )
                )
    return paths


def _flatten_context(values: Mapping[str, Any]) -> list[str]:
    clauses: list[str] = []
    for key in ("missing_point", "recent_errors", "diagnostic_focus", "feedback"):
        value = values.get(key)
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            clauses.extend(str(item) for item in value if str(item).strip())
        elif value is not None and str(value).strip():
            clauses.append(str(value))
    return clauses


def explain_prerequisites(
    graph: ConceptGraph,
    target_concept_ids: Sequence[str],
    *,
    gap_context: Mapping[str, Any],
    chunks: Sequence[StudyChunkRecord] = (),
) -> list[PrerequisiteExplanation]:
    """Explain evidenced prerequisite paths without inferring mastery."""

    nodes = {node.concept_id: node for node in graph.nodes}
    chunk_locations = {
        chunk.chunk_id: f"{chunk.source_name} · {chunk.location}"
        for chunk in chunks
    }
    normalized_gap = normalize_concept_name(" ".join(_flatten_context(gap_context)))
    ranked: list[tuple[bool, int, PrerequisiteExplanation]] = []
    for path in traverse_prerequisites(graph, target_concept_ids):
        if not path.evidence_chunk_ids:
            continue
        prerequisite = nodes.get(path.concept_ids[0])
        target = nodes.get(path.concept_ids[-1])
        if prerequisite is None or target is None:
            continue
        path_nodes = [nodes.get(concept_id) for concept_id in path.concept_ids]
        if any(node is None for node in path_nodes):
            continue
        path_names = [node.name for node in path_nodes if node is not None]
        names = [
            prerequisite.normalized_name,
            *map(normalize_concept_name, prerequisite.aliases),
        ]
        matched = any(name and name in normalized_gap for name in names)
        path_text = " → ".join(path_names)
        if matched:
            reason = (
                f"当前薄弱信息提到“{prerequisite.name}”；资料中的前置路径"
                f"“{path_text}”说明应先补这一概念。"
            )
        else:
            reason = (
                f"要理解“{target.name}”，资料显示需先掌握"
                f"“{prerequisite.name}”；前置路径为“{path_text}”。"
            )
        explanation = PrerequisiteExplanation(
            target_concept_id=target.concept_id,
            target_name=target.name,
            prerequisite_concept_id=prerequisite.concept_id,
            prerequisite_name=prerequisite.name,
            path_concept_ids=list(path.concept_ids),
            path_names=path_names,
            reason=reason,
            evidence_chunk_ids=list(path.evidence_chunk_ids),
            evidence_locations=[
                chunk_locations[chunk_id]
                for chunk_id in path.evidence_chunk_ids
                if chunk_id in chunk_locations
            ],
        )
        ranked.append((matched, len(path.concept_ids), explanation))
    ranked.sort(
        key=lambda item: (
            not item[0],
            -item[1],
            item[2].prerequisite_concept_id,
        )
    )
    return [item[2] for item in ranked[:MAX_PREREQUISITE_PATHS]]


def rank_graph_evidence(
    query: str,
    graph: ConceptGraph,
    paths: Sequence[PrerequisitePath],
    chunks: Sequence[StudyChunkRecord],
    *,
    limit: int = MAX_GRAPH_VISITED_NODES,
) -> list[RankedChunk]:
    """Rank graph-evidenced chunks on a deterministic shared scale."""

    if not 1 <= limit <= MAX_GRAPH_VISITED_NODES:
        raise ValueError(
            f"limit 必须在 1 到 {MAX_GRAPH_VISITED_NODES} 之间。"
        )
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    normalized_query = normalize_concept_name(query)
    scores: dict[str, float] = {}
    order: dict[str, int] = {}
    encounter = 0
    for path in paths:
        distance = max(1, len(path.concept_ids) - 1)
        distance_score = 1 / distance
        for chunk_id in path.evidence_chunk_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            if chunk_id not in order:
                order[chunk_id] = encounter
                encounter += 1
            normalized_text = normalize_concept_name(chunk.text)
            query_match = float(
                bool(
                    normalized_query
                    and (
                        normalized_query in normalized_text
                        or any(
                            token in normalized_text
                            for token in re.findall(
                                r"[a-z0-9_]{2,}|[\u3400-\u9fff]{2,}",
                                query.casefold(),
                            )
                        )
                    )
                )
            )
            score = min(
                1.0,
                0.55 * path.confidence
                + 0.30 * distance_score
                + 0.15 * query_match,
            )
            scores[chunk_id] = max(scores.get(chunk_id, 0.0), score)
    if not scores:
        return []
    maximum = max(scores.values())
    ranked_ids = sorted(scores, key=lambda key: (-scores[key], order[key]))[:limit]
    return [
        RankedChunk(
            chunk=chunk_by_id[chunk_id],
            score=round(scores[chunk_id] / maximum, 6),
        )
        for chunk_id in ranked_ids
    ]


def fuse_graph_rankings(
    hybrid_sources: Sequence[StudySource],
    graph_ranked: Sequence[RankedChunk],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[StudySource]:
    """Fuse Hybrid and graph ranks while preserving per-channel trace fields."""

    if top_k <= 0 or top_k > 3:
        raise ValueError("top_k 必须在 1 到 3 之间。")
    if rank_constant <= 0:
        raise ValueError("rank_constant 必须是正整数。")
    if not graph_ranked:
        return list(hybrid_sources[:top_k])

    candidates: dict[str, dict[str, Any]] = {}
    encounter = 0
    for channel, ranked in (
        ("hybrid", list(hybrid_sources)),
        ("graph", list(graph_ranked)),
    ):
        for rank, item in enumerate(ranked, start=1):
            if channel == "hybrid":
                source = item
                assert isinstance(source, StudySource)
                source_id = source.source_id
                graph_score = 0.0
            else:
                graph_item = item
                assert isinstance(graph_item, RankedChunk)
                chunk = graph_item.chunk
                source_id = chunk.chunk_id
                graph_score = graph_item.score
                source = StudySource(
                    source_id=chunk.chunk_id,
                    text=chunk.text,
                    score=max(graph_item.score, 0.000001),
                    source_name=chunk.source_name,
                    source_uri=chunk.source_uri,
                    source_type=chunk.source_type,
                    location=chunk.location,
                    chunk_hash=chunk.chunk_hash,
                    retrieval_score=RetrievalScore(
                        keyword=0,
                        embedding=0,
                        fusion=0,
                        rerank=0,
                        graph=graph_item.score,
                    ),
                    retrieval_attempt=1,
                )
            if source_id not in candidates:
                candidates[source_id] = {
                    "source": source,
                    "graph_score": graph_score,
                    "rrf": 0.0,
                    "order": encounter,
                }
                encounter += 1
            candidate = candidates[source_id]
            candidate["rrf"] = float(candidate["rrf"]) + 1 / (
                rank_constant + rank
            )
            candidate["graph_score"] = max(
                float(candidate["graph_score"]), graph_score
            )

    maximum = max(float(item["rrf"]) for item in candidates.values())
    ordered = sorted(
        candidates.values(),
        key=lambda item: (-float(item["rrf"]), int(item["order"])),
    )[:top_k]
    fused: list[StudySource] = []
    for item in ordered:
        source = item["source"]
        assert isinstance(source, StudySource)
        final_score = round(float(item["rrf"]) / maximum, 6)
        existing_score = source.retrieval_score or RetrievalScore(
            keyword=0,
            embedding=0,
            fusion=0,
            rerank=source.score,
        )
        traced_score = existing_score.model_copy(
            update={
                "graph": round(float(item["graph_score"]), 6),
                "graph_fusion": final_score,
            }
        )
        fused.append(
            source.model_copy(
                update={
                    "score": max(final_score, 0.000001),
                    "retrieval_score": traced_score,
                }
            )
        )
    return fused


class GraphStudyRetriever:
    """Add bounded concept-graph expansion to the existing Hybrid retriever."""

    def __init__(
        self,
        *,
        hybrid: HybridStudyRetriever | Any | None = None,
        extractor: EntityRelationExtractor | None = None,
    ) -> None:
        self.hybrid = hybrid or HybridStudyRetriever()
        self.extractor = extractor
        self.settings = self.hybrid.settings

    def retrieve(
        self,
        query: str,
        chunks: Sequence[StudyChunkRecord],
        *,
        rewrite_context: Mapping[str, Any] | None = None,
    ) -> HybridRetrievalResult:
        hybrid_result = self.hybrid.retrieve(
            query,
            chunks,
            rewrite_context=rewrite_context,
        )
        context = rewrite_context or {}
        try:
            graph = build_concept_graph(chunks, extractor=self.extractor)
            seeds = select_seed_concepts(
                graph,
                query=query,
                context=_flatten_context(context),
                seed_chunk_ids=[
                    source.source_id for source in hybrid_result.sources
                ],
            )
            paths = traverse_prerequisites(graph, seeds) if seeds else []
            explanations = explain_prerequisites(
                graph,
                seeds,
                gap_context=context,
                chunks=chunks,
            ) if seeds else []
            graph_ranked = rank_graph_evidence(
                query,
                graph,
                paths,
                chunks,
            ) if paths else []
            sources = fuse_graph_rankings(
                hybrid_result.sources,
                graph_ranked,
                top_k=self.settings.top_k,
            )
            expanded = list(
                dict.fromkeys(
                    concept_id
                    for path in paths
                    for concept_id in path.concept_ids[:-1]
                )
            )[:MAX_GRAPH_VISITED_NODES]
            graph_report = GraphRAGReport(
                extraction_mode=graph.extraction_mode,
                graph_used=bool(graph_ranked or explanations),
                nodes=graph.nodes,
                relations=graph.relations,
                seed_concepts=seeds,
                expanded_concepts=expanded,
                prerequisites=explanations,
                hybrid_candidates=len(hybrid_result.sources),
                graph_candidates=len(graph_ranked),
                selected_candidates=len(sources),
            )
        except Exception:
            sources = list(hybrid_result.sources)
            graph_report = GraphRAGReport(
                extraction_mode="fallback",
                graph_used=False,
                nodes=[],
                relations=[],
                seed_concepts=[],
                expanded_concepts=[],
                prerequisites=[],
                hybrid_candidates=len(hybrid_result.sources),
                graph_candidates=0,
                selected_candidates=len(sources),
            )
        return HybridRetrievalResult(
            sources=sources,
            report=hybrid_result.report,
            graph_report=graph_report,
        )


def create_graph_retriever(
    environ: Mapping[str, str] | None = None,
    *,
    initializer: Callable[[str], Any] | None = None,
    extractor: EntityRelationExtractor | None = None,
) -> GraphStudyRetriever:
    """Create the default offline GraphRAG wrapper over configured Hybrid RAG."""

    return GraphStudyRetriever(
        hybrid=create_hybrid_retriever(
            environ,
            initializer=initializer,
        ),
        extractor=extractor,
    )
