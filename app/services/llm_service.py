import json
import os
from typing import Any

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONFIGURED_GEMINI_MODEL = os.getenv("GEMINI_MODEL")

# Keep the list short. Trying many models can multiply request time.
DEFAULT_GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]

CLASSIFICATION_TIMEOUT_MS = 20_000
RECOMMENDATION_TIMEOUT_MS = 45_000

# A detailed explanation should never collapse into a two-sentence response.
MIN_RECOMMENDATION_CHARACTERS = 1_200
MAX_RECOMMENDATION_OUTPUT_TOKENS = 2_400


def _build_llm_context(user_prompt, budget, recommendations):
    """Creates a compact, grounded context for Gemini."""
    compact_results = []

    for rank, recommendation in enumerate(recommendations, start=1):
        pricing = recommendation.get("pricing") or {}
        flight = pricing.get("flight") or {}
        lodging = pricing.get("lodging") or {}
        selected_property = lodging.get("selected_property") or {}
        advisory = recommendation.get("travel_advisory") or {}
        seasonal_weather = recommendation.get("seasonal_weather") or {}

        compact_results.append({
            "rank": rank,
            "destination": recommendation.get("destination"),
            "country": recommendation.get("country"),
            "region": recommendation.get("region"),
            "subregion": recommendation.get("subregion"),
            "trip_type": recommendation.get("trip_type"),
            "trip_types": recommendation.get("trip_types") or [],
            "score": recommendation.get("score"),
            "embedding_similarity": recommendation.get("embedding_similarity"),
            "outbound_date": recommendation.get("outbound_date"),
            "return_date": recommendation.get("return_date"),
            "trip_length_nights": recommendation.get("trip_length_nights"),
            "estimated_total_cost_usd": recommendation.get("estimated_total_cost"),
            "flight_price_usd": flight.get("total_price"),
            "flight_practicality": flight.get("flight_practicality"),
            "flight_duration_minutes": flight.get("outbound_duration"),
            "flight_connections": flight.get("connection_count"),
            "flight_source": flight.get("source"),
            "flight_fallback_used": pricing.get(
                "flight_fallback_used",
                flight.get("source") == "fallback",
            ),
            "lodging_total_usd": lodging.get("lodging_total"),
            "lodging_name": selected_property.get("name"),
            "lodging_type": selected_property.get("type"),
            "lodging_nightly_usd": selected_property.get("nightly"),
            "lodging_rating": selected_property.get("rating"),
            "lodging_review_count": selected_property.get("reviews"),
            "lodging_hotel_class": selected_property.get("hotel_class"),
            "lodging_source": lodging.get("source"),
            "lodging_fallback_used": pricing.get(
                "lodging_fallback_used",
                lodging.get("source") == "csv_fallback",
            ),
            "current_temperature_f": recommendation.get("current_temperature"),
            "current_weather_condition": recommendation.get(
                "current_weather_condition"
            ),
            "seasonal_average_temperature_f": seasonal_weather.get(
                "average_temperature"
            ),
            "safety_score": recommendation.get("safety_score"),
            "attraction_score": recommendation.get("attraction_score"),
            "advisory_level": advisory.get("advisory_level"),
            "advisory_text": advisory.get("advisory_text"),
            "advisory_source": advisory.get("source"),
            "advisory_latest_update": advisory.get("latest_update"),
            "reasons": recommendation.get("reasons", []),
        })

    return {
        "user_prompt": user_prompt,
        "budget_usd": budget,
        "ranked_recommendations": compact_results,
    }


def _get_model_candidates():
    """Returns the configured model first, followed by supported fallbacks."""
    candidates = []

    if CONFIGURED_GEMINI_MODEL:
        candidates.append(CONFIGURED_GEMINI_MODEL)

    for model in DEFAULT_GEMINI_MODELS:
        if model not in candidates:
            candidates.append(model)

    return candidates


def _is_model_unavailable_error(error):
    """Identifies model errors that justify trying the next model."""
    error_text = str(error).lower()
    return (
        "404" in error_text
        or "not_found" in error_text
        or "no longer available" in error_text
        or "not found" in error_text
    )


