from __future__ import annotations

import re
import hashlib
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from learning_coach.ingestion import StudyChunkRecord
from learning_coach.schemas import ConceptKind, ConceptNode, ConceptRelationType

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
