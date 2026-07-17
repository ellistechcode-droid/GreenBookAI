import os
import re
from functools import lru_cache

import pandas as pd
import requests
from dotenv import load_dotenv

from app.services.region_service import resolve_region

load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

TRAVEL_LOCATIONS_FILE = "data/travel_locations.csv"
GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

# Candidate seeds let GreenBookAI expand its destination inventory automatically.
# The app geocodes only seeds that are not already in travel_locations.csv.
DESTINATION_DISCOVERY_SEEDS = {
    "beach": [
        "Nassau, Bahamas",
        "Punta Cana, Dominican Republic",
        "Montego Bay, Jamaica",
        "San Juan, Puerto Rico",
        "Aruba",
        "Tulum, Mexico",
        "Cabo San Lucas, Mexico",
        "Honolulu, Hawaii",
        "Maui, Hawaii",
        "Fort Lauderdale, Florida",
        "Clearwater, Florida",
        "Myrtle Beach, South Carolina",
        "Rio de Janeiro, Brazil",
        "Salvador, Brazil",
        "Lagos, Portugal",
        "Nice, France",
        "Split, Croatia",
        "Santorini, Greece",
        "Zanzibar City, Tanzania",
        "Cape Town, South Africa",
        "Bali, Indonesia",
        "Koh Samui, Thailand",
        "Da Nang, Vietnam",
        "Gold Coast, Australia",
    ],
    "city": [
        "New York City, New York",
        "Chicago, Illinois",
        "Toronto, Canada",
        "Montreal, Canada",
        "Mexico City, Mexico",
        "London, United Kingdom",
        "Paris, France",
        "Madrid, Spain",
        "Lisbon, Portugal",
        "Amsterdam, Netherlands",
        "Berlin, Germany",
        "Rome, Italy",
        "Prague, Czechia",
        "Istanbul, Turkey",
        "Dubai, United Arab Emirates",
        "Tokyo, Japan",
        "Seoul, South Korea",
        "Singapore",
        "Buenos Aires, Argentina",
        "Sao Paulo, Brazil",
    ],
    "culture": [
        "New Orleans, Louisiana",
        "Savannah, Georgia",
        "Charleston, South Carolina",
        "Quebec City, Canada",
        "Oaxaca, Mexico",
        "Havana, Cuba",
        "Cusco, Peru",
        "Cartagena, Colombia",
        "Seville, Spain",
        "Florence, Italy",
        "Athens, Greece",
        "Marrakesh, Morocco",
        "Cairo, Egypt",
        "Accra, Ghana",
        "Dakar, Senegal",
        "Kyoto, Japan",
        "Jaipur, India",
        "Hoi An, Vietnam",
    ],
    "nature": [
        "Banff, Canada",
        "Vancouver, Canada",
        "Anchorage, Alaska",
        "Denver, Colorado",
        "Sedona, Arizona",
        "Yellowstone National Park, Wyoming",
        "Reykjavik, Iceland",
        "Interlaken, Switzerland",
        "Innsbruck, Austria",
        "Bergen, Norway",
        "Azores, Portugal",
        "Madeira, Portugal",
        "San Jose, Costa Rica",
        "Quito, Ecuador",
        "Patagonia, Argentina",
        "Cape Town, South Africa",
        "Queenstown, New Zealand",
        "Cairns, Australia",
    ],
}


@lru_cache(maxsize=1)
def load_locations():
    """
    Loads and normalizes the local travel locations inventory.

    Pandas represents blank CSV cells as NaN, which cannot be returned
    through FastAPI's strict JSON encoder. Required numeric and text fields
    receive safe defaults, while optional fields become None.
    """
    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    defaults = {
        "city": "",
        "country": "",
        "region": "",
        "trip_type": "unknown",
        "climate_tag": "unknown",
        "estimated_nightly_cost": 150,
        "safety_score": 5,
        "attraction_score": 5,
    }

    for column, default_value in defaults.items():
        if column not in df.columns:
            df[column] = default_value
        else:
            df[column] = df[column].fillna(default_value)

    optional_columns = [
        "latitude",
        "longitude",
        "airport_code",
    ]

    for column in optional_columns:
        if column not in df.columns:
            df[column] = None

    # Convert every remaining pandas NaN value to Python None so the
    # recommendation response is always valid JSON.
    df = df.astype(object).where(pd.notna(df), None)

    return df.to_dict(orient="records")