def _friendly_error_message(error: Exception | None) -> str:
    """Returns a safe user-facing explanation without dumping provider JSON."""
    if error is None:
        return "Gemini returned no response."

    text = str(error).lower()

    if "429" in text or "resource_exhausted" in text:
        return "Gemini is temporarily rate-limited. Please retry shortly."
    if "deadline_exceeded" in text or "timeout" in text or "timed out" in text:
        return "Gemini did not respond within the configured time limit."
    if "503" in text or "unavailable" in text:
        return "Gemini is temporarily unavailable."
    if "403" in text or "permission_denied" in text:
        return "Gemini rejected the API credentials or project permissions."

    return "Gemini could not generate the explanation."


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Parses Gemini JSON, including Markdown-fenced responses."""
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


def _format_money(value: Any) -> str:
    """Formats numeric prices safely."""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "unavailable"


def _format_duration(minutes: Any) -> str:
    """Converts minutes to readable hours and minutes."""
    try:
        total_minutes = int(minutes)
    except (TypeError, ValueError):
        return "unavailable"

    hours, remaining_minutes = divmod(total_minutes, 60)

    if remaining_minutes:
        return f"{hours} hours and {remaining_minutes} minutes"

    return f"{hours} hours"


def _safe_number(value: Any, default: float) -> float:
    """Returns a float for comparisons without raising conversion errors."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_deterministic_recommendation(
    user_prompt,
    budget,
    recommendations,
):
    """
    Produces a detailed explanation directly from structured recommendation data.

    This is used whenever Gemini fails, times out, or returns a suspiciously
    short answer, so the frontend never receives only two generic sentences.
    """
    if not recommendations:
        return "GreenBookAI could not find any matching destinations."

    sections = []
    top = recommendations[0]

    for index, recommendation in enumerate(recommendations):
        destination = recommendation.get("destination", "Unknown destination")
        country = recommendation.get("country", "Unknown country")

        trip_types = recommendation.get("trip_types") or [
            recommendation.get("trip_type", "general travel")
        ]
        readable_trip_types = ", ".join(
            str(value).replace("_", " ")
            for value in trip_types
            if value
        ) or "general travel"

        pricing = recommendation.get("pricing") or {}
        flight = pricing.get("flight") or {}
        lodging = pricing.get("lodging") or {}
        selected_property = lodging.get("selected_property") or {}
        advisory = recommendation.get("travel_advisory") or {}
        seasonal_weather = recommendation.get("seasonal_weather") or {}

        total_cost = recommendation.get(
            "estimated_total_cost",
            pricing.get("estimated_total_cost"),
        )

        if budget is not None and total_cost is not None:
            remaining_budget = _safe_number(budget, 0) - _safe_number(total_cost, 0)
            if remaining_budget >= 0:
                budget_sentence = (
                    f"This leaves approximately {_format_money(remaining_budget)} "
                    f"within the {_format_money(budget)} maximum budget."
                )
            else:
                budget_sentence = (
                    f"This exceeds the {_format_money(budget)} budget by "
                    f"approximately {_format_money(abs(remaining_budget))}."
                )
        else:
            budget_sentence = (
                "A precise comparison with the stated budget could not be calculated."
            )

        flight_price = flight.get(
            "total_price",
            recommendation.get("estimated_flight_cost"),
        )
        flight_duration = _format_duration(flight.get("outbound_duration"))
        practicality = str(
            flight.get("flight_practicality") or "unavailable"
        ).replace("_", " ")
        connection_count = flight.get("connection_count")

        lodging_name = selected_property.get(
            "name",
            "no specific property was selected",
        )
        lodging_total = lodging.get("lodging_total")
        nightly_rate = selected_property.get("nightly")
        lodging_rating = selected_property.get("rating")
        lodging_reviews = selected_property.get("reviews")
        hotel_class = selected_property.get("hotel_class")

        seasonal_temperature = seasonal_weather.get("average_temperature")
        current_temperature = recommendation.get("current_temperature")
        weather_condition = recommendation.get("current_weather_condition")

        if seasonal_temperature is not None:
            weather_sentence = (
                f"The available seasonal average temperature was approximately "
                f"{seasonal_temperature}°F."
            )
        elif current_temperature is not None:
            weather_sentence = (
                f"The available current temperature reading was approximately "
                f"{current_temperature}°F"
            )
            if weather_condition:
                weather_sentence += f" with {weather_condition}"
            weather_sentence += "."
        else:
            weather_sentence = "Weather information was unavailable."

        advisory_level = advisory.get("advisory_level", "Unavailable")
        advisory_text = advisory.get(
            "advisory_text",
            "No advisory description was available.",
        )

        flight_fallback = pricing.get(
            "flight_fallback_used",
            flight.get("source") == "fallback",
        )
        lodging_fallback = pricing.get(
            "lodging_fallback_used",
            lodging.get("source") == "csv_fallback",
        )

        if flight_fallback and lodging_fallback:
            fallback_sentence = (
                "Both the flight and lodging estimates used fallback data."
            )
        elif flight_fallback:
            fallback_sentence = (
                "The flight estimate used fallback data, while the lodging "
                "estimate did not."
            )
        elif lodging_fallback:
            fallback_sentence = (
                "The lodging estimate used fallback data, while the flight "
                "estimate did not."
            )
        else:
            fallback_sentence = (
                "Neither the flight nor lodging estimate was marked as fallback data."
            )

        if index == 0:
            heading = f"## Best Overall Recommendation: {destination}, {country}"
            intro = (
                f"{destination}, {country}, ranked first for the request "
                f"“{user_prompt}.”"
            )
        else:
            heading = f"## Alternative {index + 1}: {destination}, {country}"
            intro = (
                f"{destination}, {country}, ranked number {index + 1} "
                f"in GreenBookAI's official results."
            )

        paragraph_parts = [
            intro,
            (
                f"It is associated with {readable_trip_types} travel and received "
                f"a final score of {recommendation.get('score', 'unavailable')}."
            ),
            (
                f"The estimated total trip cost is {_format_money(total_cost)}. "
                f"{budget_sentence}"
            ),
            (
                f"The available flight was priced at {_format_money(flight_price)}, "
                f"with an outbound duration of {flight_duration}. Its flight "
                f"practicality was classified as {practicality}"
                + (
                    f", with {connection_count} reported connection"
                    f"{'' if connection_count == 1 else 's'}."
                    if connection_count is not None
                    else "."
                )
            ),
            (
                f"The selected lodging option was {lodging_name}, with an estimated "
                f"lodging total of {_format_money(lodging_total)}"
                + (
                    f" and a nightly rate of {_format_money(nightly_rate)}"
                    if nightly_rate is not None
                    else ""
                )
                + (
                    f". It was listed as {hotel_class}"
                    if hotel_class
                    else ""
                )
                + (
                    f", carried a rating of {lodging_rating}"
                    if lodging_rating is not None
                    else ""
                )
                + (
                    f", and had {lodging_reviews} reviews"
                    if lodging_reviews is not None
                    else ""
                )
                + "."
            ),
            weather_sentence,
            (
                f"The destination's safety score was "
                f"{recommendation.get('safety_score', 'unavailable')} out of 10, "
                f"while its attraction score was "
                f"{recommendation.get('attraction_score', 'unavailable')} out of 10."
            ),
            (
                f"The available travel advisory was {advisory_level}: "
                f"{advisory_text}."
            ),
            fallback_sentence,
        ]

        reasons = recommendation.get("reasons") or []
        if reasons:
            readable_reasons = "; ".join(str(reason) for reason in reasons)
            paragraph_parts.append(
                f"The scoring record also noted the following findings: "
                f"{readable_reasons}."
            )

        sections.append(f"{heading}\n\n{' '.join(paragraph_parts)}")

    cheapest = min(
        recommendations,
        key=lambda item: _safe_number(
            item.get("estimated_total_cost"),
            float("inf"),
        ),
    )
    safest = max(
        recommendations,
        key=lambda item: _safe_number(item.get("safety_score"), float("-inf")),
    )
    easiest_flight = min(
        recommendations,
        key=lambda item: (
            _safe_number(
                ((item.get("pricing") or {}).get("flight") or {}).get(
                    "connection_count"
                ),
                float("inf"),
            ),
            _safe_number(
                ((item.get("pricing") or {}).get("flight") or {}).get(
                    "outbound_duration"
                ),
                float("inf"),
            ),
        ),
    )
    strongest_alternative = (
        recommendations[1] if len(recommendations) > 1 else recommendations[0]
    )

    final_comparison = (
        "## Final Comparison\n\n"
        f"{top.get('destination')} remains GreenBookAI's best overall "
        f"recommendation because it received the highest official ranking. "
        f"{cheapest.get('destination')} was the least expensive option at "
        f"approximately {_format_money(cheapest.get('estimated_total_cost'))}. "
        f"{safest.get('destination')} had the strongest supplied safety score "
        f"at {safest.get('safety_score')} out of 10. "
        f"{easiest_flight.get('destination')} had the easiest available flight "
        f"based on the reported connection count and duration. "
        f"{strongest_alternative.get('destination')} was the highest-ranked "
        f"alternative to the top result. The final choice should balance cost, "
        f"flight convenience, lodging quality, trip style, weather information, "
        f"and the stated travel advisory."
    )
    sections.append(final_comparison)

    return "\n\n".join(sections)


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


