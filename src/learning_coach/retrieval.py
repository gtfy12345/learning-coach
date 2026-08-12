import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_STUDY_MATERIAL_CHARS = 50_000
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_TOP_K = 3

_LATIN_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True)
class StudyChunk:
    """A stable in-memory chunk created from one pasted study material."""

    source_id: str
    text: str


@dataclass(frozen=True)
class RetrievedStudySource:
    """A relevant chunk with a deterministic lexical score."""

    source_id: str
    text: str
    score: float


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


def _relevance(query: str, text: str) -> float:
    query_terms = _lexical_terms(query)
    if not query_terms:
        return 0.0
    text_terms = _lexical_terms(text)
    overlap = sum(
        min(count, text_terms.get(term, 0)) for term, count in query_terms.items()
    )
    if overlap == 0:
        return 0.0
    return round(overlap / sum(query_terms.values()), 6)


def retrieve_study_sources(
    values: Mapping[str, Any],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedStudySource]:
    """Retrieve the most relevant positive-scoring in-memory chunks."""

    if top_k <= 0:
        raise ValueError("top_k 必须是正整数。")
    query = str(values.get("query", "")).strip()
    material = normalize_study_material(str(values.get("study_material", "")))
    if not query or not material:
        return []

    ranked = [
        RetrievedStudySource(
            source_id=chunk.source_id,
            text=chunk.text,
            score=_relevance(query, chunk.text),
        )
        for chunk in chunk_study_material(
            material,
            chunk_size=chunk_size,
            overlap=overlap,
        )
    ]
    positive = [source for source in ranked if source.score > 0]
    positive.sort(
        key=lambda source: (
            -source.score,
            int(source.source_id.rsplit("-", 1)[-1]),
        )
    )
    return positive[:top_k]
