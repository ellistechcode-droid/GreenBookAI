from fastapi import FastAPI
from dotenv import load_dotenv
import os
import requests
from pydantic import BaseModel
from app.services.recommendation_service import get_recommendations


load_dotenv()

app = FastAPI(title="GreenBookAI")

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


@app.get("/")
def root():
    return {
        "project": "GreenBookAI",
        "status": "Running"
    }


@app.get("/places/{city}")
def get_places(city: str):
    url = "https://api.geoapify.com/v1/geocode/search"

    params = {
        "text": city,
        "format": "json",
        "apiKey": GEOAPIFY_API_KEY
    }

    response = requests.get(url, params=params)

    return response.json()

@app.get("/weather/{city}")
def get_weather(city: str):
    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial"
    }

    response = requests.get(url, params=params)
    data = response.json()

    return {
        "city": city,
        "temperature": data.get("main", {}).get("temp"),
        "feels_like": data.get("main", {}).get("feels_like"),
        "condition": data.get("weather", [{}])[0].get("description"),
        "raw": data
    }

class TripRequest(BaseModel):
    start_destination: str
    prompt: str
    budget: float


@app.post("/recommend")
def recommend_trip(request: TripRequest):
    recommendations = get_recommendations(
        start_destination=request.start_destination,
        prompt=request.prompt,
        budget=request.budget
    )

    return {
        "user_prompt": request.prompt,
        "start_destination": request.start_destination,
        "budget": request.budget,
        "recommendations": recommendations
    }