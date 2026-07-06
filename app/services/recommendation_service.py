import re
import os
import requests
from dotenv import load_dotenv
from app.services.location_service import get_candidate_locations, get_or_discover_location
from app.services.advisory_service import find_advisory_by_country, calculate_advisory_penalty
from app.services.travel_logistics_service import get_trip_pricing

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


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


def get_historical_weather(latitude, longitude, month):
    if month is None:
        return None

    url = "https://archive-api.open-meteo.com/v1/archive"

    start_date = f"2023-{month:02d}-01"
    end_date = f"2023-{month:02d}-28"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "auto"
    }

    response = requests.get(url, params=params)
    data = response.json()

    daily = data.get("daily", {})

    max_temps = daily.get("temperature_2m_max", [])
    min_temps = daily.get("temperature_2m_min", [])
    precipitation = daily.get("precipitation_sum", [])

    if not max_temps or not min_temps:
        return None

    avg_high = round(sum(max_temps) / len(max_temps), 1)
    avg_low = round(sum(min_temps) / len(min_temps), 1)
    avg_temp = round((avg_high + avg_low) / 2, 1)
    total_precipitation = round(sum(precipitation), 2) if precipitation else 0

    return {
        "average_high": avg_high,
        "average_low": avg_low,
        "average_temperature": avg_temp,
        "total_precipitation": total_precipitation
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


def calculate_seasonal_weather_score(prompt, seasonal_weather, month_name):
    prompt = prompt.lower()

    if seasonal_weather is None:
        return 0, "No seasonal weather estimate used"

    avg_temp = seasonal_weather["average_temperature"]
    total_precipitation = seasonal_weather["total_precipitation"]

    score = 0

    if "warm" in prompt or "hot" in prompt or "tropical" in prompt:
        if avg_temp >= 75:
            score += 20
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which supports warm-weather travel"
        elif 65 <= avg_temp < 75:
            score += 10
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which is moderately warm"
        else:
            score -= 5
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which may not match a warm-weather preference"

    elif "mild" in prompt or "comfortable" in prompt:
        if 60 <= avg_temp <= 75:
            score += 20
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which supports mild-weather travel"
        else:
            score += 5
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which partially matches a mild-weather preference"

    elif "cold" in prompt or "snow" in prompt or "winter" in prompt:
        if avg_temp <= 45:
            score += 20
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which supports cold-weather travel"
        else:
            score -= 5
            reason = f"Historical {month_name} average temperature is {avg_temp}°F, which may not match a cold-weather preference"

    else:
        score += 5
        reason = f"Historical {month_name} weather estimate included"

    if total_precipitation >= 5:
        score -= 5
        reason += f"; historical precipitation is {total_precipitation} inches, reducing score slightly"

    return score, reason


def extract_trip_length(prompt):
    prompt = prompt.lower()

    match = re.search(r"(\d+)\s*(night|nights|day|days)", prompt)

    if match:
        return int(match.group(1))

    return 3


def extract_trip_month(prompt):
    prompt = prompt.lower()

    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12
    }

    for month_name, month_number in months.items():
        if month_name in prompt:
            return month_number, month_name

    return None, None


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


def calculate_score(start_destination, destination, prompt, budget, nights, trip_month, month_name):
    prompt = prompt.lower()
    score = 0
    reasons = []

    estimated_flight_cost = estimate_flight_cost(start_destination, destination)

    pricing = get_trip_pricing(
        origin=start_destination,
        destination=destination,
        nights=nights,
        fallback_flight_cost=estimated_flight_cost
    )

    total_cost = pricing["estimated_total_cost"]

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

    seasonal_weather = get_historical_weather(
        latitude=destination["latitude"],
        longitude=destination["longitude"],
        month=trip_month
    )

    seasonal_score, seasonal_reason = calculate_seasonal_weather_score(
        prompt=prompt,
        seasonal_weather=seasonal_weather,
        month_name=month_name
    )

    score += seasonal_score
    reasons.append(seasonal_reason)

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

    advisory = find_advisory_by_country(destination["country"])
    advisory_penalty = calculate_advisory_penalty(advisory["advisory_level"])

    score += advisory_penalty

    if advisory_penalty < 0:
        reasons.append(
            f"Travel advisory reduced score by {abs(advisory_penalty)} points: "
            f"{advisory['advisory_text']}"
        )
    else:
        reasons.append("No travel advisory penalty applied")

    return score, reasons, total_cost, estimated_flight_cost, weather, seasonal_weather, advisory, pricing

def get_recommendations(start_destination, prompt, budget):
    nights = extract_trip_length(prompt)
    trip_month, month_name = extract_trip_month(prompt)
    prompt_lower = prompt.lower()
    results = []

    origin = get_or_discover_location(start_destination)

    for destination in get_candidate_locations():
        estimated_total_cost = calculate_total_cost(
            start_destination=start_destination,
            destination=destination,
            nights=nights
        )

        if estimated_total_cost > budget * 1.3:
            continue

        known_trip_types = ["beach", "culture", "city", "nature"]
        requested_trip_types = [
            trip_type for trip_type in known_trip_types
            if trip_type in prompt_lower
        ]

        if requested_trip_types and destination["trip_type"] not in requested_trip_types:
            continue

        score, reasons, total_cost, estimated_flight_cost, weather, seasonal_weather, advisory, pricing = calculate_score(
            start_destination=start_destination,
            destination=destination,
            prompt=prompt,
            budget=budget,
            nights=nights,
            trip_month=trip_month,
            month_name=month_name
        )

        results.append({
            "origin": origin["city"] if origin else start_destination,
            "origin_found_in_dataset": origin is not None,
            "destination": destination["city"],
            "country": destination["country"],
            "region": destination["region"],
            "trip_type": destination["trip_type"],
            "climate_tag": destination["climate_tag"],
            "score": score,
            "trip_length_nights": nights,
            "estimated_total_cost": total_cost,
            "estimated_flight_cost": estimated_flight_cost,
            "pricing": pricing,
            "estimated_nightly_cost": destination["estimated_nightly_cost"],
            "safety_score": int(destination["safety_score"]),
            "attraction_score": int(destination["attraction_score"]),
            "current_temperature": weather["temperature"],
            "current_weather_condition": weather["condition"],
            "trip_month": month_name,
            "seasonal_weather": seasonal_weather,
            "travel_advisory": advisory,
            "reasons": reasons
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]