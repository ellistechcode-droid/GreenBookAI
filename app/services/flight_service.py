import os

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"


def _fallback_flight_result(reason):
    """
    Returns a consistent fallback response and explains why live pricing failed.
    """
    return {
        "total_price": None,
        "outbound_duration": None,
        "return_duration": None,
        "connection_count": None,
        "flight_practicality": "fallback",
        "source": "fallback",
        "reason": reason,
    }


def _get_airport_code(location):
    """
    Safely extracts and normalizes an airport code from a location dictionary.
    """
    if not isinstance(location, dict):
        return None

    airport_code = location.get("airport_code")

    if airport_code is None:
        return None

    airport_code = str(airport_code).strip().upper()

    if not airport_code or airport_code == "NAN":
        return None

    return airport_code


def _parse_flight_option(flight_option):
    """
    Converts one SerpAPI flight option into the format used by GreenBookAI.
    """
    flight_segments = flight_option.get("flights", [])

    if not flight_segments:
        return None

    price = flight_option.get("price")
    total_duration = flight_option.get("total_duration")
    connection_count = max(len(flight_segments) - 1, 0)

    if connection_count == 0:
        practicality = "direct"
    elif connection_count == 1:
        practicality = "one_stop"
    else:
        practicality = "multiple_stops"

    return {
        "total_price": price,
        "outbound_duration": total_duration,
        "return_duration": None,
        "connection_count": connection_count,
        "flight_practicality": practicality,
        "source": "SerpAPI",
        "reason": None,
    }


def get_flight_pricing(origin, destination, outbound_date, return_date):
    """
    Retrieves live round-trip flight pricing from SerpAPI.

    Dates must use YYYY-MM-DD format.
    """
    if not SERPAPI_API_KEY:
        return _fallback_flight_result("SERPAPI_API_KEY is missing")

    origin_code = _get_airport_code(origin)
    destination_code = _get_airport_code(destination)

    if not origin_code or not destination_code:
        return _fallback_flight_result(
            f"Airport code missing: origin={origin_code}, destination={destination_code}"
        )

    params = {
        "engine": "google_flights",
        "departure_id": origin_code,
        "arrival_id": destination_code,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "currency": "USD",
        "hl": "en",
        "type": "1",
        "api_key": SERPAPI_API_KEY,
    }

    try:
        response = requests.get(
            SERPAPI_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as error:
        return _fallback_flight_result(
            f"SerpAPI request failed: {error}"
        )
    except ValueError:
        return _fallback_flight_result(
            "SerpAPI returned invalid JSON"
        )

    if data.get("error"):
        return _fallback_flight_result(
            f"SerpAPI error: {data['error']}"
        )

    flight_options = data.get("best_flights", []) or data.get("other_flights", [])

    if not flight_options:
        return _fallback_flight_result(
            "No flight options were returned"
        )

    valid_options = [
        option
        for option in flight_options
        if isinstance(option.get("price"), (int, float))
    ]

    if not valid_options:
        return _fallback_flight_result(
            "Flight options did not contain usable prices"
        )

    cheapest_option = min(
        valid_options,
        key=lambda option: option["price"],
    )

    parsed_flight = _parse_flight_option(cheapest_option)

    if parsed_flight is None:
        return _fallback_flight_result(
            "The selected flight could not be parsed"
        )

    return parsed_flight