def generate_ai_recommendation(user_prompt, budget, recommendations):
    """
    Uses Gemini to produce a detailed explanation of all ranked results.

    Suspiciously short or incomplete responses are rejected and replaced by
    a deterministic explanation built directly from the recommendation data.
    """
    if not recommendations:
        return "GreenBookAI could not find any matching destinations."

    if not GEMINI_API_KEY:
        return _build_deterministic_recommendation(
            user_prompt=user_prompt,
            budget=budget,
            recommendations=recommendations,
        )

    context = _build_llm_context(
        user_prompt=user_prompt,
        budget=budget,
        recommendations=recommendations,
    )

    destination_names = [
        recommendation.get("destination", "Unknown destination")
        for recommendation in recommendations
    ]

    budget_text = (
        _format_money(budget)
        if budget is not None
        else "not supplied"
    )

    instructions = f"""
You are the detailed explanation layer for GreenBookAI, a grounded travel
recommendation system.

Traveler request:
{user_prompt}

Maximum budget:
{budget_text}

Ranked destinations:
{", ".join(destination_names)}

Write a complete, detailed recommendation using only the verified GreenBookAI
data supplied below.

Required structure:

## Best Overall Recommendation

Write one substantial paragraph about the first-ranked destination. Explain:
- why it ranked first
- total estimated trip cost and how it compares with the budget
- flight price, duration, connections, and practicality
- selected lodging, lodging total, nightly rate, rating, and review count
- trip types
- available current or seasonal weather
- safety and attraction scores
- travel advisory level and meaning
- important advantages and tradeoffs
- whether flight or lodging values used fallback data

## Other Recommended Destinations

Write one detailed paragraph for every remaining destination. Discuss each
destination's cost, budget fit, flight, lodging, trip types, weather, safety,
attraction score, advisory, advantages, and disadvantages compared with the
top result.

## Final Comparison

Compare all destinations and clearly identify:
- the best overall result
- the least expensive result
- the result with the strongest supplied safety score
- the easiest available flight
- the strongest alternative to the first-ranked result

Rules:
- Discuss every destination in the supplied ranked results.
- Do not stop after the first destination.
- Do not return a two-sentence summary.
- Do not invent facts or fill unavailable fields with guesses.
- Treat the supplied order as GreenBookAI's official ranking.
- Explain negative advisory information clearly rather than omitting it.
- Clearly identify fallback pricing when present.
- Use readable Markdown headings.
- Write approximately 700 to 1,100 words.
- Finish all required sections before ending.

Verified GreenBookAI data:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": RECOMMENDATION_TIMEOUT_MS},
    )
    attempted_models = []
    last_error = None

    for model in _get_model_candidates():
        attempted_models.append(model)

        try:
            response = client.models.generate_content(
                model=model,
                contents=instructions,
                config={
                    "max_output_tokens": MAX_RECOMMENDATION_OUTPUT_TOKENS,
                    "temperature": 0.35,
                    "http_options": {"timeout": RECOMMENDATION_TIMEOUT_MS},
                },
            )

            text = getattr(response, "text", None)
            candidates = getattr(response, "candidates", None)
            finish_reason = None

            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)

            cleaned_text = text.strip() if text else ""

            print(
                f"Gemini model: {model}; "
                f"finish reason: {finish_reason}; "
                f"response characters: {len(cleaned_text)}"
            )

            if len(cleaned_text) >= MIN_RECOMMENDATION_CHARACTERS:
                return cleaned_text

            last_error = RuntimeError(
                f"{model} returned an incomplete explanation containing "
                f"{len(cleaned_text)} characters. Finish reason: {finish_reason}"
            )

            # A short answer may be model-specific, so try the next model.
            continue

        except Exception as error:
            last_error = error
            print(f"Gemini recommendation failed with {model}: {error}")

            if _is_model_unavailable_error(error):
                continue

            # Do not multiply timeouts or rate limits by trying every model.
            break

    attempted = ", ".join(attempted_models)
    print(
        "Gemini could not produce a complete recommendation. "
        f"Models attempted: {attempted}. "
        f"{_friendly_error_message(last_error)}"
    )

    return _build_deterministic_recommendation(
        user_prompt=user_prompt,
        budget=budget,
        recommendations=recommendations,
    )