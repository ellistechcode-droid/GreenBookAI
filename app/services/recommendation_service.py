import re
import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


def load_destinations():
    df = pd.read_csv("data/destinations.csv")
    return df.to_dict(orient="records")

def get_live_weather(city):
    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial"
    }

    response = requests.get(url, params=params)
    data = response.json()

    temperature = data.get("main", {}).get("temp")
    condition = data.get("weather", [{}])[0].get("description")

    return {
        "temperature": temperature,
        "condition": condition
    }

def calculate_weather_score(prompt, temperature, condition):
    prompt = prompt.lower()

    if temperature is None:
        return 0, "Weather data unavailable"

    score = 0
    reason = ""

    if "warm" in prompt or "hot" in prompt or "tropical" in prompt:
        if temperature >= 75:
            score = 25
            reason = f"Current temperature {temperature}°F matches warm preference"
        elif 65 <= temperature < 75:
            score = 15
            reason = f"Current temperature {temperature}°F is moderately warm"
        else:
            score = 0
            reason = f"Current temperature {temperature}°F does not match warm preference"

    elif "mild" in prompt or "comfortable" in prompt:
        if 60 <= temperature <= 75:
            score = 25
            reason = f"Current temperature {temperature}°F matches mild preference"
        else:
            score = 10
            reason = f"Current temperature {temperature}°F partially matches mild preference"

    elif "cold" in prompt or "snow" in prompt or "winter" in prompt:
        if temperature <= 45:
            score = 25
            reason = f"Current temperature {temperature}°F matches cold preference"
        else:
            score = 0
            reason = f"Current temperature {temperature}°F does not match cold preference"

    else:
        score = 10
        reason = "No specific weather preference detected"

    if condition and ("rain" in condition or "storm" in condition):
        score -= 5
        reason += f"; current condition is {condition}, reducing score"

    return score, reason

def extract_trip_length(prompt):
    prompt = prompt.lower()

    match = re.search(r"(\d+)\s*(night|nights|day|days)", prompt)

    if match:
        return int(match.group(1))

    return 3


def estimate_flight_cost(start_destination, destination):
    start = start_destination.lower()
    region = destination["region"]

    if "boston" in start:
        region_flight_estimates = {
            "North America": 250,
            "Caribbean": 350,
            "Europe": 700,
            "Asia": 950,
            "Africa": 900,
            "South America": 650,
            "Oceania": 1200
        }
    elif "miami" in start or "fort lauderdale" in start:
        region_flight_estimates = {
            "North America": 200,
            "Caribbean": 250,
            "Europe": 750,
            "Asia": 1100,
            "Africa": 950,
            "South America": 500,
            "Oceania": 1300
        }
    else:
        region_flight_estimates = {
            "North America": 300,
            "Caribbean": 450,
            "Europe": 800,
            "Asia": 1000,
            "Africa": 950,
            "South America": 750,
            "Oceania": 1300
        }

    return region_flight_estimates.get(region, 700)


def calculate_total_cost(start_destination, destination, nights):
    flight_cost = estimate_flight_cost(start_destination, destination)

    return flight_cost + (
        destination["estimated_nightly_cost"] * nights
    )


def calculate_score(start_destination, destination, prompt, budget, nights):
    prompt = prompt.lower()
    score = 0
    reasons = []

    total_cost = calculate_total_cost(start_destination, destination, nights)
    estimated_flight_cost = estimate_flight_cost(start_destination, destination)

    if destination["trip_type"] in prompt:
        score += 30
        reasons.append(f"Matches trip type: {destination['trip_type']}")

    weather = get_live_weather(destination["city"])
    weather_score, weather_reason = calculate_weather_score(
        prompt=prompt,
        temperature=weather["temperature"],
        condition=weather["condition"]
    )

    score += weather_score
    reasons.append(weather_reason)

    if total_cost <= budget:
        score += 25
        reasons.append(f"Estimated total cost ${total_cost} fits within budget")
    else:
        over_budget = total_cost - budget
        score -= 20
        reasons.append(f"Estimated total cost ${total_cost} exceeds budget by ${over_budget}")

    safety_points = int(destination["safety_score"])
    score += safety_points
    reasons.append(f"Safety score added {safety_points} points")

    attraction_points = int(destination["attraction_score"])
    score += attraction_points
    reasons.append(f"Attraction score added {attraction_points} points")

    return score, reasons, total_cost, estimated_flight_cost, weather


def get_recommendations(start_destination, prompt, budget):
    nights = extract_trip_length(prompt)
    prompt_lower = prompt.lower()
    results = []

    for destination in load_destinations():
        # Cheap local filtering before live API calls
        estimated_total_cost = calculate_total_cost(
            start_destination=start_destination,
            destination=destination,
            nights=nights
        )

        # Avoid obviously unaffordable options before calling weather API
        if estimated_total_cost > budget * 1.3:
            continue

        # Prefer matching trip type when user clearly mentions one
        known_trip_types = ["beach", "culture", "city", "nature"]
        requested_trip_types = [
            trip_type for trip_type in known_trip_types
            if trip_type in prompt_lower
        ]

        if requested_trip_types and destination["trip_type"] not in requested_trip_types:
            continue

        score, reasons, total_cost, estimated_flight_cost, weather = calculate_score(
            start_destination=start_destination,
            destination=destination,
            prompt=prompt,
            budget=budget,
            nights=nights
        )

        results.append({
            "destination": destination["city"],
            "country": destination["country"],
            "region": destination["region"],
            "trip_type": destination["trip_type"],
            "climate_tag": destination["climate_tag"],
            "score": score,
            "trip_length_nights": nights,
            "estimated_total_cost": total_cost,
            "estimated_flight_cost": estimated_flight_cost,
            "estimated_nightly_cost": destination["estimated_nightly_cost"],
            "safety_score": int(destination["safety_score"]),
            "attraction_score": int(destination["attraction_score"]),
            "current_temperature": weather["temperature"],
            "current_weather_condition": weather["condition"],
            "reasons": reasons
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]

