import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google import genai

from app.services.embedding_service import (
    build_destination_text,
    cosine_similarity,
    get_destination_embeddings,
)

load_dotenv()

TRAVEL_LOCATIONS_FILE = Path("data/travel_locations.csv")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

VALID_REGIONS = [
    "Africa",
    "Asia",
    "Caribbean",
    "Europe",
    "North America",
    "Oceania",
    "South America",
]

# Deterministic country mapping is the most reliable and cheapest first step.
COUNTRY_REGION_MAP = {
    "aruba": "Caribbean",
    "australia": "Oceania",
    "bahamas": "Caribbean",
    "brazil": "South America",
    "canada": "North America",
    "colombia": "South America",
    "dominican republic": "Caribbean",
    "france": "Europe",
    "greece": "Europe",
    "indonesia": "Asia",
    "italy": "Europe",
    "jamaica": "Caribbean",
    "japan": "Asia",
    "mexico": "North America",
    "morocco": "Africa",
    "philippines": "Asia",
    "portugal": "Europe",
    "puerto rico": "Caribbean",
    "south africa": "Africa",
    "spain": "Europe",
    "thailand": "Asia",
    "united kingdom": "Europe",
    "united states": "North America",
    "usa": "North America",
    "vietnam": "Asia",
}

REGION_DESCRIPTORS = [
    {
        "city": region,
        "country": "",
        "region": region,
        "trip_type": "region classification",
        "climate_tag": "varied",
        "safety_score": 5,
        "attraction_score": 5,
    }
    for region in VALID_REGIONS
]


def _clean_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_region(value):
    value = _clean_text(value)

    for region in VALID_REGIONS:
        if value.lower() == region.lower():
            return region

    return None


def _region_from_country(country):
    return COUNTRY_REGION_MAP.get(_clean_text(country).lower())


def _region_from_embeddings(location):
    """
    Uses semantic similarity only when a country mapping is unavailable.
    """
    try:
        vectors = get_destination_embeddings(
            [location, *REGION_DESCRIPTORS]
        )
    except Exception:
        return None, 0.0

    location_vector = vectors[0]
    region_vectors = vectors[1:]

    similarities = [
        cosine_similarity(location_vector, vector)
        for vector in region_vectors
    ]

    if not similarities:
        return None, 0.0

    best_index = max(
        range(len(similarities)),
        key=lambda index: similarities[index],
    )

    return VALID_REGIONS[best_index], similarities[best_index]


def _region_from_llm(location):
    """
    Gemini is the final fallback and may only return a valid region label.
    """
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
Classify this destination into exactly one region:
{", ".join(VALID_REGIONS)}

Destination:
{json.dumps({
    "city": _clean_text(location.get("city")),
    "country": _clean_text(location.get("country")),
    "latitude": location.get("latitude"),
    "longitude": location.get("longitude"),
})}

Return only the region name and nothing else.
"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return _normalize_region(getattr(response, "text", None))
    except Exception:
        return None


def resolve_region(location):
    """
    Resolves a missing region using:
    1. Existing valid value
    2. Country mapping
    3. Jina embedding classification
    4. Gemini fallback
    """
    existing = _normalize_region(location.get("region"))

    if existing:
        return existing

    mapped = _region_from_country(location.get("country"))

    if mapped:
        return mapped

    embedded_region, similarity = _region_from_embeddings(location)

    # Embeddings are a classifier fallback, not the primary source of truth.
    if embedded_region and similarity >= 0.25:
        return embedded_region

    return _region_from_llm(location) or "Unknown"


def backfill_missing_regions():
    """
    Fills blank/unknown region cells in travel_locations.csv.

    Returns the number of rows updated.
    """
    if not TRAVEL_LOCATIONS_FILE.exists():
        return 0

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    if "region" not in df.columns:
        df["region"] = None

    updated = 0

    for index, row in df.iterrows():
        current_region = _normalize_region(row.get("region"))

        if current_region:
            continue

        location = row.to_dict()
        resolved_region = resolve_region(location)

        if resolved_region and resolved_region != "Unknown":
            df.at[index, "region"] = resolved_region
            updated += 1

    if updated:
        df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)

    return updated