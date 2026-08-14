import hashlib
import math
import re
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

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
