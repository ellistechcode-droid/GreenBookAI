import os
import re
from statistics import mean
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"


def _fallback_lodging_result(destination, nights, reason, check_in_date=None, check_out_date=None):
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
        "quality_property": None,
        "hotel_budget_available": None,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "nights": nights,
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
        "link": property_result.get("link"),
        "property_token": property_result.get("property_token"),
        "serpapi_property_details_link": property_result.get(
            "serpapi_property_details_link"
        ),
    }


def _normalize_name_tokens(value):
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    stopwords = {
        "hotel", "hotels", "motel", "inn", "resort", "the", "by",
        "at", "and", "of", "a", "an",
    }
    return [token for token in tokens if token not in stopwords]


def _link_matches_property_name(name, link):
    """
    Conservatively checks whether a hotel website URL appears to identify the
    specific property. Generic brand/homepage links fail this test.
    """
    if not name or not link:
        return False

    normalized_link = str(link).lower()
    tokens = _normalize_name_tokens(name)

    if not tokens:
        return False

    # Require at least one meaningful property-name token to appear in the URL.
    # This rejects generic links such as atminehospitality.com for "The Victoria
    # Hotel", while accepting property-specific domains such as
    # caribbeanhousekw.com.
    return any(token in normalized_link for token in tokens)


def _google_hotels_search_link(
    property_name,
    city,
    country,
    check_in_date,
    check_out_date,
):
    """Builds a consumer-facing Google Hotels search for one exact property."""
    if not property_name or not city:
        return None

    destination = ", ".join(
        value for value in (city, country) if value
    )
    query = f"{property_name}, {destination}"

    return "https://www.google.com/travel/hotels?" + urlencode({
        "q": query,
        "hl": "en",
        "checkin": check_in_date,
        "checkout": check_out_date,
    })


def _preferred_property_link(
    property_data,
    city=None,
    country=None,
    check_in_date=None,
    check_out_date=None,
):
    """
    Uses a property-specific direct website when available; otherwise uses a
    targeted Google Hotels search. Generic hospitality-company homepages and
    SerpAPI JSON endpoints are never displayed.
    """
    if not isinstance(property_data, dict):
        return None

    direct_link = property_data.get("link")
    if _link_matches_property_name(property_data.get("name"), direct_link):
        return direct_link

    return _google_hotels_search_link(
        property_name=property_data.get("name"),
        city=city,
        country=country,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
    )


def _property_total(item, nights):
    total = item.get("total")
    if isinstance(total, (int, float)):
        return float(total)

    nightly = item.get("nightly")
    if isinstance(nightly, (int, float)):
        return float(nightly) * nights

    return float("inf")


