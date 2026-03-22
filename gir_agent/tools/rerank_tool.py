import json
from typing import Any

from litellm import completion

from gir_agent.config import LLM_MODEL, LLM_TEMPERATURE


def _normalize_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for index, candidate in enumerate(candidates, start=1):
        if isinstance(candidate, dict):
            item = dict(candidate)
        else:
            item = {"value": str(candidate)}
        item.setdefault("candidate_id", str(index))
        normalized.append(item)
    return normalized


def rerank_candidates(
    original_query: str,
    candidates: list[Any],
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Rerank geographic candidates against the original user query with an LLM.

    Args:
        original_query: The user's original query.
        candidates: Candidate locations or nearby place records to rerank.
        top_k: Maximum number of candidates to return.
    """
    normalized_candidates = _normalize_candidates(candidates)
    if not original_query.strip():
        return {"error": "original_query must not be empty.", "candidates": []}
    if not normalized_candidates:
        return {"error": "No candidates provided.", "candidates": []}

    prompt = (
        "You are reranking geographic candidates for query matching.\n"
        "Your job is to score how well each candidate matches the user's original query.\n"
        "Consider entity name similarity, place type, coordinates context, nearby place evidence, and any temporal hints in the query.\n"
        "Return strict JSON with this shape only:\n"
        '{'
        '"ranked_candidates": ['
        '{"candidate_id": "string", "score": 0-100, "reason": "short explanation"}'
        "]"
        "}\n"
        "Do not include markdown fences or extra text."
    )

    response = completion(
        model=LLM_MODEL,
        temperature=float(LLM_TEMPERATURE),
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_query": original_query,
                        "top_k": max(1, int(top_k)),
                        "candidates": normalized_candidates,
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    ranked = payload.get("ranked_candidates")
    if not isinstance(ranked, list):
        return {"error": "LLM response did not include ranked_candidates.", "candidates": []}

    candidate_by_id = {
        candidate["candidate_id"]: candidate for candidate in normalized_candidates
    }
    merged = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id", "")).strip()
        if candidate_id not in candidate_by_id:
            continue
        merged.append(
            {
                **candidate_by_id[candidate_id],
                "score": item.get("score"),
                "reason": item.get("reason", ""),
            }
        )

    merged.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return {
        "original_query": original_query,
        "count": len(merged[: max(1, int(top_k))]),
        "candidates": merged[: max(1, int(top_k))],
    }
