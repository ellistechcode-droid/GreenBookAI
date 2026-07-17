import os
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.services.llm_service import generate_ai_recommendation
from app.services.recommendation_service import (
    get_recommendations,
    resolve_budget,
)

load_dotenv()

app = FastAPI(title="GreenBookAI")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


@app.get("/")
def root():
    return {
        "project": "GreenBookAI",
        "status": "Running",
    }


@app.get("/places/{city}")
def get_places(city: str):
    url = "https://api.geoapify.com/v1/geocode/search"

    params = {
        "text": city,
        "format": "json",
        "apiKey": GEOAPIFY_API_KEY,
    }

    response = requests.get(url, params=params, timeout=20)
    return response.json()


@app.get("/weather/{city}")
def get_weather(city: str):
    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial",
    }

    response = requests.get(url, params=params, timeout=20)
    data = response.json()

    return {
        "city": city,
        "temperature": data.get("main", {}).get("temp"),
        "feels_like": data.get("main", {}).get("feels_like"),
        "condition": data.get("weather", [{}])[0].get("description"),
        "raw": data,
    }


class TripRequest(BaseModel):
    start_destination: str = Field(
        default="Boston",
        description="Starting city. Defaults to Boston when omitted.",
    )
    prompt: str
    budget: Optional[float] = Field(
        default=None,
        description=(
            "Optional because GreenBookAI can extract budgets such as "
            "'within $1500' or 'budget of 3000' from the prompt."
        ),
    )


@app.post("/recommend")
def recommend_trip(request: TripRequest):
    resolved_budget = resolve_budget(
        prompt=request.prompt,
        budget=request.budget,
    )

    recommendations = get_recommendations(
        start_destination=request.start_destination,
        prompt=request.prompt,
        budget=resolved_budget,
    )

    ai_recommendation = generate_ai_recommendation(
        user_prompt=request.prompt,
        budget=resolved_budget,
        recommendations=recommendations,
    )

    return {
        "user_prompt": request.prompt,
        "start_destination": request.start_destination,
        "budget": resolved_budget,
        "ai_recommendation": ai_recommendation,
        "recommendations": recommendations,
    }