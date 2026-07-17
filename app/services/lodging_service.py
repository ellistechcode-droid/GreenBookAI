import os
from statistics import mean

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"


def _fallback_lodging_result(destination, nights, reason):
    """
    Returns CSV-based lodging pricing when live hotel data is unavailable.
    """
    nightly_cost = float(destination.get("estimated_nightly_cost", 150))
    lodging_total = nightly_cost * nights

    return {
        "properties_checked": 0,
        "min_nightly": nightly_cost,
        "max_nightly": nightly_cost,
        "average_nightly": nightly_cost,
        "lodging_total": lodging_total,
        "selected_property": None,
        "source": "csv_fallback",
        "reason": reason,
    }


def _extract_property_price(property_result):
    """
    Extracts usable nightly and total prices from one SerpAPI hotel result.
    """
    rate_per_night = property_result.get("rate_per_night", {})
    total_rate = property_result.get("total_rate", {})

    nightly = rate_per_night.get("extracted_lowest")
    total = total_rate.get("extracted_lowest")

    if not isinstance(nightly, (int, float)):
        return None

    if total is not None and not isinstance(total, (int, float)):
        total = None

    return {
        "name": property_result.get("name"),
        "type": property_result.get("type"),
        "nightly": float(nightly),
        "total": float(total) if total is not None else None,
        "rating": property_result.get("overall_rating"),
        "reviews": property_result.get("reviews"),
        "hotel_class": property_result.get("hotel_class"),
        "free_cancellation": property_result.get("free_cancellation"),
    }


def get_lodging_pricing(
    destination,
    nights,
    check_in_date,
    check_out_date,
    adults=2,
):
    """
    Retrieves live hotel pricing from SerpAPI Google Hotels.

    The lowest-priced valid property is used for the trip total while
    summary statistics are calculated across the returned properties.
    """
    if not SERPAPI_API_KEY:
        return _fallback_lodging_result(
            destination,
            nights,
            "SERPAPI_API_KEY is missing",
        )

    city = str(destination.get("city", "")).strip()
    country = str(destination.get("country", "")).strip()

    if not city:
        return _fallback_lodging_result(
            destination,
            nights,
            "Destination city is missing",
        )

    query = f"hotels in {city}"
    if country:
        query += f", {country}"

    params = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "sort_by": "3",
        "api_key": SERPAPI_API_KEY,
    }

    try:
        response = requests.get(
            SERPAPI_URL,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as error:
        return _fallback_lodging_result(
            destination,
            nights,
            f"SerpAPI hotel request failed: {error}",
        )
    except ValueError:
        return _fallback_lodging_result(
            destination,
            nights,
            "SerpAPI returned invalid hotel JSON",
        )

    if data.get("error"):
        return _fallback_lodging_result(
            destination,
            nights,
            f"SerpAPI hotel error: {data['error']}",
        )

    parsed_properties = []

    for property_result in data.get("properties", []):
        parsed = _extract_property_price(property_result)

        if parsed is not None:
            parsed_properties.append(parsed)

    if not parsed_properties:
        return _fallback_lodging_result(
            destination,
            nights,
            "No hotel properties with usable prices were returned",
        )

    def is_acceptable_property(item):
        name = str(item.get("name") or "").lower()
        property_type = str(item.get("type") or "").lower()
        rating = item.get("rating")
        reviews = item.get("reviews")

        is_hostel = "hostel" in name or "hostel" in property_type
        has_good_rating = isinstance(rating, (int, float)) and rating >= 3.5
        has_enough_reviews = isinstance(reviews, (int, float)) and reviews >= 20

        return not is_hostel and has_good_rating and has_enough_reviews

    acceptable_properties = [
        item for item in parsed_properties
        if is_acceptable_property(item)
    ]

    # Prefer a reasonably reviewed hotel. If none qualify, keep live pricing
    # working by falling back to the broader result set.
    selection_pool = acceptable_properties or parsed_properties

    selected_property = min(
        selection_pool,
        key=lambda item: item["total"]
        if item["total"] is not None
        else item["nightly"] * nights,
    )

    nightly_prices = [item["nightly"] for item in selection_pool]
    lodging_total = (
        selected_property["total"]
        if selected_property["total"] is not None
        else selected_property["nightly"] * nights
    )

    return {
        "properties_checked": len(parsed_properties),
        "acceptable_properties": len(acceptable_properties),
        "min_nightly": round(min(nightly_prices), 2),
        "max_nightly": round(max(nightly_prices), 2),
        "average_nightly": round(mean(nightly_prices), 2),
        "lodging_total": round(lodging_total, 2),
        "selected_property": selected_property,
        "source": "SerpAPI",
        "reason": None,
    }