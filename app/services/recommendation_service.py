import re
import os
import requests
from calendar import monthrange
from datetime import date, timedelta
from statistics import mean
from dotenv import load_dotenv
from app.services.location_service import (
    detect_requested_administrative_areas,
    discover_destination_candidates,
    get_candidate_locations,
    get_destination_administrative_area,
    get_or_discover_location,
    repair_missing_administrative_areas,
)
from app.services.advisory_service import find_advisory_by_country, calculate_advisory_penalty
from app.services.travel_logistics_service import get_trip_pricing
from app.services.region_service import backfill_missing_regions
from app.services.embedding_service import rank_destinations_by_embedding

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

# A destination with valid live flight data but no provider-supplied flight link
# remains eligible, but is strongly demoted below otherwise comparable options.
MISSING_FLIGHT_LINK_PENALTY = 100

TARGET_FINAL_RECOMMENDATIONS = 5
MAX_REPLENISH_ROUNDS = 3
REPLENISH_DISCOVERY_LIMIT = 6
LIVE_SHORTLIST_SIZE = 8



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
    """
    Returns a five-year historical monthly climate mean from Open-Meteo.

    The five most recent complete calendar years are used. For example, during
    2026 the calculation uses the same requested month from 2021 through 2025.
    This is climatological context for the travel period, not a future forecast.
    """
    if month is None or latitude is None or longitude is None:
        return None

    current_year = date.today().year
    years = list(range(current_year - 5, current_year))

    url = "https://archive-api.open-meteo.com/v1/archive"

    yearly_highs = []
    yearly_lows = []
    yearly_means = []
    yearly_precipitation = []

    for year in years:
        last_day = monthrange(year, month)[1]

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": f"{year}-{month:02d}-01",
            "end_date": f"{year}-{month:02d}-{last_day:02d}",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": "auto",
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue

        daily = data.get("daily") or {}
        max_temps = [
            value for value in daily.get("temperature_2m_max", [])
            if isinstance(value, (int, float))
        ]
        min_temps = [
            value for value in daily.get("temperature_2m_min", [])
            if isinstance(value, (int, float))
        ]
        precipitation = [
            value for value in daily.get("precipitation_sum", [])
            if isinstance(value, (int, float))
        ]

        if not max_temps or not min_temps:
            continue

        yearly_high = mean(max_temps)
        yearly_low = mean(min_temps)

        yearly_highs.append(yearly_high)
        yearly_lows.append(yearly_low)
        yearly_means.append((yearly_high + yearly_low) / 2)
        yearly_precipitation.append(sum(precipitation) if precipitation else 0.0)

    if not yearly_highs:
        return None

    years_used = years[:len(yearly_highs)]

    return {
        "average_high": round(mean(yearly_highs), 1),
        "average_low": round(mean(yearly_lows), 1),
        "average_temperature": round(mean(yearly_means), 1),
        # Kept for compatibility with the existing scoring function. This is
        # now the mean monthly precipitation across the historical years.
        "total_precipitation": round(mean(yearly_precipitation), 2),
        "average_monthly_precipitation": round(mean(yearly_precipitation), 2),
        "years_averaged": len(yearly_highs),
        "historical_years": years_used,
        "source": "Open-Meteo Archive",
        "weather_type": "five_year_historical_monthly_mean",
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

    elif "cold" in prompt or "snow" in prompt or "ski" in prompt:
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

    elif "cold" in prompt or "snow" in prompt or "ski" in prompt:
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



def extract_budget_from_prompt(prompt):
    """
    Extracts a budget from natural language.

    Supported examples:
    - "$1500"
    - "$1,500"
    - "1500 dollars"
    - "budget of 3000"
    """
    prompt_lower = prompt.lower()

    patterns = [
        r"\$\s*([\d,]+(?:\.\d{1,2})?)",
        r"(?:budget(?:\s+of)?|within|under|up to|max(?:imum)?)\s*\$?\s*([\d,]+(?:\.\d{1,2})?)",
        r"([\d,]+(?:\.\d{1,2})?)\s*(?:dollars|usd)",
    ]

    for pattern in patterns:
        match = re.search(pattern, prompt_lower)

        if match:
            return float(match.group(1).replace(",", ""))

    return None


def resolve_budget(prompt, budget=None, default_budget=2500):
    """
    Resolves budget with natural-language intent taking precedence.

    If the traveler explicitly writes a budget in the prompt, that value wins.
    Otherwise an explicitly supplied UI/API budget is used, followed by the
    application default.
    """
    prompt_budget = extract_budget_from_prompt(prompt)

    if prompt_budget is not None and prompt_budget > 0:
        return float(prompt_budget)

    if budget is not None and budget > 0:
        return float(budget)

    return float(default_budget)

def extract_trip_length(prompt):
    """
    Extracts trip duration from common natural-language expressions.

    Supported examples:
    - "5 days"
    - "5 nights"
    - "five days"
    - "five nights"
    - "1 week"
    - "2 weeks"
    - "one week"
    - "two weeks"
    - "about a week"
    - "around two weeks"
    - "five-night"
    - "2-week"

    Week-based durations are converted to 7 nights per week.
    Returns the existing 3-night default when no supported duration
    expression is found.
    """
    prompt_lower = prompt.lower()

    number_words = {
        "a": 1,
        "an": 1,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
    }

    # Match numeric durations first:
    # "5 days", "7 nights", "1 week", "2 weeks", "5-day"
    numeric_match = re.search(
        r"\b(\d+)[\s-]*(day|days|night|nights|week|weeks)\b",
        prompt_lower,
    )

    if numeric_match:
        amount = int(numeric_match.group(1))
        unit = numeric_match.group(2)

        if unit in {"week", "weeks"}:
            return amount * 7

        return amount

    # Match written-number durations:
    # "five days", "one week", "about a week", "five-night", etc.
    word_pattern = "|".join(
        sorted(number_words.keys(), key=len, reverse=True)
    )

    word_match = re.search(
        rf"\b({word_pattern})[\s-]*(day|days|night|nights|week|weeks)\b",
        prompt_lower,
    )

    if word_match:
        amount = number_words[word_match.group(1)]
        unit = word_match.group(2)

        if unit in {"week", "weeks"}:
            return amount * 7

        return amount

    return 3


def extract_trip_month(prompt):
    """
    Extracts an explicit month or maps a season to a representative month.

    Season mapping uses Northern Hemisphere travel conventions:
    winter -> January, spring -> April, summer -> July, fall/autumn -> October.
    """
    prompt_lower = prompt.lower()

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
        "december": 12,
    }

    for month_name, month_number in months.items():
        if month_name in prompt_lower:
            return month_number, month_name

    seasons = {
        "winter": (1, "january"),
        "spring": (4, "april"),
        "summer": (7, "july"),
        "fall": (10, "october"),
        "autumn": (10, "october"),
    }

    for season_name, season_month in seasons.items():
        if season_name in prompt_lower:
            return season_month

    return None, None


