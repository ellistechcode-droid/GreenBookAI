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

# Deterministic subregion mapping should be checked before country
# classification because many dynamically discovered records already
# contain a correct subregion even when the broad region is missing
# or incorrectly classified.
SUBREGION_REGION_MAP = {
    "northern europe": "Europe",
    "southern europe": "Europe",
    "western europe": "Europe",
    "eastern europe": "Europe",

    "east asia": "Asia",
    "southeast asia": "Asia",
    "south asia": "Asia",
    "west asia": "Asia",
    "central asia": "Asia",

    "north africa": "Africa",
    "west africa": "Africa",
    "east africa": "Africa",
    "southern africa": "Africa",
    "central africa": "Africa",

    "northern america": "North America",
    "central america": "North America",
    "mexico": "North America",

    "northern south america": "South America",
    "eastern south america": "South America",
    "andean south america": "South America",
    "andean region": "South America",
    "southern cone": "South America",
    "brazil": "South America",

    "greater antilles": "Caribbean",
    "lucayan archipelago": "Caribbean",
    "southern caribbean": "Caribbean",

    "australia and new zealand": "Oceania",
    "melanesia": "Oceania",
    "micronesia": "Oceania",
    "polynesia": "Oceania",
}

# Deterministic country mapping is the most reliable and cheapest
# fallback after subregion mapping.
COUNTRY_REGION_MAP = {
    "albania": "Europe",
    "aruba": "Caribbean",
    "australia": "Oceania",
    "bahamas": "Caribbean",
    "belize": "North America",
    "benin": "Africa",
    "brazil": "South America",
    "cambodia": "Asia",
    "canada": "North America",
    "chile": "South America",
    "china": "Asia",
    "colombia": "South America",
    "costa rica": "North America",
    "croatia": "Europe",
    "cuba": "Caribbean",
    "cyprus": "Europe",
    "dominican republic": "Caribbean",
    "egypt": "Africa",
    "fiji": "Oceania",
    "france": "Europe",
    "ghana": "Africa",
    "greece": "Europe",
    "honduras": "North America",
    "iceland": "Europe",
    "india": "Asia",
    "indonesia": "Asia",
    "italy": "Europe",
    "jamaica": "Caribbean",
    "japan": "Asia",
    "kenya": "Africa",
    "liberia": "Africa",
    "madagascar": "Africa",
    "malaysia": "Asia",
    "maldives": "Asia",
    "mauritius": "Africa",
    "mexico": "North America",
    "montenegro": "Europe",
    "morocco": "Africa",
    "mozambique": "Africa",
    "namibia": "Africa",
    "new zealand": "Oceania",
    "panama": "North America",
    "peru": "South America",
    "philippines": "Asia",
    "portugal": "Europe",
    "puerto rico": "Caribbean",
    "samoa": "Oceania",
    "senegal": "Africa",
    "seychelles": "Africa",
    "sierra leone": "Africa",
    "south africa": "Africa",
    "south korea": "Asia",
    "spain": "Europe",
    "sri lanka": "Asia",
    "tanzania": "Africa",
    "thailand": "Asia",
    "the gambia": "Africa",
    "togo": "Africa",
    "tunisia": "Africa",
    "turkey": "Asia",
    "united kingdom": "Europe",
    "united states": "North America",
    "uruguay": "South America",
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


def _region_from_subregion(subregion):
    return SUBREGION_REGION_MAP.get(
        _clean_text(subregion).lower()
    )


def _region_from_country(country):
    return COUNTRY_REGION_MAP.get(
        _clean_text(country).lower()
    )


def _region_from_embeddings(location):
    """
    Uses semantic similarity only when deterministic mappings are unavailable.
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
    "subregion": _clean_text(location.get("subregion")),
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
    Resolves a region using:
    1. Deterministic subregion mapping
    2. Deterministic country mapping
    3. Existing valid region
    4. Jina embedding classification
    5. Gemini fallback

    Deterministic geographic evidence intentionally takes precedence over
    previously stored broad-region labels so inconsistent records can be
    corrected automatically.
    """
    mapped_subregion = _region_from_subregion(
        location.get("subregion")
    )

    if mapped_subregion:
        return mapped_subregion

    mapped_country = _region_from_country(
        location.get("country")
    )

    if mapped_country:
        return mapped_country

    existing = _normalize_region(location.get("region"))

    if existing:
        return existing

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


def repair_regions():
    """
    Repairs missing or inconsistent broad-region values in travel_locations.csv.

    Deterministic subregion and country mappings override an existing broad
    region when the stored value conflicts with known geography. Rows that
    cannot be resolved deterministically retain a valid existing region or
    fall back to the standard resolver.
    """
    if not TRAVEL_LOCATIONS_FILE.exists():
        return 0

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    if "region" not in df.columns:
        df["region"] = None

    updated = 0

    for index, row in df.iterrows():
        location = row.to_dict()

        deterministic_region = (
            _region_from_subregion(location.get("subregion"))
            or _region_from_country(location.get("country"))
        )

        current_region = _normalize_region(
            location.get("region")
        )

        if deterministic_region:
            if current_region != deterministic_region:
                df.at[index, "region"] = deterministic_region
                updated += 1
            continue

        if current_region:
            continue

        resolved_region = resolve_region(location)

        if resolved_region and resolved_region != "Unknown":
            df.at[index, "region"] = resolved_region
            updated += 1

    if updated:
        df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)

    return updated