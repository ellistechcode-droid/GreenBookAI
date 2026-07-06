import os
import requests
from dotenv import load_dotenv

load_dotenv()

print("SERPAPI:", os.getenv("SERPAPI_API_KEY"))

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")


def test_serpapi_connection():
    if not SERPAPI_API_KEY:
        return {
            "status": "failed",
            "message": "SERPAPI_API_KEY not found in .env"
        }

    url = "https://serpapi.com/search.json"

    params = {
        "engine": "google_flights",
        "departure_id": "BOS",
        "arrival_id": "MIA",
        "outbound_date": "2026-09-15",
        "return_date": "2026-09-20",
        "currency": "USD",
        "hl": "en",
        "api_key": SERPAPI_API_KEY
    }

    response = requests.get(url, params=params, timeout=15)

    return response.json().get("best_flights", [])

def get_flight_pricing(origin, destination):
    """
    Future: Replace with live flight API.
    Current: fallback estimate.
    """

    return {
        "total_price": None,
        "outbound_duration": None,
        "return_duration": None,
        "connection_count": None,
        "flight_practicality": "fallback",
        "source": "fallback"
    }


def get_lodging_pricing(destination, nights):
    nightly_cost = destination["estimated_nightly_cost"]
    lodging_total = nightly_cost * nights

    return {
        "properties_checked": 0,
        "min_nightly": nightly_cost,
        "max_nightly": nightly_cost,
        "average_nightly": nightly_cost,
        "lodging_total": lodging_total,
        "source": "csv_fallback"
    }


def get_trip_pricing(origin, destination, nights, fallback_flight_cost):
    flight = get_flight_pricing(origin, destination)
    lodging = get_lodging_pricing(destination, nights)

    flight_total = (
        flight["total_price"]
        if flight["total_price"] is not None
        else fallback_flight_cost
    )

    estimated_total_cost = flight_total + lodging["lodging_total"]

    return {
        "flight": flight,
        "lodging": lodging,
        "flight_total": flight_total,
        "estimated_total_cost": estimated_total_cost,
        "fallback_used": flight["source"] == "fallback"
    }