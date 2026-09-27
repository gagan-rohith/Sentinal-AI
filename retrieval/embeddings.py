"""Embedding providers.

The retrieval code depends only on the EmbeddingProvider protocol. Adding a hosted
provider (OpenAI, Bedrock, Voyage) means implementing embed_documents/embed_query and
registering it in create_embedder; credentials come from environment variables.
"""

import hashlib
import math
import re
from collections import Counter
from itertools import pairwise
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic feature-hashing embedder.

    Not semantic: it captures lexical overlap of words and word pairs. Used in tests and
    CI where downloading a model is not wanted.
    """

    name = "hash"

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        tokens = _TOKEN.findall(text.lower())
        features = Counter(tokens + [f"{a}_{b}" for a, b in pairwise(tokens)])
        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Install the 'ml' extra or set "
                "EMBEDDING_PROVIDER=hash."
            ) from exc
        self.name = model_name
        self._model: Any = SentenceTransformer(model_name, device="cpu")
        dimensions = self._model.get_embedding_dimension()
        if dimensions is None:
            raise RuntimeError(f"model {model_name} does not report an embedding dimension")
        self.dimensions = int(dimensions)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=32, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_embedder(provider: str, model_name: str, dimensions: int = 384) -> EmbeddingProvider:
    if provider == "hash":
        return HashEmbedder(dimensions)
    if provider == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"unknown embedding provider '{provider}'")