def generate_trip_dates(trip_month, nights):
    """
    Generates concrete outbound and return dates for live flight searches.

    - Uses the 15th of the requested month.
    - Uses next year when that date has already passed.
    - Defaults to 30 days from today when no month is requested.
    """
    today = date.today()

    if trip_month is None:
        outbound = today + timedelta(days=30)
    else:
        outbound = date(today.year, trip_month, 15)

        if outbound <= today:
            outbound = date(today.year + 1, trip_month, 15)

    return_date = outbound + timedelta(days=nights)

    return outbound.isoformat(), return_date.isoformat()


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


def get_destination_trip_types(destination):
    """
    Returns normalized trip types for both the new three-column CSV schema
    and older dynamically discovered records that may still use trip_type.
    """
    trip_types = []

    for field in ("trip_type_1", "trip_type_2", "trip_type_3", "trip_type"):
        value = str(destination.get(field, "")).strip().lower()

        if value and value not in {"unknown", "none", "nan"} and value not in trip_types:
            trip_types.append(value)

    return trip_types


def calculate_score(
    origin,
    start_destination,
    destination,
    prompt,
    budget,
    nights,
    trip_month,
    month_name,
    outbound_date,
    return_date,
):
    prompt = prompt.lower()
    score = 0
    reasons = []

    estimated_flight_cost = estimate_flight_cost(start_destination, destination)

    pricing = get_trip_pricing(
        origin=origin,
        destination=destination,
        nights=nights,
        fallback_flight_cost=estimated_flight_cost,
        outbound_date=outbound_date,
        return_date=return_date,
        budget=budget,
    )

    total_cost = pricing["estimated_total_cost"]

    destination_trip_types = get_destination_trip_types(destination)
    matched_trip_types = [
        trip_type for trip_type in destination_trip_types
        if trip_type in prompt
    ]

    if matched_trip_types:
        score += 30
        reasons.append(
            f"Matches trip type: {', '.join(matched_trip_types)}"
        )

    # Future-trip recommendations use climate evidence for the travel period,
    # not today's weather at the destination.
    weather = {
        "temperature": None,
        "condition": None,
    }

    seasonal_weather = get_historical_weather(
        latitude=destination["latitude"],
        longitude=destination["longitude"],
        month=trip_month,
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


def detect_requested_trip_types(prompt):
    """
    Maps prompt wording and common variants to supported trip types.
    """
    prompt_lower = prompt.lower()

    keyword_groups = {
        "beach": [
            "beach", "beaches", "coast", "coastal", "ocean",
            "island", "tropical", "seaside",
        ],
        "culture": [
            "culture", "cultural", "history", "historic", "historical",
            "museum", "museums", "architecture", "art", "heritage",
        ],
        "city": [
            "city", "cities", "urban", "nightlife", "shopping",
            "walkable", "restaurants",
        ],
        "nature": [
            "nature", "mountain", "mountains", "hiking", "outdoors",
            "forest", "wildlife", "national park", "scenery",
        ],
    }

    return {
        trip_type
        for trip_type, keywords in keyword_groups.items()
        if any(keyword in prompt_lower for keyword in keywords)
    }



def detect_requested_regions(prompt):
    """
    Maps common region wording and adjective forms to CSV region values.
    """
    prompt_lower = prompt.lower()

    region_keywords = {
        "Asia": ["asia", "asian"],
        "Europe": ["europe", "european"],
        "Africa": ["africa", "african"],
        "North America": ["north america", "north american"],
        "South America": ["south america", "south american", "latin america"],
        "Caribbean": ["caribbean"],
        "Oceania": ["oceania", "australia", "new zealand", "pacific"],
    }

    return {
        region
        for region, keywords in region_keywords.items()
        if any(keyword in prompt_lower for keyword in keywords)
    }


def detect_requested_subregions(prompt):
    """
    Detects smaller geographic areas such as East Africa or Southeast Asia.

    A subregion is more specific than a broad region. For example, a request
    for "East Africa" should not search every destination in Africa.
    """
    prompt_lower = prompt.lower()

    subregion_keywords = {
        "North Africa": ["north africa", "northern africa"],
        "West Africa": ["west africa", "western africa"],
        "Central Africa": ["central africa", "middle africa"],
        "East Africa": ["east africa", "eastern africa"],
        "Southern Africa": ["southern africa"],
        "East Asia": ["east asia", "eastern asia"],
        "Southeast Asia": [
            "southeast asia",
            "south east asia",
            "southeastern asia",
            "south-eastern asia",
        ],
        "South Asia": ["south asia", "southern asia"],
        "Central Asia": ["central asia"],
        "West Asia": ["west asia", "western asia", "middle east"],
        "Northern Europe": ["northern europe", "north europe"],
        "Western Europe": ["western europe", "west europe"],
        "Southern Europe": ["southern europe", "south europe"],
        "Eastern Europe": ["eastern europe", "east europe"],
        "Central America": ["central america"],
        "Northern America": ["northern america"],
        "Andean Region": ["andean region", "andes", "andean"],
        "Southern Cone": ["southern cone"],
        "Northern South America": ["northern south america"],
        "Australia and New Zealand": [
            "australia and new zealand",
            "australasia",
        ],
        "Melanesia": ["melanesia"],
        "Micronesia": ["micronesia"],
        "Polynesia": ["polynesia"],
    }

    return {
        subregion
        for subregion, keywords in subregion_keywords.items()
        if any(keyword in prompt_lower for keyword in keywords)
    }


COUNTRY_SUBREGION_MAP = {
    # Africa
    "Algeria": "North Africa",
    "Egypt": "North Africa",
    "Libya": "North Africa",
    "Morocco": "North Africa",
    "Sudan": "North Africa",
    "Tunisia": "North Africa",
    "Benin": "West Africa",
    "Burkina Faso": "West Africa",
    "Cape Verde": "West Africa",
    "Côte d'Ivoire": "West Africa",
    "Ivory Coast": "West Africa",
    "Gambia": "West Africa",
    "Ghana": "West Africa",
    "Guinea": "West Africa",
    "Guinea-Bissau": "West Africa",
    "Liberia": "West Africa",
    "Mali": "West Africa",
    "Mauritania": "West Africa",
    "Niger": "West Africa",
    "Nigeria": "West Africa",
    "Senegal": "West Africa",
    "Sierra Leone": "West Africa",
    "Togo": "West Africa",
    "Burundi": "East Africa",
    "Comoros": "East Africa",
    "Djibouti": "East Africa",
    "Eritrea": "East Africa",
    "Ethiopia": "East Africa",
    "Kenya": "East Africa",
    "Madagascar": "East Africa",
    "Malawi": "East Africa",
    "Mauritius": "East Africa",
    "Mozambique": "East Africa",
    "Rwanda": "East Africa",
    "Seychelles": "East Africa",
    "Somalia": "East Africa",
    "South Sudan": "East Africa",
    "Tanzania": "East Africa",
    "Uganda": "East Africa",
    "Zambia": "East Africa",
    "Zimbabwe": "East Africa",
    "Angola": "Central Africa",
    "Cameroon": "Central Africa",
    "Central African Republic": "Central Africa",
    "Chad": "Central Africa",
    "Democratic Republic of the Congo": "Central Africa",
    "DR Congo": "Central Africa",
    "Republic of the Congo": "Central Africa",
    "Congo": "Central Africa",
    "Equatorial Guinea": "Central Africa",
    "Gabon": "Central Africa",
    "São Tomé and Príncipe": "Central Africa",
    "Botswana": "Southern Africa",
    "Eswatini": "Southern Africa",
    "Lesotho": "Southern Africa",
    "Namibia": "Southern Africa",
    "South Africa": "Southern Africa",

    # Asia
    "China": "East Asia",
    "Hong Kong": "East Asia",
    "Japan": "East Asia",
    "Macao": "East Asia",
    "Macau": "East Asia",
    "Mongolia": "East Asia",
    "North Korea": "East Asia",
    "South Korea": "East Asia",
    "Taiwan": "East Asia",
    "Brunei": "Southeast Asia",
    "Cambodia": "Southeast Asia",
    "Indonesia": "Southeast Asia",
    "Laos": "Southeast Asia",
    "Malaysia": "Southeast Asia",
    "Myanmar": "Southeast Asia",
    "Philippines": "Southeast Asia",
    "Singapore": "Southeast Asia",
    "Thailand": "Southeast Asia",
    "Timor-Leste": "Southeast Asia",
    "Vietnam": "Southeast Asia",
    "Afghanistan": "South Asia",
    "Bangladesh": "South Asia",
    "Bhutan": "South Asia",
    "India": "South Asia",
    "Maldives": "South Asia",
    "Nepal": "South Asia",
    "Pakistan": "South Asia",
    "Sri Lanka": "South Asia",
    "Kazakhstan": "Central Asia",
    "Kyrgyzstan": "Central Asia",
    "Tajikistan": "Central Asia",
    "Turkmenistan": "Central Asia",
    "Uzbekistan": "Central Asia",
    "Armenia": "West Asia",
    "Azerbaijan": "West Asia",
    "Bahrain": "West Asia",
    "Cyprus": "West Asia",
    "Georgia": "West Asia",
    "Iraq": "West Asia",
    "Israel": "West Asia",
    "Jordan": "West Asia",
    "Kuwait": "West Asia",
    "Lebanon": "West Asia",
    "Oman": "West Asia",
    "Palestine": "West Asia",
    "Qatar": "West Asia",
    "Saudi Arabia": "West Asia",
    "Turkey": "West Asia",
    "Türkiye": "West Asia",
    "United Arab Emirates": "West Asia",
    "Yemen": "West Asia",

    # Europe
    "Denmark": "Northern Europe",
    "Estonia": "Northern Europe",
    "Finland": "Northern Europe",
    "Iceland": "Northern Europe",
    "Ireland": "Northern Europe",
    "Latvia": "Northern Europe",
    "Lithuania": "Northern Europe",
    "Norway": "Northern Europe",
    "Sweden": "Northern Europe",
    "United Kingdom": "Northern Europe",
    "Austria": "Western Europe",
    "Belgium": "Western Europe",
    "France": "Western Europe",
    "Germany": "Western Europe",
    "Liechtenstein": "Western Europe",
    "Luxembourg": "Western Europe",
    "Monaco": "Western Europe",
    "Netherlands": "Western Europe",
    "Switzerland": "Western Europe",
    "Albania": "Southern Europe",
    "Andorra": "Southern Europe",
    "Bosnia and Herzegovina": "Southern Europe",
    "Croatia": "Southern Europe",
    "Greece": "Southern Europe",
    "Italy": "Southern Europe",
    "Malta": "Southern Europe",
    "Montenegro": "Southern Europe",
    "North Macedonia": "Southern Europe",
    "Portugal": "Southern Europe",
    "San Marino": "Southern Europe",
    "Serbia": "Southern Europe",
    "Slovenia": "Southern Europe",
    "Spain": "Southern Europe",
    "Vatican City": "Southern Europe",
    "Belarus": "Eastern Europe",
    "Bulgaria": "Eastern Europe",
    "Czechia": "Eastern Europe",
    "Czech Republic": "Eastern Europe",
    "Hungary": "Eastern Europe",
    "Moldova": "Eastern Europe",
    "Poland": "Eastern Europe",
    "Romania": "Eastern Europe",
    "Russia": "Eastern Europe",
    "Slovakia": "Eastern Europe",
    "Ukraine": "Eastern Europe",

    # Americas
    "Belize": "Central America",
    "Costa Rica": "Central America",
    "El Salvador": "Central America",
    "Guatemala": "Central America",
    "Honduras": "Central America",
    "Nicaragua": "Central America",
    "Panama": "Central America",
    "Canada": "Northern America",
    "United States": "Northern America",
    "USA": "Northern America",
    "Mexico": "Northern America",
    "Bolivia": "Andean Region",
    "Colombia": "Andean Region",
    "Ecuador": "Andean Region",
    "Peru": "Andean Region",
    "Argentina": "Southern Cone",
    "Chile": "Southern Cone",
    "Paraguay": "Southern Cone",
    "Uruguay": "Southern Cone",
    "Guyana": "Northern South America",
    "Suriname": "Northern South America",
    "Venezuela": "Northern South America",

    # Oceania
    "Australia": "Australia and New Zealand",
    "New Zealand": "Australia and New Zealand",
    "Fiji": "Melanesia",
    "Papua New Guinea": "Melanesia",
    "Solomon Islands": "Melanesia",
    "Vanuatu": "Melanesia",
    "Kiribati": "Micronesia",
    "Marshall Islands": "Micronesia",
    "Micronesia": "Micronesia",
    "Nauru": "Micronesia",
    "Palau": "Micronesia",
    "Samoa": "Polynesia",
    "Tonga": "Polynesia",
    "Tuvalu": "Polynesia",
}


def get_destination_subregion(destination):
    """
    Returns a saved subregion when present, otherwise infers one from country.

    This lets GreenBookAI support subregion filtering immediately, even before
    every row in travel_locations.csv has a subregion value.
    """
    saved_subregion = str(destination.get("subregion", "")).strip()

    if saved_subregion and saved_subregion.lower() not in {"unknown", "none", "nan"}:
        return saved_subregion

    country = str(destination.get("country", "")).strip()
    return COUNTRY_SUBREGION_MAP.get(country, "")


def detect_requested_countries(prompt, destinations):
    """
    Detects exact country names already represented in the candidate inventory.

    Country matching has priority over broad-region matching, so "South Africa"
    is treated as a country instead of merely as a request for Africa.
    """
    prompt_lower = prompt.lower()
    countries = {
        str(destination.get("country", "")).strip()
        for destination in destinations
        if str(destination.get("country", "")).strip()
    }

    requested = set()

    for country in sorted(countries, key=len, reverse=True):
        pattern = rf"(?<!\w){re.escape(country.lower())}(?!\w)"

        if re.search(pattern, prompt_lower):
            requested.add(country)

    return requested

def calculate_preliminary_score(
    start_destination,
    destination,
    prompt,
    budget,
    nights,
    requested_trip_types,
    requested_regions,
    requested_subregions,
    requested_administrative_areas,
):
    """
    Fast local score used only to choose which destinations receive live API calls.

    No weather, advisory, flight, or hotel API is called here.
    """
    score = 0.0
    prompt_lower = prompt.lower()
    destination_trip_types = set(get_destination_trip_types(destination))
    climate_tag = str(destination.get("climate_tag", "unknown")).lower()

    if requested_trip_types:
        if destination_trip_types.intersection(requested_trip_types):
            score += 40
        else:
            score -= 40

    destination_region = str(destination.get("region", "")).strip()
    destination_subregion = get_destination_subregion(destination)
    destination_administrative_area = get_destination_administrative_area(
        destination
    )

    if requested_administrative_areas:
        if destination_administrative_area in requested_administrative_areas:
            score += 55
        else:
            score -= 55
    elif requested_subregions:
        if destination_subregion in requested_subregions:
            score += 45
        else:
            score -= 45
    elif requested_regions:
        if destination_region in requested_regions:
            score += 35
        else:
            score -= 35

    if any(word in prompt_lower for word in ["warm", "hot", "tropical"]):
        score += 20 if climate_tag == "warm" else -5
    elif any(word in prompt_lower for word in ["mild", "comfortable", "cool"]):
        score += 20 if climate_tag == "mild" else 0
    elif any(word in prompt_lower for word in ["cold", "snow", "ski"]):
        score += 20 if climate_tag == "cold" else -5

    estimated_total = calculate_total_cost(
        start_destination=start_destination,
        destination=destination,
        nights=nights,
    )

    if estimated_total <= budget:
        score += 25
    elif estimated_total <= budget * 1.3:
        score += 5
    else:
        score -= 30

    score += float(destination.get("safety_score", 5))
    score += float(destination.get("attraction_score", 5))

    if "safety" in prompt_lower or "safe" in prompt_lower or "low crime" in prompt_lower:
        score += float(destination.get("safety_score", 5)) * 2

    return score

def _notify_progress(progress_callback, percent, stage):
    """Safely reports backend progress without coupling the recommender to the UI."""
    if not callable(progress_callback):
        return

    try:
        progress_callback(int(percent), str(stage))
    except Exception:
        pass


def _destination_identity(destination):
    return (
        str(destination.get("city", "")).strip().lower(),
        str(destination.get("country", "")).strip().lower(),
    )


def _is_viable_final_result(pricing):
    """
    Final recommendations require usable live flight and Best Value Stay links.
    Optional quality/resort alternatives do not determine destination viability.
    """
    flight = pricing.get("flight") or {}
    lodging = pricing.get("lodging") or {}
    selected = lodging.get("selected_property") or {}

    flight_viable = (
        not pricing.get("flight_fallback_used")
        and flight.get("source") == "SerpAPI"
        and flight.get("total_price") is not None
        and bool(flight.get("airlines"))
        and bool(flight.get("search_url"))
    )

    lodging_viable = (
        not pricing.get("lodging_fallback_used")
        and lodging.get("source") == "SerpAPI"
        and bool(selected.get("name"))
        and bool(selected.get("display_link"))
        and lodging.get("lodging_total") is not None
    )

    return flight_viable and lodging_viable


def _eligible_destinations_for_prompt(
    all_destinations,
    origin,
    prompt,
    requested_trip_types,
    requested_regions,
    requested_subregions,
    requested_administrative_areas,
):
    requested_countries = detect_requested_countries(
        prompt=prompt,
        destinations=all_destinations,
    )

    eligible_destinations = []

    for destination in all_destinations:
        city = str(destination.get("city", "")).strip()

        if not city:
            continue

        if origin and city.lower() == str(origin.get("city", "")).strip().lower():
            continue

        destination_country = str(destination.get("country", "")).strip()
        destination_region = str(destination.get("region", "")).strip()
        destination_subregion = get_destination_subregion(destination)
        destination_administrative_area = get_destination_administrative_area(
            destination
        )
        destination_trip_types = set(get_destination_trip_types(destination))

        if requested_administrative_areas:
            if destination_administrative_area not in requested_administrative_areas:
                continue
        elif requested_countries:
            if destination_country not in requested_countries:
                continue
        elif requested_subregions:
            if destination_subregion not in requested_subregions:
                continue
        elif requested_regions:
            if destination_region not in requested_regions:
                continue

        if requested_trip_types:
            if not destination_trip_types.intersection(requested_trip_types):
                continue

        eligible_destinations.append(destination)

    return eligible_destinations


def get_recommendations(
    start_destination,
    prompt,
    budget=None,
    progress_callback=None,
):
    """
    Builds up to five viable ranked recommendations.

    If live flight/hotel validation leaves fewer than five viable choices,
    GreenBookAI discovers additional prompt-relevant destinations and retries,
    subject to a strict retry cap.
    """
    _notify_progress(progress_callback, 5, "Understanding your trip request...")

    budget = resolve_budget(prompt, budget)
    nights = extract_trip_length(prompt)
    trip_month, month_name = extract_trip_month(prompt)
    outbound_date, return_date = generate_trip_dates(trip_month, nights)

    if trip_month is None:
        generated_month = date.fromisoformat(outbound_date).month
        trip_month = generated_month
        month_name = date(2000, generated_month, 1).strftime("%B").lower()

    _notify_progress(progress_callback, 12, "Checking destination inventory...")

    origin = get_or_discover_location(start_destination)

    backfill_missing_regions()
    repair_missing_administrative_areas()
    discover_destination_candidates(prompt, limit=1)

    requested_trip_types = detect_requested_trip_types(prompt)
    requested_regions = detect_requested_regions(prompt)
    requested_subregions = detect_requested_subregions(prompt)
    requested_administrative_areas = detect_requested_administrative_areas(prompt)

    results = []
    evaluated_destinations = set()

    for discovery_round in range(MAX_REPLENISH_ROUNDS + 1):
        if discovery_round > 0:
            needed = TARGET_FINAL_RECOMMENDATIONS - len(results)
            if needed <= 0:
                break

            _notify_progress(
                progress_callback,
                min(84 + discovery_round * 3, 92),
                (
                    "Finding additional viable destinations "
                    f"(round {discovery_round}/{MAX_REPLENISH_ROUNDS})..."
                ),
            )

            newly_discovered = discover_destination_candidates(
                prompt,
                limit=min(
                    REPLENISH_DISCOVERY_LIMIT,
                    max(needed + 1, 2),
                ),
            )

            if not newly_discovered:
                break

        all_destinations = get_candidate_locations()

        eligible_destinations = _eligible_destinations_for_prompt(
            all_destinations=all_destinations,
            origin=origin,
            prompt=prompt,
            requested_trip_types=requested_trip_types,
            requested_regions=requested_regions,
            requested_subregions=requested_subregions,
            requested_administrative_areas=requested_administrative_areas,
        )

        unevaluated = [
            destination
            for destination in eligible_destinations
            if _destination_identity(destination) not in evaluated_destinations
        ]

        if not unevaluated:
            continue

        _notify_progress(
            progress_callback,
            25 if discovery_round == 0 else min(86 + discovery_round * 2, 94),
            "Ranking candidate destinations...",
        )

        embedding_ranked = rank_destinations_by_embedding(
            prompt=prompt,
            destinations=unevaluated,
        )

        preliminary_candidates = []

        for embedding_result in embedding_ranked:
            destination = embedding_result["destination"]
            embedding_similarity = embedding_result["embedding_similarity"]

            local_score = calculate_preliminary_score(
                start_destination=start_destination,
                destination=destination,
                prompt=prompt,
                budget=budget,
                nights=nights,
                requested_trip_types=requested_trip_types,
                requested_regions=requested_regions,
                requested_subregions=requested_subregions,
                requested_administrative_areas=requested_administrative_areas,
            )

            embedding_points = max(embedding_similarity, 0.0) * 60

            preliminary_candidates.append({
                "destination": destination,
                "local_score": local_score,
                "embedding_similarity": embedding_similarity,
                "embedding_available": embedding_result["embedding_available"],
                "combined_score": local_score + embedding_points,
            })

        shortlisted_candidates = sorted(
            preliminary_candidates,
            key=lambda item: item["combined_score"],
            reverse=True,
        )[:LIVE_SHORTLIST_SIZE]

        shortlist_metadata = {
            _destination_identity(item["destination"]): item
            for item in shortlisted_candidates
        }

        candidate_count = max(len(shortlisted_candidates), 1)

        for index, shortlist_item in enumerate(shortlisted_candidates, start=1):
            if len(results) >= TARGET_FINAL_RECOMMENDATIONS:
                break

            destination = shortlist_item["destination"]
            identity = _destination_identity(destination)
            evaluated_destinations.add(identity)

            base_percent = 35 if discovery_round == 0 else 86
            span = 45 if discovery_round == 0 else 8
            candidate_percent = min(
                base_percent + int(span * (index - 1) / candidate_count),
                94,
            )

            _notify_progress(
                progress_callback,
                candidate_percent,
                f"Checking live travel data for {destination.get('city', 'destination')}...",
            )

            (
                score,
                reasons,
                total_cost,
                estimated_flight_cost,
                weather,
                seasonal_weather,
                advisory,
                pricing,
            ) = calculate_score(
                origin=origin,
                start_destination=start_destination,
                destination=destination,
                prompt=prompt,
                budget=budget,
                nights=nights,
                trip_month=trip_month,
                month_name=month_name,
                outbound_date=outbound_date,
                return_date=return_date,
            )

            flight_result = pricing.get("flight") or {}

            if not flight_result.get("search_url"):
                score -= MISSING_FLIGHT_LINK_PENALTY
                reasons.append(
                    "Flight link unavailable; "
                    f"{MISSING_FLIGHT_LINK_PENALTY}-point ranking penalty applied"
                )

            if not _is_viable_final_result(pricing):
                continue

            metadata = shortlist_metadata[identity]

            results.append({
                "origin": origin["city"] if origin else start_destination,
                "origin_found_in_dataset": origin is not None,
                "destination": destination["city"],
                "country": destination["country"],
                "region": destination["region"],
                "subregion": get_destination_subregion(destination),
                "administrative_area": get_destination_administrative_area(
                    destination
                ),
                "trip_type": (
                    get_destination_trip_types(destination)[0]
                    if get_destination_trip_types(destination)
                    else "unknown"
                ),
                "trip_types": get_destination_trip_types(destination),
                "destination_description": destination.get(
                    "destination_description",
                    "",
                ),
                "climate_tag": destination["climate_tag"],
                "score": score,
                "preliminary_score": round(metadata["combined_score"], 2),
                "embedding_similarity": round(
                    metadata["embedding_similarity"],
                    4,
                ),
                "embedding_available": metadata["embedding_available"],
                "trip_length_nights": nights,
                "outbound_date": outbound_date,
                "return_date": return_date,
                "estimated_total_cost": total_cost,
                "estimated_flight_cost": estimated_flight_cost,
                "pricing": pricing,
                "estimated_nightly_cost": destination["estimated_nightly_cost"],
                "safety_score": int(destination["safety_score"]),
                "attraction_score": int(destination["attraction_score"]),
                "current_temperature": None,
                "current_weather_condition": None,
                "trip_month": month_name,
                "seasonal_weather": seasonal_weather,
                "travel_advisory": advisory,
                "reasons": reasons,
            })

        if len(results) >= TARGET_FINAL_RECOMMENDATIONS:
            break

    _notify_progress(
        progress_callback,
        94,
        (
            f"Finalizing {len(results)} viable recommendation"
            f"{'s' if len(results) != 1 else ''}..."
        ),
    )

    return sorted(
        results,
        key=lambda item: item["score"],
        reverse=True,
    )[:TARGET_FINAL_RECOMMENDATIONS]