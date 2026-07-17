import hashlib
import json
import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

JINA_API_KEY = os.getenv("JINA_API_KEY")
JINA_EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"
JINA_EMBEDDING_MODEL = "jina-embeddings-v3"

CACHE_FILE = Path("data/destination_embeddings.json")


def build_destination_text(destination):
    """
    Converts one destination record into richer text for semantic retrieval.
    """
    city = destination.get("city", "")
    country = destination.get("country", "")
    region = destination.get("region", "")
    trip_type = destination.get("trip_type", "unknown")
    climate_tag = destination.get("climate_tag", "unknown")
    safety_score = destination.get("safety_score", 5)
    attraction_score = destination.get("attraction_score", 5)

    return (
        f"{city}, {country}. "
        f"Region: {region or 'unknown'}. "
        f"Travel style: {trip_type}. "
        f"Climate: {climate_tag}. "
        f"Safety score: {safety_score} out of 10. "
        f"Attraction score: {attraction_score} out of 10. "
        f"Suitable for travelers interested in {trip_type} experiences, "
        f"local culture, food, sightseeing, neighborhoods, and regional activities."
    )


def _text_cache_key(text):
    """
    Produces a stable key that changes whenever the destination text changes.
    """
    raw = f"{JINA_EMBEDDING_MODEL}:{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_cache():
    if not CACHE_FILE.exists():
        return {}

    try:
        with CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with CACHE_FILE.open("w", encoding="utf-8") as file:
        json.dump(cache, file)


def _request_embeddings(texts, task):
    """
    Sends one batched embedding request to Jina AI.
    """
    if not JINA_API_KEY:
        raise RuntimeError("JINA_API_KEY is missing from .env")

    if not texts:
        return []

    headers = {
        "Authorization": f"Bearer {JINA_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": JINA_EMBEDDING_MODEL,
        "task": task,
        "input": texts,
    }

    response = requests.post(
        JINA_EMBEDDINGS_URL,
        headers=headers,
        json=payload,
        timeout=45,
    )
    response.raise_for_status()

    data = response.json().get("data", [])
    ordered = sorted(data, key=lambda item: item.get("index", 0))

    embeddings = [item.get("embedding") for item in ordered]

    if len(embeddings) != len(texts) or any(vector is None for vector in embeddings):
        raise RuntimeError("Jina returned an incomplete embedding response")

    return embeddings


def get_query_embedding(prompt):
    """
    Embeds the user's request using Jina's retrieval-query task.
    """
    return _request_embeddings([prompt], task="retrieval.query")[0]


def get_destination_embeddings(destinations):
    """
    Returns destination vectors while caching them on disk.

    Only new or changed destination descriptions are sent to Jina.
    """
    cache = _load_cache()
    vectors = [None] * len(destinations)
    missing_texts = []
    missing_positions = []
    missing_keys = []

    for position, destination in enumerate(destinations):
        text = build_destination_text(destination)
        cache_key = _text_cache_key(text)
        cached_vector = cache.get(cache_key)

        if isinstance(cached_vector, list) and cached_vector:
            vectors[position] = cached_vector
        else:
            missing_texts.append(text)
            missing_positions.append(position)
            missing_keys.append(cache_key)

    if missing_texts:
        new_vectors = _request_embeddings(
            missing_texts,
            task="retrieval.passage",
        )

        for position, cache_key, vector in zip(
            missing_positions,
            missing_keys,
            new_vectors,
        ):
            vectors[position] = vector
            cache[cache_key] = vector

        _save_cache(cache)

    return vectors


def cosine_similarity(vector_a, vector_b):
    """
    Calculates cosine similarity without requiring NumPy.
    """
    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
    magnitude_a = math.sqrt(sum(a * a for a in vector_a))
    magnitude_b = math.sqrt(sum(b * b for b in vector_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def rank_destinations_by_embedding(prompt, destinations):
    """
    Returns destinations ordered by semantic similarity to the user prompt.

    Falls back safely when Jina is unavailable so recommendations still work.
    """
    try:
        query_vector = get_query_embedding(prompt)
        destination_vectors = get_destination_embeddings(destinations)
    except (RuntimeError, requests.RequestException, ValueError):
        return [
            {
                "destination": destination,
                "embedding_similarity": 0.0,
                "embedding_available": False,
            }
            for destination in destinations
        ]

    ranked = []

    for destination, vector in zip(destinations, destination_vectors):
        similarity = cosine_similarity(query_vector, vector)

        ranked.append({
            "destination": destination,
            "embedding_similarity": similarity,
            "embedding_available": True,
        })

    return sorted(
        ranked,
        key=lambda item: item["embedding_similarity"],
        reverse=True,
    )