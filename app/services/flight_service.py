import os
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"


def _get_airport_code(location):
    if not isinstance(location, dict):
        return None

    airport_code = location.get("airport_code")
    if airport_code is None:
        return None

    airport_code = str(airport_code).strip().upper()
    if not airport_code or airport_code == "NAN":
        return None

    return airport_code


def _build_flight_search_url(origin_code, destination_code, outbound_date, return_date):
    """
    Builds a transparent Google Flights search link for the requested itinerary.

    This is a search link, not a claim that the quoted SerpAPI fare will remain
    available after the user opens Google Flights.
    """
    query = (
        f"Flights from {origin_code} to {destination_code} "
        f"on {outbound_date} returning {return_date}"
    )
    return "https://www.google.com/travel/flights?" + urlencode(
        {"hl": "en", "q": query}
    )


def _fallback_flight_result(
    reason,
    origin_code=None,
    destination_code=None,
    outbound_date=None,
    return_date=None,
):
    # No usable live itinerary was returned, so do not provide a flight link.
    # A generic Google Flights search URL can misleadingly look like a verified
    # itinerary even when Google Flights returned no result for the request.
    search_url = None

    return {
        "total_price": None,
        "outbound_duration": None,
        "return_duration": None,
        "connection_count": None,
        "return_connection_count": None,
        "outbound_layover_duration": None,
        "return_layover_duration": None,
        "outbound_layover_airports": [],
        "return_layover_airports": [],
        "flight_practicality": "fallback",
        "airlines": [],
        "outbound_airlines": [],
        "return_airlines": [],
        "origin_airport": origin_code,
        "destination_airport": destination_code,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "search_url": search_url,
        "source": "fallback",
        "reason": reason,
    }


def _unique_airlines(segments):
    airlines = []
    for segment in segments or []:
        airline = str(segment.get("airline") or "").strip()
        if airline and airline not in airlines:
            airlines.append(airline)
    return airlines


def _parse_leg(option):
    segments = option.get("flights") or []
    if not segments:
        return None

    layovers = option.get("layovers") or []
    layover_durations = [
        item.get("duration")
        for item in layovers
        if isinstance(item.get("duration"), (int, float))
    ]
    layover_airports = [
        str(item.get("id")).strip()
        for item in layovers
        if item.get("id")
    ]

    # A direct itinerary has a known zero-minute layover. For a connecting
    # itinerary, return None unless SerpAPI supplied all usable layover data.
    connections = max(len(segments) - 1, 0)
    if connections == 0:
        layover_duration = 0
    elif len(layover_durations) == connections:
        layover_duration = sum(layover_durations)
    else:
        layover_duration = None

    return {
        "segments": segments,
        "duration": option.get("total_duration"),
        "connections": connections,
        "layover_duration": layover_duration,
        "layover_airports": layover_airports,
        "airlines": _unique_airlines(segments),
        "departure_token": option.get("departure_token"),
        "booking_token": option.get("booking_token"),
        "price": option.get("price"),
    }


def _request(params):
    response = requests.get(
        SERPAPI_URL,
        params=params,
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def get_flight_pricing(origin, destination, outbound_date, return_date):
    """
    Retrieves a round-trip itinerary from SerpAPI Google Flights.

    Round trips require a second SerpAPI request with the selected outbound
    option's departure_token to retrieve the return leg.
    """
    origin_code = _get_airport_code(origin)
    destination_code = _get_airport_code(destination)

    if not SERPAPI_API_KEY:
        return _fallback_flight_result(
            "SERPAPI_API_KEY is missing",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    if not origin_code or not destination_code:
        return _fallback_flight_result(
            f"Airport code missing: origin={origin_code}, destination={destination_code}",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    base_params = {
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
        outbound_data = _request(base_params)
    except requests.RequestException as error:
        return _fallback_flight_result(
            f"SerpAPI request failed: {error}",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )
    except ValueError:
        return _fallback_flight_result(
            "SerpAPI returned invalid JSON",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    if outbound_data.get("error"):
        return _fallback_flight_result(
            f"SerpAPI error: {outbound_data['error']}",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    outbound_options = (
        outbound_data.get("best_flights", [])
        or outbound_data.get("other_flights", [])
    )
    valid_outbound = [
        option for option in outbound_options
        if isinstance(option.get("price"), (int, float))
        and option.get("flights")
    ]

    if not valid_outbound:
        return _fallback_flight_result(
            "No outbound flight options with usable pricing were returned",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    selected_outbound = min(valid_outbound, key=lambda item: item["price"])
    outbound_leg = _parse_leg(selected_outbound)

    if not outbound_leg:
        return _fallback_flight_result(
            "The selected outbound flight could not be parsed",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    departure_token = outbound_leg.get("departure_token")
    if not departure_token:
        return _fallback_flight_result(
            "SerpAPI did not provide a departure token for the return-flight search",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    return_params = dict(base_params)
    return_params["departure_token"] = departure_token

    try:
        return_data = _request(return_params)
    except requests.RequestException as error:
        return _fallback_flight_result(
            f"SerpAPI return-flight request failed: {error}",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )
    except ValueError:
        return _fallback_flight_result(
            "SerpAPI returned invalid JSON for return flights",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    if return_data.get("error"):
        return _fallback_flight_result(
            f"SerpAPI return-flight error: {return_data['error']}",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    return_options = (
        return_data.get("best_flights", [])
        or return_data.get("other_flights", [])
    )
    valid_returns = [
        option for option in return_options
        if option.get("flights")
    ]

    if not valid_returns:
        return _fallback_flight_result(
            "No return flight options were returned",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    # Prefer the lowest numeric total when available. If return options do not
    # expose a price, retain SerpAPI's first ranked return option.
    priced_returns = [
        option for option in valid_returns
        if isinstance(option.get("price"), (int, float))
    ]
    selected_return = (
        min(priced_returns, key=lambda item: item["price"])
        if priced_returns
        else valid_returns[0]
    )
    return_leg = _parse_leg(selected_return)

    if not return_leg:
        return _fallback_flight_result(
            "The selected return flight could not be parsed",
            origin_code,
            destination_code,
            outbound_date,
            return_date,
        )

    total_price = (
        return_leg.get("price")
        if isinstance(return_leg.get("price"), (int, float))
        else outbound_leg.get("price")
    )

    airlines = []
    for airline in outbound_leg["airlines"] + return_leg["airlines"]:
        if airline not in airlines:
            airlines.append(airline)

    max_connections = max(
        outbound_leg["connections"],
        return_leg["connections"],
    )
    if max_connections == 0:
        practicality = "direct"
    elif max_connections == 1:
        practicality = "one_stop"
    else:
        practicality = "multiple_stops"

    search_url = (
        (return_data.get("search_metadata") or {}).get("google_flights_url")
        or (outbound_data.get("search_metadata") or {}).get("google_flights_url")
    )

    return {
        "total_price": total_price,
        "outbound_duration": outbound_leg["duration"],
        "return_duration": return_leg["duration"],
        "connection_count": outbound_leg["connections"],
        "return_connection_count": return_leg["connections"],
        "outbound_layover_duration": outbound_leg["layover_duration"],
        "return_layover_duration": return_leg["layover_duration"],
        "outbound_layover_airports": outbound_leg["layover_airports"],
        "return_layover_airports": return_leg["layover_airports"],
        "flight_practicality": practicality,
        "airlines": airlines,
        "outbound_airlines": outbound_leg["airlines"],
        "return_airlines": return_leg["airlines"],
        "origin_airport": origin_code,
        "destination_airport": destination_code,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "search_url": search_url,
        "source": "SerpAPI",
        "reason": None,
    }