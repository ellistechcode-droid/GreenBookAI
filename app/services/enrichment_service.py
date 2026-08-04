import os
from collections import Counter
from typing import Any

import requests
from dotenv import load_dotenv

from app.services.llm_service import classify_destination_metadata

load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
PLACES_URL = "https://api.geoapify.com/v2/places"

# Three broad searches instead of seven. This substantially reduces latency
# and Geoapify usage while still providing useful classification evidence.
POI_SEARCH_CATEGORIES = [
    "tourism",
    "natural",
    "beach",
]

ALLOWED_TRIP_TYPES = {
    "adventure",
    "art",
    "beach",
    "city",
    "culture",
    "family",
    "food",
    "history",
    "nature",
    "nightlife",
    "resort",
    "romance",
    "technology",
    "water_sports",
    "wellness",
}

ALLOWED_CLIMATE_TAGS = {"warm", "mild", "cold"}


def _clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _normalize_label(value: Any) -> str:
    return _clean_text(value).lower().replace(" ", "_").replace("-", "_")


def _fallback_climate(latitude: Any) -> str:
    """Returns a broad static climate tag when Gemini cannot classify one."""
    try:
        absolute_latitude = abs(float(latitude))
    except (TypeError, ValueError):
        return "mild"

    if absolute_latitude <= 23.5:
        return "warm"
    if absolute_latitude >= 55:
        return "cold"
    return "mild"


def collect_destination_categories(
    latitude: Any,
    longitude: Any,
    radius_meters: int = 25000,
    limit_per_category: int = 12,
) -> dict[str, Any]:
    """Collects nearby Geoapify categories with bounded request times."""
    if not GEOAPIFY_API_KEY or latitude is None or longitude is None:
        return {
            "category_counts": {},
            "sample_places": [],
            "poi_count": 0,
            "source": "Geoapify",
        }

    category_counts: Counter[str] = Counter()
    sample_places: list[str] = []
    seen_place_ids: set[str] = set()

    for category in POI_SEARCH_CATEGORIES:
        params = {
            "categories": category,
            "filter": f"circle:{longitude},{latitude},{radius_meters}",
            "bias": f"proximity:{longitude},{latitude}",
            "limit": limit_per_category,
            "apiKey": GEOAPIFY_API_KEY,
        }

        try:
            response = requests.get(
                PLACES_URL,
                params=params,
                timeout=(3, 8),
            )
            response.raise_for_status()
            features = response.json().get("features", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"Geoapify category lookup failed for {category}: {exc}")
            continue

        for feature in features:
            properties = feature.get("properties", {})
            place_id = str(
                properties.get("place_id")
                or properties.get("osm_id")
                or properties.get("formatted")
                or ""
            )

            if place_id and place_id in seen_place_ids:
                continue
            if place_id:
                seen_place_ids.add(place_id)

            categories = properties.get("categories", [])
            if isinstance(categories, list):
                for discovered_category in categories:
                    normalized = _clean_text(discovered_category).lower()
                    if normalized:
                        category_counts[normalized] += 1

            place_name = (
                properties.get("name")
                or properties.get("address_line1")
                or properties.get("formatted")
            )
            if place_name and len(sample_places) < 12:
                sample_places.append(str(place_name))

    return {
        "category_counts": dict(category_counts.most_common(40)),
        "sample_places": sample_places,
        "poi_count": len(seen_place_ids),
        "source": "Geoapify",
    }


def _fallback_trip_types(category_counts: dict[str, int]) -> list[str]:
    """Maps Geoapify evidence to three safe labels if Gemini is unavailable."""
    scores = Counter()

    for category, count in category_counts.items():
        category = category.lower()

        if "beach" in category:
            scores["beach"] += count
            scores["water_sports"] += max(1, count // 2)
        if any(token in category for token in ("natural", "forest", "mountain", "park")):
            scores["nature"] += count
        if any(token in category for token in ("museum", "heritage", "monument", "religion")):
            scores["culture"] += count
            scores["history"] += max(1, count // 2)
        if any(token in category for token in ("catering", "restaurant", "cafe", "food")):
            scores["food"] += count
        if any(token in category for token in ("nightclub", "bar", "entertainment")):
            scores["nightlife"] += count
        if any(token in category for token in ("sport", "hiking", "climbing", "surf")):
            scores["adventure"] += count
        if any(token in category for token in ("spa", "wellness")):
            scores["wellness"] += count
        if any(token in category for token in ("shopping", "commercial")):
            scores["city"] += count

    selected = [label for label, _ in scores.most_common(3)]
    defaults = ["city", "culture", "nature"]

    for label in defaults:
        if len(selected) >= 3:
            break
        if label not in selected:
            selected.append(label)

    return selected[:3]


def _validated_trip_types(values: Any, fallback: list[str]) -> list[str]:
    if not isinstance(values, list):
        return fallback

    cleaned: list[str] = []
    for value in values:
        label = _normalize_label(value)
        if label in ALLOWED_TRIP_TYPES and label not in cleaned:
            cleaned.append(label)

    for label in fallback:
        if len(cleaned) >= 3:
            break
        if label not in cleaned:
            cleaned.append(label)

    return cleaned[:3]


def enrich_location(location: dict[str, Any]) -> dict[str, Any]:
    """Completes semantic destination fields before CSV persistence."""
    enriched = dict(location)

    city = _clean_text(enriched.get("city"))
    country = _clean_text(enriched.get("country"))
    latitude = enriched.get("latitude")
    longitude = enriched.get("longitude")

    evidence = collect_destination_categories(latitude, longitude)
    fallback_types = _fallback_trip_types(evidence["category_counts"])

    classification = classify_destination_metadata(
        city=city,
        country=country,
        region=_clean_text(enriched.get("region")),
        subregion=_clean_text(enriched.get("subregion")),
        latitude=latitude,
        longitude=longitude,
        category_counts=evidence["category_counts"],
        sample_places=evidence["sample_places"],
    )

    trip_types = _validated_trip_types(
        classification.get("trip_types") if classification else None,
        fallback_types,
    )

    climate_tag = _normalize_label(
        classification.get("climate_tag") if classification else ""
    )
    if climate_tag not in ALLOWED_CLIMATE_TAGS:
        climate_tag = _fallback_climate(latitude)

    description = _clean_text(
        classification.get("destination_description") if classification else ""
    )
    if not description:
        readable_types = ", ".join(
            label.replace("_", " ") for label in trip_types
        )
        description = (
            f"{city} in {country} offers travel experiences centered on "
            f"{readable_types}."
        )

    enriched.update({
        "trip_type_1": trip_types[0],
        "trip_type_2": trip_types[1],
        "trip_type_3": trip_types[2],
        "climate_tag": climate_tag,
        "destination_description": description,
        "enrichment_source": (
            "Geoapify+Gemini" if classification else "Geoapify fallback"
        ),
        "enrichment_evidence": evidence,
    })

    return enriched