def _hotel_class_stars(value):
    """Extracts a numeric star count from values such as '4-star hotel'."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*-?\s*star", str(value or ""), re.I)
    return float(match.group(1)) if match else 0.0


def _quality_sort_key(item, nights):
    """
    Ranks hotel quality by rating, class, review volume, then lower total cost.
    """
    rating = item.get("rating")
    reviews = item.get("reviews")

    return (
        float(rating) if isinstance(rating, (int, float)) else 0.0,
        _hotel_class_stars(item.get("hotel_class")),
        float(reviews) if isinstance(reviews, (int, float)) else 0.0,
        -_property_total(item, nights),
    )


def _request_hotel_properties(
    query,
    check_in_date,
    check_out_date,
    adults,
    sort_by=None,
):
    params = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": SERPAPI_API_KEY,
    }

    if sort_by is not None:
        params["sort_by"] = sort_by

    response = requests.get(
        SERPAPI_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("error"):
        raise RuntimeError(str(data["error"]))

    return data.get("properties", [])


def _is_resort_property(item):
    text = " ".join([
        str(item.get("name") or ""),
        str(item.get("type") or ""),
        str(item.get("hotel_class") or ""),
    ]).lower()

    return "resort" in text


def _deduplicate_properties(properties):
    unique = {}

    for item in properties:
        name = str(item.get("name") or "").strip().lower()
        token = str(item.get("property_token") or "").strip()
        key = token or name

        if key and key not in unique:
            unique[key] = item

    return list(unique.values())


def get_lodging_pricing(
    destination,
    nights,
    check_in_date,
    check_out_date,
    adults=2,
    max_total_budget=None,
):
    """
    Retrieves Best Value, Best Quality, and Best Resort choices.

    Best Value remains the lodging price used for destination ranking.
    """
    if not SERPAPI_API_KEY:
        return _fallback_lodging_result(
            destination,
            nights,
            "SERPAPI_API_KEY is missing",
            check_in_date,
            check_out_date,
        )

    city = str(destination.get("city", "")).strip()
    country = str(destination.get("country", "")).strip()

    if not city:
        return _fallback_lodging_result(
            destination,
            nights,
            "Destination city is missing",
            check_in_date,
            check_out_date,
        )

    destination_text = f"{city}, {country}" if country else city

    try:
        value_results = _request_hotel_properties(
            f"hotels in {destination_text}",
            check_in_date,
            check_out_date,
            adults,
            sort_by="3",
        )
        quality_results = _request_hotel_properties(
            f"hotels in {destination_text}",
            check_in_date,
            check_out_date,
            adults,
        )
        resort_results = _request_hotel_properties(
            f"resorts in {destination_text}",
            check_in_date,
            check_out_date,
            adults,
        )
    except requests.RequestException as error:
        return _fallback_lodging_result(
            destination,
            nights,
            f"SerpAPI hotel request failed: {error}",
            check_in_date,
            check_out_date,
        )
    except (ValueError, RuntimeError) as error:
        return _fallback_lodging_result(
            destination,
            nights,
            f"SerpAPI returned unusable hotel data: {error}",
            check_in_date,
            check_out_date,
        )

    parsed_properties = []

    for property_result in (
        list(value_results)
        + list(quality_results)
        + list(resort_results)
    ):
        parsed = _extract_property_price(property_result)

        if parsed is not None:
            parsed["display_link"] = _preferred_property_link(
                parsed,
                city=city,
                country=country,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
            )
            parsed_properties.append(parsed)

    parsed_properties = _deduplicate_properties(parsed_properties)

    if not parsed_properties:
        return _fallback_lodging_result(
            destination,
            nights,
            "No hotel properties with usable prices were returned",
            check_in_date,
            check_out_date,
        )

    def is_acceptable_property(item):
        name = str(item.get("name") or "").lower()
        property_type = str(item.get("type") or "").lower()
        rating = item.get("rating")
        reviews = item.get("reviews")

        is_hostel = "hostel" in name or "hostel" in property_type
        has_good_rating = isinstance(rating, (int, float)) and rating >= 3.5
        has_enough_reviews = isinstance(reviews, (int, float)) and reviews >= 20
        has_usable_link = bool(item.get("display_link"))

        return (
            not is_hostel
            and has_good_rating
            and has_enough_reviews
            and has_usable_link
        )

    acceptable_properties = [
        item for item in parsed_properties
        if is_acceptable_property(item)
    ]

    if not acceptable_properties:
        return _fallback_lodging_result(
            destination,
            nights,
            "No acceptable hotel properties with usable links were returned",
            check_in_date,
            check_out_date,
        )

    selected_property = min(
        acceptable_properties,
        key=lambda item: _property_total(item, nights),
    )
    selected_property = dict(selected_property)
    selected_property["total"] = round(
        _property_total(selected_property, nights),
        2,
    )

    nightly_prices = [item["nightly"] for item in acceptable_properties]
    lodging_total = _property_total(selected_property, nights)

    budget_limit = (
        float(max_total_budget)
        if isinstance(max_total_budget, (int, float))
        and max_total_budget >= 0
        else None
    )

    quality_candidates = [
        item
        for item in acceptable_properties
        if item.get("name") != selected_property.get("name")
        and (
            budget_limit is None
            or _property_total(item, nights) <= budget_limit
        )
    ]

    quality_property = None
    if quality_candidates:
        quality_property = max(
            quality_candidates,
            key=lambda item: _quality_sort_key(item, nights),
        )
        quality_property = dict(quality_property)
        quality_property["total"] = round(
            _property_total(quality_property, nights),
            2,
        )

    resort_candidates = [
        item
        for item in acceptable_properties
        if _is_resort_property(item)
        and (
            budget_limit is None
            or _property_total(item, nights) <= budget_limit
        )
    ]

    resort_property = None
    if resort_candidates:
        resort_property = max(
            resort_candidates,
            key=lambda item: _quality_sort_key(item, nights),
        )
        resort_property = dict(resort_property)
        resort_property["total"] = round(
            _property_total(resort_property, nights),
            2,
        )

    return {
        "properties_checked": len(parsed_properties),
        "acceptable_properties": len(acceptable_properties),
        "min_nightly": round(min(nightly_prices), 2),
        "max_nightly": round(max(nightly_prices), 2),
        "average_nightly": round(mean(nightly_prices), 2),
        "lodging_total": round(lodging_total, 2),
        "selected_property": selected_property,
        "quality_property": quality_property,
        "resort_property": resort_property,
        "hotel_budget_available": (
            round(budget_limit, 2)
            if budget_limit is not None
            else None
        ),
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "nights": nights,
        "source": "SerpAPI",
        "reason": None,
    }