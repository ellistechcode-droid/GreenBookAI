import pandas as pd
from functools import lru_cache
import os
import requests
from dotenv import load_dotenv
load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

TRAVEL_LOCATIONS_FILE = "data/travel_locations.csv"


@lru_cache(maxsize=1)
def load_locations():
    """
    Loads the local travel locations inventory.

    This is the central source of location data for the application.
    Each row can serve as either an origin or a destination.
    """
    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)
    return df.to_dict(orient="records")


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

    Future versions can:
    - filter destinations
    - refresh stale dynamic fields
    - discover new locations
    - cache API results
    """
    return load_locations()


def refresh_dynamic_fields(location):
    """
    Placeholder for future dynamic data refresh.

    Future responsibilities:
    - Travel advisories
    - Current weather
    - Flight pricing
    - Hotel pricing
    - OpenTripMap enrichment
    """
    return location


def clear_location_cache():
    """
    Clears the cached location inventory.
    Useful after updating travel_locations.csv.
    """
    load_locations.cache_clear()

def discover_location(city_name):
    """
    Uses Geoapify to discover a location that is not already in the local dataset.
    """
    if not GEOAPIFY_API_KEY:
        return None

    url = "https://api.geoapify.com/v1/geocode/search"

    params = {
        "text": city_name,
        "format": "json",
        "limit": 1,
        "apiKey": GEOAPIFY_API_KEY
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        return None

    data = response.json()
    results = data.get("results", [])

    if not results:
        return None

    result = results[0]

    city = (
        result.get("city")
        or result.get("name")
        or city_name
    )

    country = result.get("country", "")
    region = result.get("continent", "")
    latitude = result.get("lat")
    longitude = result.get("lon")

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
        "source": "Geoapify"
    }

def get_or_discover_location(city_name):
    """
    First checks the local dataset. If missing, discovers the location using Geoapify
    and saves it for future use.
    """
    location = get_location_by_city(city_name)

    if location:
        location["source"] = "Local"
        return location

    discovered_location = discover_location(city_name)

    if discovered_location:
        return save_location(discovered_location)

    return None

def save_location(location):
    """
    Appends a newly discovered location to the travel locations CSV.
    Prevents duplicates by checking city name first.
    """
    existing_location = get_location_by_city(location["city"])

    if existing_location:
        return existing_location

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    new_row = {
        "city": location.get("city"),
        "country": location.get("country"),
        "region": location.get("region"),
        "trip_type": location.get("trip_type", "unknown"),
        "climate_tag": location.get("climate_tag", "unknown"),
        "estimated_nightly_cost": location.get("estimated_nightly_cost", 150),
        "safety_score": location.get("safety_score", 5),
        "attraction_score": location.get("attraction_score", 5),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude")
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)

    clear_location_cache()

    return location