def _clean_airport_code(value):
    """
    Returns a valid three-letter airport code or None.
    """
    if value is None or pd.isna(value):
        return None

    airport_code = str(value).strip().upper()

    if re.fullmatch(r"[A-Z]{3}", airport_code):
        return airport_code

    return None


def get_location_by_city(city_name):
    """
    Finds a single location by city name.
    """
    city_name = city_name.strip().lower()

    for location in load_locations():
        if location["city"].strip().lower() == city_name:
            return location

    return None


def get_candidate_locations():
    """
    Returns all candidate locations.
    """
    return load_locations()


def refresh_dynamic_fields(location):
    """
    Enriches a location with an airport code when one is missing.
    """
    if _clean_airport_code(location.get("airport_code")):
        return location

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    airport_code = discover_airport_code(latitude, longitude)

    if airport_code:
        update_location_airport_code(location["city"], airport_code)
        location["airport_code"] = airport_code

    return location


def clear_location_cache():
    """
    Clears the cached location inventory.
    Useful after updating travel_locations.csv.
    """
    load_locations.cache_clear()


def _extract_airport_code(feature):
    """
    Extracts an IATA-style code from a Geoapify airport feature.

    Geoapify place properties can contain source-specific airport tags,
    so several common locations are checked.
    """
    properties = feature.get("properties", {})
    datasource = properties.get("datasource", {})
    raw = datasource.get("raw", {}) if isinstance(datasource, dict) else {}

    candidates = [
        properties.get("iata"),
        properties.get("iata_code"),
        properties.get("airport_code"),
        raw.get("iata"),
        raw.get("iata_code"),
        raw.get("airport:iata"),
        raw.get("ref"),
    ]

    for candidate in candidates:
        airport_code = _clean_airport_code(candidate)

        if airport_code:
            return airport_code

    return None


def discover_airport_code(latitude, longitude, radius_meters=200000):
    """
    Finds the nearest usable airport code with Geoapify Places.

    Searches international airports first, then broadens to all airports.
    """
    if not GEOAPIFY_API_KEY or latitude is None or longitude is None:
        return None

    for categories in ("airport.international", "airport"):
        params = {
            "categories": categories,
            "filter": f"circle:{longitude},{latitude},{radius_meters}",
            "bias": f"proximity:{longitude},{latitude}",
            "limit": 20,
            "apiKey": GEOAPIFY_API_KEY,
        }

        try:
            response = requests.get(PLACES_URL, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue

        for feature in data.get("features", []):
            airport_code = _extract_airport_code(feature)

            if airport_code:
                return airport_code

    return None


def discover_location(city_name):
    """
    Uses Geoapify to discover a location that is not already in the local dataset.
    It also attempts to discover the nearest airport code.
    """
    if not GEOAPIFY_API_KEY:
        return None

    params = {
        "text": city_name,
        "format": "json",
        "limit": 1,
        "apiKey": GEOAPIFY_API_KEY,
    }

    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("results", [])

    if not results:
        return None

    result = results[0]

    city = result.get("city") or result.get("name") or city_name
    country = result.get("country", "")
    latitude = result.get("lat")
    longitude = result.get("lon")

    region = resolve_region({
        "city": city,
        "country": country,
        "region": result.get("continent", ""),
        "latitude": latitude,
        "longitude": longitude,
    })

    airport_code = discover_airport_code(latitude, longitude)

    return {
        "city": city,
        "country": country,
        "region": region,
        "trip_type": "unknown",
        "climate_tag": "unknown",
        "estimated_nightly_cost": 150,
        "safety_score": 5,
        "attraction_score": 5,
        "latitude": latitude,
        "longitude": longitude,
        "airport_code": airport_code,
        "source": "Geoapify",
    }


def get_or_discover_location(city_name):
    """
    Checks the local dataset first.

    Existing records that lack an airport code are enriched automatically.
    Missing cities are discovered and saved for future use.
    """
    location = get_location_by_city(city_name)

    if location:
        location = refresh_dynamic_fields(location)
        location["source"] = "Local"
        return location

    discovered_location = discover_location(city_name)

    if discovered_location:
        return save_location(discovered_location)

    return None


def update_location_airport_code(city_name, airport_code):
    """
    Saves a discovered airport code to an existing CSV row.
    """
    airport_code = _clean_airport_code(airport_code)

    if not airport_code:
        return False

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    if "airport_code" not in df.columns:
        df["airport_code"] = None

    city_mask = (
        df["city"].astype(str).str.strip().str.lower()
        == city_name.strip().lower()
    )

    if not city_mask.any():
        return False

    df.loc[city_mask, "airport_code"] = airport_code
    df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)
    clear_location_cache()

    return True


