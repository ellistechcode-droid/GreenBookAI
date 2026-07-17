import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# An explicit GEMINI_MODEL in .env takes priority. Otherwise GreenBookAI
# tries current Gemini models in order until one works for the account.
CONFIGURED_GEMINI_MODEL = os.getenv("GEMINI_MODEL")
DEFAULT_GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
]


def _build_llm_context(user_prompt, budget, recommendations):
    """
    Creates a compact, grounded context for Gemini.

    Only verified GreenBookAI results are included so the model explains
    existing recommendations rather than inventing prices or destinations.
    """
    compact_results = []

    for rank, recommendation in enumerate(recommendations, start=1):
        pricing = recommendation.get("pricing", {})
        flight = pricing.get("flight", {})
        lodging = pricing.get("lodging", {})
        advisory = recommendation.get("travel_advisory", {})
        seasonal_weather = recommendation.get("seasonal_weather") or {}

        compact_results.append({
            "rank": rank,
            "destination": recommendation.get("destination"),
            "country": recommendation.get("country"),
            "trip_type": recommendation.get("trip_type"),
            "score": recommendation.get("score"),
            "embedding_similarity": recommendation.get(
                "embedding_similarity"
            ),
            "outbound_date": recommendation.get("outbound_date"),
            "return_date": recommendation.get("return_date"),
            "estimated_total_cost_usd": recommendation.get(
                "estimated_total_cost"
            ),
            "flight_price_usd": flight.get("total_price"),
            "flight_practicality": flight.get("flight_practicality"),
            "flight_duration_minutes": flight.get("outbound_duration"),
            "flight_fallback_used": pricing.get(
                "flight_fallback_used",
                flight.get("source") == "fallback",
            ),
            "lodging_total_usd": lodging.get("lodging_total"),
            "lodging_name": (
                lodging.get("selected_property") or {}
            ).get("name"),
            "lodging_rating": (
                lodging.get("selected_property") or {}
            ).get("rating"),
            "lodging_fallback_used": pricing.get(
                "lodging_fallback_used",
                lodging.get("source") == "csv_fallback",
            ),
            "seasonal_average_temperature_f": seasonal_weather.get(
                "average_temperature"
            ),
            "safety_score": recommendation.get("safety_score"),
            "attraction_score": recommendation.get("attraction_score"),
            "advisory_level": advisory.get("advisory_level"),
            "advisory_text": advisory.get("advisory_text"),
            "reasons": recommendation.get("reasons", []),
        })

    return {
        "user_prompt": user_prompt,
        "budget_usd": budget,
        "ranked_recommendations": compact_results,
    }


def _get_model_candidates():
    """
    Returns the configured model first, followed by supported fallbacks.
    """
    candidates = []

    if CONFIGURED_GEMINI_MODEL:
        candidates.append(CONFIGURED_GEMINI_MODEL)

    for model in DEFAULT_GEMINI_MODELS:
        if model not in candidates:
            candidates.append(model)

    return candidates


def _is_model_unavailable_error(error):
    """
    Identifies model-name or account-availability errors that justify trying
    the next Gemini model.
    """
    error_text = str(error).lower()

    return (
        "404" in error_text
        or "not_found" in error_text
        or "no longer available" in error_text
        or "not found" in error_text
    )


def generate_ai_recommendation(user_prompt, budget, recommendations):
    """
    Uses Gemini to explain GreenBookAI's ranked results in natural language.

    If a model is unavailable for the account, the next supported model is
    tried automatically. Structured recommendations remain available if all
    Gemini attempts fail.
    """
    if not recommendations:
        return "GreenBookAI could not find any matching destinations."

    if not GEMINI_API_KEY:
        return (
            "AI explanation unavailable because GEMINI_API_KEY is missing. "
            "The structured recommendations are still valid."
        )

    context = _build_llm_context(
        user_prompt=user_prompt,
        budget=budget,
        recommendations=recommendations,
    )

    instructions = f"""
You are the explanation layer for GreenBookAI, a grounded travel recommendation system.

Write a polished recommendation for the traveler using only the verified data below.

Rules:
- Do not invent prices, hotels, attractions, flight details, safety claims, or weather.
- Treat the existing order as GreenBookAI's official ranking.
- Start with a brief paragraph naming the strongest overall recommendation and why.
- Then give a concise paragraph for each remaining destination.
- Mention meaningful tradeoffs such as cost, flight convenience, lodging, weather, or advisory level.
- Clearly say when a flight or lodging value used a fallback.
- Keep the entire response between 250 and 450 words.
- Use readable headings, but do not output JSON.

Verified GreenBookAI data:
{json.dumps(context, ensure_ascii=False)}
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    attempted_models = []
    last_error = None

    for model in _get_model_candidates():
        attempted_models.append(model)

        try:
            response = client.models.generate_content(
                model=model,
                contents=instructions,
            )

            text = getattr(response, "text", None)

            if text:
                return text.strip()

            last_error = RuntimeError(
                f"{model} returned no explanation text"
            )

        except Exception as error:
            last_error = error

            if _is_model_unavailable_error(error):
                continue

            break

    attempted = ", ".join(attempted_models)

    return (
        "AI explanation unavailable, but the structured recommendations "
        f"remain valid. Models attempted: {attempted}. "
        f"Gemini error: {last_error}"
    )