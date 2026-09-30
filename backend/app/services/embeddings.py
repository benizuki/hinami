from __future__ import annotations

import logging
import math
import os

from .gemini import gemini_client, gemini_configured

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
# 「月次集計」と「月次の集計作業」を同じ業務とみなす距離。実データで調整する前提の初期値。
# 埋め込みモデルを変えると類似度の分布も変わるため、変えたらこの値も見直す。
WORK_PROFILE_SIMILARITY_THRESHOLD = 0.80


def embedding_model_name() -> str:
    return os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """業務名の名寄せ用に埋め込みを取得する。

    埋め込みは名寄せの精度を上げる補助であり、必須ではない。取得できない場合は
    空リストを返し、呼び出し側は正規化した文字列一致だけで動作を続ける。
    """
    targets = [text.strip() for text in texts if text.strip()]
    if not targets:
        return []
    if not gemini_configured():
        return []
    try:
        response = gemini_client().models.embed_content(model=embedding_model_name(), contents=targets)
    except Exception:
        logger.warning("Embedding request failed; work profiles fall back to text matching", exc_info=True)
        return []

    vectors: list[list[float]] = []
    for embedding in getattr(response, "embeddings", None) or []:
        values = getattr(embedding, "values", None)
        if not values:
            return []
        vectors.append([float(value) for value in values])
    return vectors if len(vectors) == len(targets) else []


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def most_similar_index(
    target: list[float],
    candidates: list[list[float]],
    threshold: float = WORK_PROFILE_SIMILARITY_THRESHOLD,
) -> int | None:
    best_index: int | None = None
    best_score = threshold
    for index, candidate in enumerate(candidates):
        score = cosine_similarity(target, candidate)
        if score >= best_score:
            best_index = index
            best_score = score
    return best_index