def save_location(location):
    """
    Appends a newly discovered location to the travel locations CSV.
    Prevents duplicates by checking city name first.
    """
    existing_location = get_location_by_city(location["city"])

    if existing_location:
        return refresh_dynamic_fields(existing_location)

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    if "airport_code" not in df.columns:
        df["airport_code"] = None

    airport_code = _clean_airport_code(location.get("airport_code"))

    if not airport_code:
        airport_code = discover_airport_code(
            location.get("latitude"),
            location.get("longitude"),
        )

    resolved_region = resolve_region(location)

    new_row = {
        "city": location.get("city"),
        "country": location.get("country"),
        "region": resolved_region,
        "trip_type": location.get("trip_type", "unknown"),
        "climate_tag": location.get("climate_tag", "unknown"),
        "estimated_nightly_cost": location.get("estimated_nightly_cost", 150),
        "safety_score": location.get("safety_score", 5),
        "attraction_score": location.get("attraction_score", 5),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "airport_code": airport_code,
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)

    clear_location_cache()

    saved_location = dict(location)
    saved_location["airport_code"] = airport_code

    return saved_location


def _detect_requested_trip_type(prompt):
    """
    Detects the strongest supported trip type in the user's prompt.
    """
    prompt_lower = prompt.lower()

    keyword_groups = {
        "beach": ["beach", "coast", "coastal", "ocean", "island", "tropical"],
        "nature": ["nature", "mountain", "hiking", "outdoor", "forest", "national park"],
        "culture": ["culture", "historic", "history", "museum", "food", "architecture"],
        "city": ["city", "urban", "nightlife", "shopping"],
    }

    for trip_type, keywords in keyword_groups.items():
        if any(keyword in prompt_lower for keyword in keywords):
            return trip_type

    return None


def _detect_climate_tag(prompt):
    """
    Detects a simple climate tag for newly discovered destinations.
    """
    prompt_lower = prompt.lower()

    if any(word in prompt_lower for word in ["warm", "hot", "tropical", "beach"]):
        return "warm"

    if any(word in prompt_lower for word in ["cold", "snow", "winter"]):
        return "cold"

    if any(word in prompt_lower for word in ["mild", "comfortable", "cool"]):
        return "mild"

    return "unknown"


def discover_destination_candidates(prompt, limit=5):
    """
    Automatically expands the destination inventory from prompt-relevant seeds.

    Only cities that are not already in travel_locations.csv are geocoded,
    enriched with an airport code, saved, and returned.
    """
    trip_type = _detect_requested_trip_type(prompt)

    if trip_type is None:
        return []

    climate_tag = _detect_climate_tag(prompt)
    existing_cities = {
        str(location.get("city", "")).strip().lower()
        for location in load_locations()
    }

    new_locations = []

    for seed in DESTINATION_DISCOVERY_SEEDS.get(trip_type, []):
        if len(new_locations) >= limit:
            break

        seed_city = seed.split(",")[0].strip().lower()

        if seed_city in existing_cities:
            continue

        discovered = discover_location(seed)

        if not discovered:
            continue

        discovered["trip_type"] = trip_type
        discovered["climate_tag"] = climate_tag

        saved = save_location(discovered)

        if saved:
            new_locations.append(saved)
            existing_cities.add(str(saved.get("city", "")).strip().lower())

    return new_locations