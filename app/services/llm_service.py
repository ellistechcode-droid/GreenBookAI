import json
import os
from datetime import date
from typing import Any

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONFIGURED_GEMINI_MODEL = os.getenv("GEMINI_MODEL")

DEFAULT_GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]

CLASSIFICATION_TIMEOUT_MS = 20_000
RECOMMENDATION_TIMEOUT_MS = 45_000
MAX_RECOMMENDATION_OUTPUT_TOKENS = 2_400


def _get_model_candidates():
    candidates = []
    if CONFIGURED_GEMINI_MODEL:
        candidates.append(CONFIGURED_GEMINI_MODEL)
    for model in DEFAULT_GEMINI_MODELS:
        if model not in candidates:
            candidates.append(model)
    return candidates


def _is_model_unavailable_error(error):
    error_text = str(error).lower()
    return (
        "404" in error_text
        or "not_found" in error_text
        or "no longer available" in error_text
        or "not found" in error_text
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            value = json.loads(cleaned[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _format_money(value):
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "Unavailable"


def _format_date(value):
    if not value:
        return "Unavailable"
    try:
        return date.fromisoformat(str(value)).strftime("%b %-d, %Y")
    except ValueError:
        try:
            return date.fromisoformat(str(value)).strftime("%b %#d, %Y")
        except (ValueError, TypeError):
            return str(value)


def _format_date_range(outbound, return_date):
    try:
        start = date.fromisoformat(str(outbound))
        end = date.fromisoformat(str(return_date))
        if start.year == end.year and start.month == end.month:
            return f"{start.strftime('%b')} {start.day}–{end.day}, {start.year}"
        return f"{start.strftime('%b')} {start.day}, {start.year}–{end.strftime('%b')} {end.day}, {end.year}"
    except (ValueError, TypeError):
        return f"{outbound}–{return_date}"


def _format_duration_compact(minutes):
    """Formats a duration for display without exposing raw minute totals."""
    try:
        total_minutes = int(minutes)
    except (TypeError, ValueError):
        return "Unavailable"

    if total_minutes < 0:
        return "Unavailable"

    hours, remaining = divmod(total_minutes, 60)
    if hours and remaining:
        return f"{hours} hr {remaining} min"
    if hours:
        return f"{hours} hr"
    return f"{remaining} min"


def _format_layover(minutes, airports, connections):
    try:
        connection_count = int(connections)
    except (TypeError, ValueError):
        connection_count = None

    if connection_count == 0:
        return "Direct flight"

    duration = _format_duration_compact(minutes)
    if duration == "Unavailable":
        return "Unavailable"

    if isinstance(airports, list) and airports:
        return f"{duration} in {', '.join(str(value) for value in airports)}"

    return duration


def _airline_text(flight):
    airlines = flight.get("airlines") or []
    return ", ".join(str(value) for value in airlines if value) or "Unavailable"


def _route_text(recommendation, flight):
    origin = flight.get("origin_airport") or recommendation.get("origin") or "Origin"
    destination = flight.get("destination_airport") or recommendation.get("destination") or "Destination"
    outbound = _format_date(recommendation.get("outbound_date"))
    return_date = _format_date(recommendation.get("return_date"))
    return f"{origin} → {destination}, {outbound}; return {destination} → {origin}, {return_date}"


def _fallback_text(pricing):
    flight_fallback = pricing.get("flight_fallback_used", False)
    lodging_fallback = pricing.get("lodging_fallback_used", False)
    if flight_fallback and lodging_fallback:
        return "Flight and lodging"
    if flight_fallback:
        return "Flight only"
    if lodging_fallback:
        return "Lodging only"
    return "None"


def _deterministic_paragraph(recommendation, rank):
    destination = recommendation.get("destination", "This destination")
    description = str(recommendation.get("destination_description") or "").strip()
    if not description:
        description = (
            f"{destination} is represented in GreenBookAI's destination inventory."
        )

    trip_types = recommendation.get("trip_types") or []
    styles = ", ".join(str(value).replace("_", " ") for value in trip_types if value)
    total = _format_money(recommendation.get("estimated_total_cost"))
    score = recommendation.get("score")
    safety = recommendation.get("safety_score")
    attraction = recommendation.get("attraction_score")
    pricing = recommendation.get("pricing") or {}
    flight = pricing.get("flight") or {}

    features = []
    if styles:
        features.append(f"its {styles} travel profile")
    if flight.get("flight_practicality") == "direct":
        features.append("a direct available flight itinerary")
    features.append(f"an estimated trip total of {total}")
    if attraction is not None:
        features.append(f"an attraction score of {attraction}/10")

    reason_text = ", ".join(features)
    return (
        f"{description} It ranks #{rank} because GreenBookAI's scoring pipeline "
        f"evaluated {reason_text}. Its final score is {score}, with a supplied "
        f"safety score of {safety}/10 and attraction score of {attraction}/10. "
        f"The ranking reflects the structured itinerary, pricing, weather, "
        f"destination metadata, and advisory evidence shown above."
    )


def _paragraph_context(recommendations):
    items = []
    for rank, rec in enumerate(recommendations, start=1):
        pricing = rec.get("pricing") or {}
        flight = pricing.get("flight") or {}
        lodging = pricing.get("lodging") or {}
        selected = lodging.get("selected_property") or {}
        quality = lodging.get("quality_property") or {}
        resort = lodging.get("resort_property") or {}
        weather = rec.get("seasonal_weather") or {}
        advisory = rec.get("travel_advisory") or {}

        items.append({
            "rank": rank,
            "destination": rec.get("destination"),
            "destination_description": rec.get("destination_description"),
            "trip_types": rec.get("trip_types") or [],
            "estimated_total_cost": rec.get("estimated_total_cost"),
            "score": rec.get("score"),
            "safety_score": rec.get("safety_score"),
            "attraction_score": rec.get("attraction_score"),
            "flight_practicality": flight.get("flight_practicality"),
            "flight_fallback_used": pricing.get("flight_fallback_used"),
            "lodging_fallback_used": pricing.get("lodging_fallback_used"),
            "best_value_hotel": selected.get("name"),
            "best_quality_hotel_within_budget": quality.get("name"),
            "best_resort_within_budget": resort.get("name"),
            "weather": weather,
            "advisory_level": advisory.get("advisory_level"),
            "reasons": rec.get("reasons") or [],
        })
    return items


def _generate_paragraphs(user_prompt, recommendations):
    """
    Gemini may explain the structured evidence, but it does not render the hard
    fact block. If Gemini is unavailable, deterministic paragraphs are used.
    """
    deterministic = {
        str(rank): _deterministic_paragraph(rec, rank)
        for rank, rec in enumerate(recommendations, start=1)
    }

    if not GEMINI_API_KEY:
        return deterministic

    instructions = f"""
You are the explanation layer for GreenBookAI.

Write exactly one concise paragraph for each ranked destination using ONLY the
verified JSON below. Return JSON only in this shape:
{{"paragraphs": {{"1": "...", "2": "...", "3": "..."}}}}

Rules:
- Keep each paragraph about 90 to 140 words.
- Begin with the supplied destination_description whenever it is present.
- Explain why the destination ranked where it did.
- Interpret the structured evidence instead of repeating every fact-line value.
- You may mention cost, trip style, flight convenience, safety, attraction,
  five-year historical weather, advisory level, or fallback status when useful.
- Do not invent attractions, airline names, prices, dates, weather, hotels,
  safety claims, links, or other facts.
- Do not describe current weather; the recommendation uses five-year historical
  climate data for the travel period.
- Treat GreenBookAI's supplied ranking as final.
- Do not add Markdown headings or bullet points.

Traveler request:
{user_prompt}

Verified ranked evidence:
{json.dumps(_paragraph_context(recommendations), ensure_ascii=False)}
"""

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": RECOMMENDATION_TIMEOUT_MS},
    )

    for model in _get_model_candidates():
        try:
            response = client.models.generate_content(
                model=model,
                contents=instructions,
                config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": MAX_RECOMMENDATION_OUTPUT_TOKENS,
                    "temperature": 0.25,
                    "http_options": {"timeout": RECOMMENDATION_TIMEOUT_MS},
                },
            )
            text = getattr(response, "text", None)
            parsed = _extract_json_object(text or "")
            paragraphs = (parsed or {}).get("paragraphs")
            if isinstance(paragraphs, dict):
                merged = dict(deterministic)
                for key, value in paragraphs.items():
                    if str(key) in merged and isinstance(value, str) and value.strip():
                        merged[str(key)] = value.strip()
                return merged
        except Exception as error:
            print(f"Gemini recommendation paragraph generation failed with {model}: {error}")
            if _is_model_unavailable_error(error):
                continue
            break

    return deterministic


def _format_destination_block(recommendation, rank, paragraph):
    pricing = recommendation.get("pricing") or {}
    flight = pricing.get("flight") or {}
    lodging = pricing.get("lodging") or {}
    selected = lodging.get("selected_property") or {}
    quality = lodging.get("quality_property") or {}
    resort = lodging.get("resort_property") or {}
    weather = recommendation.get("seasonal_weather") or {}

    destination = recommendation.get("destination", "Unknown destination")
    outbound = recommendation.get("outbound_date")
    return_date = recommendation.get("return_date")
    nights = pricing.get("validated_nights", recommendation.get("trip_length_nights"))

    airlines = _airline_text(flight)
    route = _route_text(recommendation, flight)
    flight_price = (
        flight.get("total_price")
        if flight.get("total_price") is not None
        else pricing.get("flight_total")
    )
    flight_link = flight.get("search_url")
    flight_link_text = (
        f"[View flight]({flight_link})"
        if flight_link
        else "Unavailable"
    )

    hotel_name = selected.get("name") or "No specific live hotel selected"
    lodging_total = lodging.get("lodging_total")
    hotel_rating = selected.get("rating")
    hotel_reviews = selected.get("reviews")
    hotel_link = selected.get("display_link")
    hotel_link_text = (
        f"[View hotel]({hotel_link})"
        if hotel_link
        else "Unavailable"
    )

    quality_name = quality.get("name")
    quality_total = quality.get("total")
    quality_rating = quality.get("rating")
    quality_reviews = quality.get("reviews")
    quality_link = quality.get("display_link")
    quality_link_text = (
        f"[View hotel]({quality_link})"
        if quality_link
        else "Unavailable"
    )

    resort_name = resort.get("name")
    resort_total = resort.get("total")
    resort_rating = resort.get("rating")
    resort_reviews = resort.get("reviews")
    resort_link = resort.get("display_link")
    resort_link_text = (
        f"[View resort]({resort_link})"
        if resort_link
        else "Unavailable"
    )

    check_in = lodging.get("check_in_date") or outbound
    check_out = lodging.get("check_out_date") or return_date

    years = weather.get("historical_years") or []
    years_text = (
        f"{years[0]}–{years[-1]}"
        if len(years) >= 2
        else (str(years[0]) if years else "historical")
    )
    month_name = str(recommendation.get("trip_month") or "travel-period").title()

    avg_high = weather.get("average_high")
    avg_low = weather.get("average_low")
    avg_mean = weather.get("average_temperature")
    weather_text = (
        f"Avg high {avg_high}°F · Avg low {avg_low}°F · Mean {avg_mean}°F "
        f"({years_text})"
        if avg_high is not None and avg_low is not None and avg_mean is not None
        else "Unavailable"
    )

    lines = [
        f"**{destination} — Rank #{rank}**  ",
        f"**Trip dates:** {_format_date_range(outbound, return_date)}  ",
        f"**Flight:** {airlines}, {route}  ",
        f"**Outbound flight time:** {_format_duration_compact(flight.get('outbound_duration'))}  ",
        f"**Outbound layover:** {_format_layover(flight.get('outbound_layover_duration'), flight.get('outbound_layover_airports'), flight.get('connection_count'))}  ",
        f"**Return flight time:** {_format_duration_compact(flight.get('return_duration'))}  ",
        f"**Return layover:** {_format_layover(flight.get('return_layover_duration'), flight.get('return_layover_airports'), flight.get('return_connection_count'))}  ",
        f"**Flight price:** {_format_money(flight_price)} round trip  ",
        f"**Flight link:** {flight_link_text}  ",
        f"**Best Value Stay:** {hotel_name}  ",
        (
            f"**Best Value Stay rating:** {hotel_rating}/5 · {int(hotel_reviews):,} reviews  "
            if isinstance(hotel_rating, (int, float)) and isinstance(hotel_reviews, (int, float))
            else "**Best Value Stay rating:** Unavailable  "
        ),
        f"**Best Value Stay total:** {_format_money(lodging_total)} for {nights} nights  ",
        f"**Best Value Stay link:** {hotel_link_text}  ",
        (
            f"**Best Quality Hotel Within Budget:** {quality_name}  "
            if quality_name
            else "**Best Quality Hotel Within Budget:** No distinct higher-quality option found within budget  "
        ),
        (
            f"**Best Quality Hotel total:** {_format_money(quality_total)} for {nights} nights  "
            if quality_name
            else "**Best Quality Hotel total:** Unavailable  "
        ),
        (
            f"**Best Quality Hotel rating:** {quality_rating}/5 · {int(quality_reviews):,} reviews  "
            if quality_name
            and isinstance(quality_rating, (int, float))
            and isinstance(quality_reviews, (int, float))
            else "**Best Quality Hotel rating:** Unavailable  "
        ),
        (
            f"**Best Quality Hotel link:** {quality_link_text}  "
            if quality_name
            else "**Best Quality Hotel link:** Unavailable  "
        ),
        (
            f"**Best Resort Within Budget:** {resort_name}  "
            if resort_name
            else "**Best Resort Within Budget:** No qualifying resort found within budget  "
        ),
        (
            f"**Best Resort rating:** {resort_rating}/5 · {int(resort_reviews):,} reviews  "
            if resort_name
            and isinstance(resort_rating, (int, float))
            and isinstance(resort_reviews, (int, float))
            else "**Best Resort rating:** Unavailable  "
        ),
        (
            f"**Best Resort total:** {_format_money(resort_total)} for {nights} nights  "
            if resort_name
            else "**Best Resort total:** Unavailable  "
        ),
        (
            f"**Best Resort link:** {resort_link_text}  "
            if resort_name
            else "**Best Resort link:** Unavailable  "
        ),
        f"**Check-in:** {_format_date(check_in)}  ",
        f"**Check-out:** {_format_date(check_out)}  ",
        f"**5-year {month_name} weather:** {weather_text}  ",
        f"**Estimated trip total:** {_format_money(recommendation.get('estimated_total_cost'))}  ",
        f"**Fallback data:** {_fallback_text(pricing)}  ",
        "",
        paragraph,
    ]
    return "\n".join(lines)


def _final_comparison(recommendations):
    def cost(rec):
        try:
            return float(rec.get("estimated_total_cost"))
        except (TypeError, ValueError):
            return float("inf")

    def safety(rec):
        try:
            return float(rec.get("safety_score"))
        except (TypeError, ValueError):
            return float("-inf")

    def flight_key(rec):
        flight = ((rec.get("pricing") or {}).get("flight") or {})
        connections = flight.get("connection_count")
        duration = flight.get("outbound_duration")
        return (
            connections if isinstance(connections, int) else 999,
            duration if isinstance(duration, (int, float)) else 999999,
        )

    top = recommendations[0]
    cheapest = min(recommendations, key=cost)
    safest = max(recommendations, key=safety)
    easiest = min(recommendations, key=flight_key)
    alternative = recommendations[1] if len(recommendations) > 1 else top

    return (
        "## Final Comparison\n\n"
        f"- **Best Overall Result:** {top.get('destination')} (GreenBookAI rank #1).\n"
        f"- **Least Expensive Result:** {cheapest.get('destination')} "
        f"({_format_money(cheapest.get('estimated_total_cost'))} total).\n"
        f"- **Strongest Safety Score:** {safest.get('destination')} "
        f"({safest.get('safety_score')}/10).\n"
        f"- **Easiest Available Flight:** {easiest.get('destination')}.\n"
        f"- **Strongest Alternative to the First-Ranked Result:** "
        f"{alternative.get('destination')}."
    )


def generate_ai_recommendation(user_prompt, budget, recommendations):
    """
    Returns GreenBookAI's hybrid recommendation format.

    Hard facts, links, dates, costs, weather statistics, and fallback status are
    rendered deterministically. Gemini is limited to one grounded explanatory
    paragraph per destination.
    """
    if not recommendations:
        return "GreenBookAI could not find any matching destinations."

    paragraphs = _generate_paragraphs(user_prompt, recommendations)

    sections = ["## Best Overall Recommendation", ""]
    sections.append(
        _format_destination_block(
            recommendations[0],
            1,
            paragraphs["1"],
        )
    )

    if len(recommendations) > 1:
        sections.extend(["", "## Other Recommended Destinations", ""])
        for rank, recommendation in enumerate(recommendations[1:], start=2):
            sections.append(
                _format_destination_block(
                    recommendation,
                    rank,
                    paragraphs[str(rank)],
                )
            )
            sections.append("")

    sections.append(_final_comparison(recommendations))
    return "\n".join(sections).strip()


def _format_duration(minutes):
    """Backward-compatible readable duration helper."""
    return _format_duration_compact(minutes)


def _friendly_error_message(error):
    """Backward-compatible safe Gemini error message."""
    if error is None:
        return "Gemini returned no response."
    text = str(error).lower()
    if "429" in text or "resource_exhausted" in text:
        return "Gemini is temporarily rate-limited. Please retry shortly."
    if "deadline_exceeded" in text or "timeout" in text or "timed out" in text:
        return "Gemini did not respond within the configured time limit."
    if "403" in text or "permission_denied" in text:
        return "Gemini rejected the API credentials or project permissions."
    return "Gemini could not generate the explanation."


def _build_deterministic_recommendation(user_prompt, budget, recommendations):
    """Backward-compatible deterministic recommendation entry point."""
    paragraphs = {
        str(rank): _deterministic_paragraph(rec, rank)
        for rank, rec in enumerate(recommendations, start=1)
    }
    sections = ["## Best Overall Recommendation", ""]
    if not recommendations:
        return "GreenBookAI could not find any matching destinations."
    sections.append(_format_destination_block(recommendations[0], 1, paragraphs["1"]))
    if len(recommendations) > 1:
        sections.extend(["", "## Other Recommended Destinations", ""])
        for rank, rec in enumerate(recommendations[1:], start=2):
            sections.append(_format_destination_block(rec, rank, paragraphs[str(rank)]))
            sections.append("")
    sections.append(_final_comparison(recommendations))
    return "\n".join(sections).strip()


def classify_destination_metadata(
    city: str,
    country: str,
    region: str,
    subregion: str,
    latitude: Any,
    longitude: Any,
    category_counts: dict[str, int],
    sample_places: list[str],
) -> dict[str, Any] | None:
    """Classifies one destination with a strict request deadline."""
    if not GEMINI_API_KEY:
        return None

    allowed_trip_types = [
        "adventure", "art", "beach", "city", "culture", "family",
        "food", "history", "nature", "nightlife", "resort", "romance",
        "technology", "water_sports", "wellness",
    ]

    evidence = {
        "city": city,
        "country": country,
        "region": region,
        "subregion": subregion,
        "latitude": latitude,
        "longitude": longitude,
        "nearby_category_counts": category_counts,
        "sample_nearby_places": sample_places,
    }

    instructions = f"""
You classify destination metadata for GreenBookAI.

Use only the supplied geographic identity and Geoapify evidence. Do not invent
specific attractions, prices, safety claims, airport codes, or weather values.

Return one JSON object with exactly these keys:
- "trip_types": exactly three distinct labels
- "climate_tag": one of "warm", "mild", or "cold"
- "destination_description": one grounded sentence of 18 to 35 words

Allowed trip type labels:
{json.dumps(allowed_trip_types)}

Classification rules:
- Rank the three trip types from strongest to weakest.
- Prefer evidence-supported labels over generic assumptions.
- The description may summarize broad destination characteristics but must not
  name an attraction unless it appears in sample_nearby_places.
- Output JSON only.

Destination evidence:
{json.dumps(evidence, ensure_ascii=False)}
"""

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": CLASSIFICATION_TIMEOUT_MS},
    )

    for model in _get_model_candidates():
        try:
            response = client.models.generate_content(
                model=model,
                contents=instructions,
                config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": 350,
                    "temperature": 0.2,
                    "http_options": {"timeout": CLASSIFICATION_TIMEOUT_MS},
                },
            )
            text = getattr(response, "text", None)
            if text:
                parsed = _extract_json_object(text)
                if parsed:
                    return parsed
        except Exception as error:
            print(f"Gemini classification failed with {model}: {error}")
            if _is_model_unavailable_error(error):
                continue
            return None

    return None