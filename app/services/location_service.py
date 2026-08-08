import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from app.services.region_service import resolve_region

try:
    # Use region_service when it exposes subregion resolution.
    from app.services.region_service import resolve_subregion  # type: ignore
except ImportError:
    resolve_subregion = None


load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")

TRAVEL_LOCATIONS_FILE = Path("data/travel_locations.csv")
GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

# Discovery behavior. The service becomes more aggressive while the inventory
# is still small, but caps each run to avoid excessive API calls.
TARGET_INVENTORY_SIZE = 125
DEFAULT_DISCOVERY_LIMIT = 1
MAX_DISCOVERY_LIMIT = 8
MIN_ADMINISTRATIVE_AREA_CANDIDATES = 5

CSV_COLUMNS = [
    "city",
    "country",
    "region",
    "subregion",
    "administrative_area",
    "trip_type_1",
    "trip_type_2",
    "trip_type_3",
    "climate_tag",
    "average_humidity",
    "estimated_nightly_cost",
    "safety_score",
    "attraction_score",
    "latitude",
    "longitude",
    "airport_code",
    "destination_description",
]

# Candidate seeds let GreenBookAI expand its destination inventory automatically.
# Seeds are intentionally broader than the original list so the CSV can grow well
# beyond the initial 50 destinations. A seed may appear in multiple categories.
DESTINATION_DISCOVERY_SEEDS = {
    "beach": [
        "Maui, Hawaii",
        "Kauai, Hawaii",
        "Miami, Florida",
        "Key West, Florida",
        "Fort Lauderdale, Florida",
        "Clearwater, Florida",
        "Naples, Florida",
        "Saint Petersburg, Florida",
        "Destin, Florida",
        "Virginia Beach, Virginia",
        "Hilton Head Island, South Carolina",
        "Outer Banks, North Carolina",
        "Puerto Vallarta, Mexico",
        "Playa del Carmen, Mexico",
        "Mazatlan, Mexico",
        "La Paz, Mexico",
        "Belize City, Belize",
        "Ambergris Caye, Belize",
        "Roatan, Honduras",
        "Bocas del Toro, Panama",
        "Manuel Antonio, Costa Rica",
        "Tamarindo, Costa Rica",
        "Santa Marta, Colombia",
        "San Andres, Colombia",
        "Recife, Brazil",
        "Fortaleza, Brazil",
        "Florianopolis, Brazil",
        "Buzios, Brazil",
        "Punta del Este, Uruguay",
        "Lima, Peru",
        "Vina del Mar, Chile",
        "Albufeira, Portugal",
        "Cascais, Portugal",
        "Malaga, Spain",
        "Palma de Mallorca, Spain",
        "Ibiza, Spain",
        "Valencia, Spain",
        "Marseille, France",
        "Cannes, France",
        "Amalfi, Italy",
        "Naples, Italy",
        "Palermo, Italy",
        "Cagliari, Italy",
        "Mykonos, Greece",
        "Crete, Greece",
        "Rhodes, Greece",
        "Dubrovnik, Croatia",
        "Kotor, Montenegro",
        "Sarande, Albania",
        "Antalya, Turkey",
        "Bodrum, Turkey",
        "Larnaca, Cyprus",
        "Paphos, Cyprus",
        "Sharm El Sheikh, Egypt",
        "Hurghada, Egypt",
        "Essaouira, Morocco",
        "Agadir, Morocco",
        "Djerba, Tunisia",
        "Saly, Senegal",
        "Banjul, Gambia",
        "Freetown, Sierra Leone",
        "Monrovia, Liberia",
        "Abidjan, Ivory Coast",
        "Lome, Togo",
        "Cotonou, Benin",
        "Elmina, Ghana",
        "Mombasa, Kenya",
        "Diani Beach, Kenya",
        "Dar es Salaam, Tanzania",
        "Nosy Be, Madagascar",
        "Mauritius",
        "Victoria, Seychelles",
        "Maputo, Mozambique",
        "Durban, South Africa",
        "Walvis Bay, Namibia",
        "Goa, India",
        "Kochi, India",
        "Galle, Sri Lanka",
        "Maldives",
        "Langkawi, Malaysia",
        "Penang, Malaysia",
        "Sihanoukville, Cambodia",
        "Nha Trang, Vietnam",
        "Phu Quoc, Vietnam",
        "Boracay, Philippines",
        "Cebu City, Philippines",
        "Palawan, Philippines",
        "Okinawa, Japan",
        "Jeju City, South Korea",
        "Sanya, China",
        "Kota Kinabalu, Malaysia",
        "Lombok, Indonesia",
        "Fiji",
        "Apia, Samoa",
        "Papeete, French Polynesia",
        "Noumea, New Caledonia",
        "Auckland, New Zealand",
        "Byron Bay, Australia",
        "Cairns, Australia",
        "Perth, Australia",
    ],
    "city": [
        "New York City, New York",
        "Chicago, Illinois",
        "Los Angeles, California",
        "San Francisco, California",
        "Seattle, Washington",
        "Washington, District of Columbia",
        "Philadelphia, Pennsylvania",
        "Atlanta, Georgia",
        "Houston, Texas",
        "Dallas, Texas",
        "Austin, Texas",
        "Denver, Colorado",
        "Las Vegas, Nevada",
        "Toronto, Canada",
        "Montreal, Canada",
        "Vancouver, Canada",
        "Mexico City, Mexico",
        "Panama City, Panama",
        "San Jose, Costa Rica",
        "Guatemala City, Guatemala",
        "London, United Kingdom",
        "Paris, France",
        "Madrid, Spain",
        "Amsterdam, Netherlands",
        "Berlin, Germany",
        "Rome, Italy",
        "Milan, Italy",
        "Prague, Czechia",
        "Vienna, Austria",
        "Budapest, Hungary",
        "Warsaw, Poland",
        "Copenhagen, Denmark",
        "Stockholm, Sweden",
        "Oslo, Norway",
        "Helsinki, Finland",
        "Dublin, Ireland",
        "Brussels, Belgium",
        "Zurich, Switzerland",
        "Istanbul, Turkey",
        "Dubai, United Arab Emirates",
        "Abu Dhabi, United Arab Emirates",
        "Doha, Qatar",
        "Tel Aviv, Israel",
        "Amman, Jordan",
        "Beirut, Lebanon",
        "Tokyo, Japan",
        "Osaka, Japan",
        "Seoul, South Korea",
        "Beijing, China",
        "Shanghai, China",
        "Hong Kong",
        "Taipei, Taiwan",
        "Singapore",
        "Kuala Lumpur, Malaysia",
        "Manila, Philippines",
        "Ho Chi Minh City, Vietnam",
        "Hanoi, Vietnam",
        "Jakarta, Indonesia",
        "Mumbai, India",
        "Delhi, India",
        "Bengaluru, India",
        "Buenos Aires, Argentina",
        "Sao Paulo, Brazil",
        "Santiago, Chile",
        "Montevideo, Uruguay",
        "Bogota, Colombia",
        "Quito, Ecuador",
        "Lima, Peru",
        "Johannesburg, South Africa",
        "Nairobi, Kenya",
        "Addis Ababa, Ethiopia",
        "Kigali, Rwanda",
        "Lusaka, Zambia",
        "Harare, Zimbabwe",
        "Melbourne, Australia",
        "Sydney, Australia",
        "Brisbane, Australia",
        "Wellington, New Zealand",
    ],
    "culture": [
        "Santa Fe, New Mexico",
        "Memphis, Tennessee",
        "Nashville, Tennessee",
        "Baltimore, Maryland",
        "Detroit, Michigan",
        "Quebec City, Canada",
        "Merida, Mexico",
        "Puebla, Mexico",
        "Guanajuato, Mexico",
        "Antigua Guatemala, Guatemala",
        "Leon, Nicaragua",
        "Granada, Nicaragua",
        "Havana, Cuba",
        "Santo Domingo, Dominican Republic",
        "San Salvador, El Salvador",
        "Cusco, Peru",
        "Arequipa, Peru",
        "Cartagena, Colombia",
        "Medellin, Colombia",
        "Salvador, Brazil",
        "Buenos Aires, Argentina",
        "Valparaiso, Chile",
        "Seville, Spain",
        "Granada, Spain",
        "Bilbao, Spain",
        "Porto, Portugal",
        "Florence, Italy",
        "Bologna, Italy",
        "Venice, Italy",
        "Naples, Italy",
        "Athens, Greece",
        "Thessaloniki, Greece",
        "Edinburgh, United Kingdom",
        "Glasgow, United Kingdom",
        "Krakow, Poland",
        "Tallinn, Estonia",
        "Riga, Latvia",
        "Vilnius, Lithuania",
        "Sarajevo, Bosnia and Herzegovina",
        "Belgrade, Serbia",
        "Tbilisi, Georgia",
        "Yerevan, Armenia",
        "Baku, Azerbaijan",
        "Marrakesh, Morocco",
        "Fez, Morocco",
        "Tunis, Tunisia",
        "Cairo, Egypt",
        "Luxor, Egypt",
        "Alexandria, Egypt",
        "Accra, Ghana",
        "Kumasi, Ghana",
        "Dakar, Senegal",
        "Lagos, Nigeria",
        "Abuja, Nigeria",
        "Kigali, Rwanda",
        "Nairobi, Kenya",
        "Addis Ababa, Ethiopia",
        "Stone Town, Tanzania",
        "Kyoto, Japan",
        "Nara, Japan",
        "Kanazawa, Japan",
        "Jaipur, India",
        "Varanasi, India",
        "Udaipur, India",
        "Kathmandu, Nepal",
        "Bhaktapur, Nepal",
        "Luang Prabang, Laos",
        "Hoi An, Vietnam",
        "Siem Reap, Cambodia",
        "Chiang Mai, Thailand",
        "George Town, Malaysia",
        "Yogyakarta, Indonesia",
        "Melaka, Malaysia",
    ],
    "nature": [
        "Banff, Canada",
        "Jasper, Canada",
        "Whistler, Canada",
        "Anchorage, Alaska",
        "Juneau, Alaska",
        "Sedona, Arizona",
        "Moab, Utah",
        "Jackson, Wyoming",
        "Yellowstone National Park, Wyoming",
        "Yosemite National Park, California",
        "Lake Tahoe, California",
        "Aspen, Colorado",
        "Breckenridge, Colorado",
        "Estes Park, Colorado",
        "Colorado Springs, Colorado",
        "Asheville, North Carolina",
        "Great Smoky Mountains, Tennessee",
        "Reykjavik, Iceland",
        "Akureyri, Iceland",
        "Interlaken, Switzerland",
        "Zermatt, Switzerland",
        "Innsbruck, Austria",
        "Salzburg, Austria",
        "Bergen, Norway",
        "Tromso, Norway",
        "Lofoten, Norway",
        "Azores, Portugal",
        "Madeira, Portugal",
        "Lake District, United Kingdom",
        "Scottish Highlands, United Kingdom",
        "Dolomites, Italy",
        "Slovenian Alps, Slovenia",
        "Plitvice Lakes, Croatia",
        "Durmitor, Montenegro",
        "San Jose, Costa Rica",
        "La Fortuna, Costa Rica",
        "Monteverde, Costa Rica",
        "Boquete, Panama",
        "Galapagos Islands, Ecuador",
        "Quito, Ecuador",
        "Patagonia, Argentina",
        "Bariloche, Argentina",
        "Mendoza, Argentina",
        "Atacama Desert, Chile",
        "Torres del Paine, Chile",
        "Uyuni, Bolivia",
        "Cusco, Peru",
        "Iguazu Falls, Brazil",
        "Chapada Diamantina, Brazil",
        "Cape Town, South Africa",
        "Kruger National Park, South Africa",
        "Victoria Falls, Zimbabwe",
        "Maun, Botswana",
        "Etosha National Park, Namibia",
        "Arusha, Tanzania",
        "Masai Mara, Kenya",
        "Bwindi, Uganda",
        "Volcanoes National Park, Rwanda",
        "Simien Mountains, Ethiopia",
        "Queenstown, New Zealand",
        "Rotorua, New Zealand",
        "Fiordland, New Zealand",
        "Cairns, Australia",
        "Tasmania, Australia",
        "Uluru, Australia",
        "Blue Mountains, Australia",
        "Ubud, Indonesia",
        "Komodo, Indonesia",
        "Sabah, Malaysia",
        "Sapa, Vietnam",
        "Ha Long Bay, Vietnam",
        "Pokhara, Nepal",
        "Paro, Bhutan",
        "Hokkaido, Japan",
    ],
    "food": [
        "New Orleans, Louisiana",
        "New York City, New York",
        "Chicago, Illinois",
        "Austin, Texas",
        "Portland, Oregon",
        "Montreal, Canada",
        "Mexico City, Mexico",
        "Oaxaca, Mexico",
        "Lima, Peru",
        "Buenos Aires, Argentina",
        "Sao Paulo, Brazil",
        "San Sebastian, Spain",
        "Lyon, France",
        "Bologna, Italy",
        "Naples, Italy",
        "Brussels, Belgium",
        "Copenhagen, Denmark",
        "Istanbul, Turkey",
        "Marrakesh, Morocco",
        "Cape Town, South Africa",
        "Tokyo, Japan",
        "Osaka, Japan",
        "Fukuoka, Japan",
        "Seoul, South Korea",
        "Taipei, Taiwan",
        "Hong Kong",
        "Bangkok, Thailand",
        "Chiang Mai, Thailand",
        "Singapore",
        "Penang, Malaysia",
        "Hanoi, Vietnam",
        "Ho Chi Minh City, Vietnam",
        "Mumbai, India",
        "Delhi, India",
    ],
    "nightlife": [
        "Las Vegas, Nevada",
        "New York City, New York",
        "Miami, Florida",
        "New Orleans, Louisiana",
        "Montreal, Canada",
        "Mexico City, Mexico",
        "Cancun, Mexico",
        "Medellin, Colombia",
        "Rio de Janeiro, Brazil",
        "Buenos Aires, Argentina",
        "London, United Kingdom",
        "Berlin, Germany",
        "Amsterdam, Netherlands",
        "Barcelona, Spain",
        "Madrid, Spain",
        "Ibiza, Spain",
        "Lisbon, Portugal",
        "Prague, Czechia",
        "Budapest, Hungary",
        "Belgrade, Serbia",
        "Mykonos, Greece",
        "Split, Croatia",
        "Istanbul, Turkey",
        "Tel Aviv, Israel",
        "Dubai, United Arab Emirates",
        "Cape Town, South Africa",
        "Lagos, Nigeria",
        "Accra, Ghana",
        "Bangkok, Thailand",
        "Phuket, Thailand",
        "Tokyo, Japan",
        "Seoul, South Korea",
        "Hong Kong",
        "Singapore",
        "Bali, Indonesia",
        "Manila, Philippines",
    ],
    "history": [
        "Washington, District of Columbia",
        "Philadelphia, Pennsylvania",
        "Boston, Massachusetts",
        "Quebec City, Canada",
        "Mexico City, Mexico",
        "Chichen Itza, Mexico",
        "Havana, Cuba",
        "Cartagena, Colombia",
        "Cusco, Peru",
        "Rome, Italy",
        "Florence, Italy",
        "Athens, Greece",
        "Istanbul, Turkey",
        "Cairo, Egypt",
        "Luxor, Egypt",
        "Petra, Jordan",
        "Jerusalem, Israel",
        "Marrakesh, Morocco",
        "Fez, Morocco",
        "Dakar, Senegal",
        "Cape Coast, Ghana",
        "Zanzibar City, Tanzania",
        "Lalibela, Ethiopia",
        "Kyoto, Japan",
        "Nara, Japan",
        "Beijing, China",
        "Xi'an, China",
        "Jaipur, India",
        "Varanasi, India",
        "Kathmandu, Nepal",
        "Siem Reap, Cambodia",
        "Hoi An, Vietnam",
        "Ayutthaya, Thailand",
    ],
    "adventure": [
        "Moab, Utah",
        "Aspen, Colorado",
        "Breckenridge, Colorado",
        "Estes Park, Colorado",
        "Colorado Springs, Colorado",
        "Anchorage, Alaska",
        "Banff, Canada",
        "Whistler, Canada",
        "La Fortuna, Costa Rica",
        "Patagonia, Argentina",
        "Cusco, Peru",
        "Quito, Ecuador",
        "Atacama Desert, Chile",
        "Interlaken, Switzerland",
        "Chamonix, France",
        "Innsbruck, Austria",
        "Reykjavik, Iceland",
        "Cape Town, South Africa",
        "Victoria Falls, Zimbabwe",
        "Maun, Botswana",
        "Arusha, Tanzania",
        "Pokhara, Nepal",
        "Paro, Bhutan",
        "Queenstown, New Zealand",
        "Cairns, Australia",
        "Tasmania, Australia",
        "Komodo, Indonesia",
        "Palawan, Philippines",
        "Sabah, Malaysia",
    ],
    "wellness": [
        "Sedona, Arizona",
        "Palm Springs, California",
        "Tulum, Mexico",
        "Nosara, Costa Rica",
        "Osa Peninsula, Costa Rica",
        "Ubud, Indonesia",
        "Bali, Indonesia",
        "Ko Samui, Thailand",
        "Chiang Mai, Thailand",
        "Phuket, Thailand",
        "Rishikesh, India",
        "Kerala, India",
        "Goa, India",
        "Kyoto, Japan",
        "Hakone, Japan",
        "Reykjavik, Iceland",
        "Baden-Baden, Germany",
        "Bath, United Kingdom",
        "Budapest, Hungary",
        "Madeira, Portugal",
    ],
}

TRIP_TYPE_KEYWORDS = {
    "beach": ["beach", "coast", "coastal", "ocean", "island", "tropical", "seaside"],
    "nature": ["nature", "mountain", "hiking", "outdoor", "forest", "national park", "wildlife"],
    "culture": ["culture", "cultural", "museum", "architecture", "arts", "heritage"],
    "city": ["city", "urban", "shopping", "metropolitan"],
    "food": ["food", "cuisine", "culinary", "restaurant", "dining"],
    "nightlife": ["nightlife", "party", "clubs", "bars"],
    "history": ["historic", "history", "ancient", "ruins", "landmarks"],
    "adventure": ["adventure", "rafting", "climbing", "surfing", "safari", "extreme"],
    "wellness": ["wellness", "spa", "yoga", "relax", "retreat"],
}

# Fallback subregion mapping. If region_service has resolve_subregion(), that
# function is used instead.
COUNTRY_SUBREGION_MAP = {
    # Africa
    "Algeria": "North Africa", "Egypt": "North Africa", "Libya": "North Africa",
    "Morocco": "North Africa", "Sudan": "North Africa", "Tunisia": "North Africa",
    "Benin": "West Africa", "Burkina Faso": "West Africa", "Cape Verde": "West Africa",
    "Ivory Coast": "West Africa", "Gambia": "West Africa", "Ghana": "West Africa",
    "Guinea": "West Africa", "Guinea-Bissau": "West Africa", "Liberia": "West Africa",
    "Mali": "West Africa", "Mauritania": "West Africa", "Niger": "West Africa",
    "Nigeria": "West Africa", "Senegal": "West Africa", "Sierra Leone": "West Africa",
    "Togo": "West Africa",
    "Burundi": "East Africa", "Comoros": "East Africa", "Djibouti": "East Africa",
    "Eritrea": "East Africa", "Ethiopia": "East Africa", "Kenya": "East Africa",
    "Madagascar": "East Africa", "Malawi": "East Africa", "Mauritius": "East Africa",
    "Mozambique": "East Africa", "Rwanda": "East Africa", "Seychelles": "East Africa",
    "Somalia": "East Africa", "South Sudan": "East Africa", "Tanzania": "East Africa",
    "Uganda": "East Africa", "Zambia": "East Africa", "Zimbabwe": "East Africa",
    "Angola": "Central Africa", "Cameroon": "Central Africa", "Central African Republic": "Central Africa",
    "Chad": "Central Africa", "Democratic Republic of the Congo": "Central Africa",
    "Equatorial Guinea": "Central Africa", "Gabon": "Central Africa", "Republic of the Congo": "Central Africa",
    "Botswana": "Southern Africa", "Eswatini": "Southern Africa", "Lesotho": "Southern Africa",
    "Namibia": "Southern Africa", "South Africa": "Southern Africa",
    # Asia
    "China": "East Asia", "Hong Kong": "East Asia", "Japan": "East Asia",
    "Macau": "East Asia", "Mongolia": "East Asia", "North Korea": "East Asia",
    "South Korea": "East Asia", "Taiwan": "East Asia",
    "Brunei": "Southeast Asia", "Cambodia": "Southeast Asia", "Indonesia": "Southeast Asia",
    "Laos": "Southeast Asia", "Malaysia": "Southeast Asia", "Myanmar": "Southeast Asia",
    "Philippines": "Southeast Asia", "Singapore": "Southeast Asia", "Thailand": "Southeast Asia",
    "Timor-Leste": "Southeast Asia", "Vietnam": "Southeast Asia",
    "Afghanistan": "South Asia", "Bangladesh": "South Asia", "Bhutan": "South Asia",
    "India": "South Asia", "Maldives": "South Asia", "Nepal": "South Asia",
    "Pakistan": "South Asia", "Sri Lanka": "South Asia",
    "Kazakhstan": "Central Asia", "Kyrgyzstan": "Central Asia", "Tajikistan": "Central Asia",
    "Turkmenistan": "Central Asia", "Uzbekistan": "Central Asia",
    "Armenia": "West Asia", "Azerbaijan": "West Asia", "Bahrain": "West Asia",
    "Cyprus": "West Asia", "Georgia": "West Asia", "Iraq": "West Asia",
    "Israel": "West Asia", "Jordan": "West Asia", "Kuwait": "West Asia",
    "Lebanon": "West Asia", "Oman": "West Asia", "Qatar": "West Asia",
    "Saudi Arabia": "West Asia", "Turkey": "West Asia", "United Arab Emirates": "West Asia",
    "Yemen": "West Asia",
    # Europe
    "Denmark": "Northern Europe", "Estonia": "Northern Europe", "Finland": "Northern Europe",
    "Iceland": "Northern Europe", "Ireland": "Northern Europe", "Latvia": "Northern Europe",
    "Lithuania": "Northern Europe", "Norway": "Northern Europe", "Sweden": "Northern Europe",
    "United Kingdom": "Northern Europe",
    "Austria": "Western Europe", "Belgium": "Western Europe", "France": "Western Europe",
    "Germany": "Western Europe", "Liechtenstein": "Western Europe", "Luxembourg": "Western Europe",
    "Monaco": "Western Europe", "Netherlands": "Western Europe", "Switzerland": "Western Europe",
    "Albania": "Southern Europe", "Andorra": "Southern Europe", "Bosnia and Herzegovina": "Southern Europe",
    "Croatia": "Southern Europe", "Greece": "Southern Europe", "Italy": "Southern Europe",
    "Malta": "Southern Europe", "Montenegro": "Southern Europe", "North Macedonia": "Southern Europe",
    "Portugal": "Southern Europe", "San Marino": "Southern Europe", "Serbia": "Southern Europe",
    "Slovenia": "Southern Europe", "Spain": "Southern Europe", "Vatican City": "Southern Europe",
    "Belarus": "Eastern Europe", "Bulgaria": "Eastern Europe", "Czechia": "Eastern Europe",
    "Hungary": "Eastern Europe", "Moldova": "Eastern Europe", "Poland": "Eastern Europe",
    "Romania": "Eastern Europe", "Russia": "Eastern Europe", "Slovakia": "Eastern Europe",
    "Ukraine": "Eastern Europe",
    # North America and Caribbean
    "Canada": "Northern America", "United States": "Northern America",
    "Belize": "Central America", "Costa Rica": "Central America", "El Salvador": "Central America",
    "Guatemala": "Central America", "Honduras": "Central America", "Mexico": "Central America",
    "Nicaragua": "Central America", "Panama": "Central America",
    "Anguilla": "Caribbean", "Antigua and Barbuda": "Caribbean", "Aruba": "Caribbean",
    "Bahamas": "Caribbean", "Barbados": "Caribbean", "Cuba": "Caribbean",
    "Curacao": "Caribbean", "Dominica": "Caribbean", "Dominican Republic": "Caribbean",
    "Grenada": "Caribbean", "Guadeloupe": "Caribbean", "Haiti": "Caribbean",
    "Jamaica": "Caribbean", "Martinique": "Caribbean", "Puerto Rico": "Caribbean",
    "Saint Kitts and Nevis": "Caribbean", "Saint Lucia": "Caribbean",
    "Saint Vincent and the Grenadines": "Caribbean", "Trinidad and Tobago": "Caribbean",
    # South America
    "Colombia": "Northern South America", "Guyana": "Northern South America",
    "Suriname": "Northern South America", "Venezuela": "Northern South America",
    "Bolivia": "Andean Region", "Ecuador": "Andean Region", "Peru": "Andean Region",
    "Argentina": "Southern Cone", "Chile": "Southern Cone", "Paraguay": "Southern Cone",
    "Uruguay": "Southern Cone", "Brazil": "Brazil",
    # Oceania
    "Australia": "Australia and New Zealand", "New Zealand": "Australia and New Zealand",
    "Fiji": "Melanesia", "New Caledonia": "Melanesia", "Papua New Guinea": "Melanesia",
    "Solomon Islands": "Melanesia", "Vanuatu": "Melanesia",
    "Kiribati": "Micronesia", "Marshall Islands": "Micronesia", "Micronesia": "Micronesia",
    "Nauru": "Micronesia", "Palau": "Micronesia",
    "French Polynesia": "Polynesia", "Samoa": "Polynesia", "Tonga": "Polynesia",
    "Tuvalu": "Polynesia",
}


ADMINISTRATIVE_AREA_ALIASES = {
    "alabama": "Alabama", "alaska": "Alaska", "arizona": "Arizona",
    "arkansas": "Arkansas", "california": "California", "colorado": "Colorado",
    "connecticut": "Connecticut", "delaware": "Delaware",
    "district of columbia": "District of Columbia",
    "washington dc": "District of Columbia", "washington, dc": "District of Columbia",
    "florida": "Florida", "georgia": "Georgia", "hawaii": "Hawaii",
    "idaho": "Idaho", "illinois": "Illinois", "indiana": "Indiana",
    "iowa": "Iowa", "kansas": "Kansas", "kentucky": "Kentucky",
    "louisiana": "Louisiana", "maine": "Maine", "maryland": "Maryland",
    "massachusetts": "Massachusetts", "michigan": "Michigan", "minnesota": "Minnesota",
    "mississippi": "Mississippi", "missouri": "Missouri", "montana": "Montana",
    "nebraska": "Nebraska", "nevada": "Nevada", "new hampshire": "New Hampshire",
    "new jersey": "New Jersey", "new mexico": "New Mexico", "new york": "New York",
    "north carolina": "North Carolina", "north dakota": "North Dakota",
    "ohio": "Ohio", "oklahoma": "Oklahoma", "oregon": "Oregon",
    "pennsylvania": "Pennsylvania", "rhode island": "Rhode Island",
    "south carolina": "South Carolina", "south dakota": "South Dakota",
    "tennessee": "Tennessee", "texas": "Texas", "utah": "Utah",
    "vermont": "Vermont", "virginia": "Virginia", "washington": "Washington",
    "west virginia": "West Virginia", "wisconsin": "Wisconsin", "wyoming": "Wyoming",
    "alberta": "Alberta", "british columbia": "British Columbia",
    "manitoba": "Manitoba", "new brunswick": "New Brunswick",
    "newfoundland and labrador": "Newfoundland and Labrador",
    "nova scotia": "Nova Scotia", "ontario": "Ontario",
    "prince edward island": "Prince Edward Island", "quebec": "Quebec",
    "saskatchewan": "Saskatchewan", "northwest territories": "Northwest Territories",
    "nunavut": "Nunavut", "yukon": "Yukon",
}


def _normalize_administrative_area(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    return ADMINISTRATIVE_AREA_ALIASES.get(text.lower(), text)


def detect_requested_administrative_areas(prompt: str) -> set[str]:
    """Detects explicit U.S. state or Canadian province/territory wording."""
    prompt_lower = prompt.lower()
    requested: set[str] = set()

    for alias, canonical in sorted(
        ADMINISTRATIVE_AREA_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
        if re.search(pattern, prompt_lower):
            requested.add(canonical)

    return requested


def _seed_administrative_area(seed: str) -> str:
    parts = [part.strip() for part in seed.split(",") if part.strip()]
    if len(parts) < 2:
        return ""
    return ADMINISTRATIVE_AREA_ALIASES.get(parts[1].lower(), "")


def _infer_administrative_area_from_seed(city: Any) -> str:
    city_key = _normalize_text(city).lower()
    if not city_key:
        return ""

    for seeds in DESTINATION_DISCOVERY_SEEDS.values():
        for seed in seeds:
            if seed.split(",")[0].strip().lower() != city_key:
                continue
            administrative_area = _seed_administrative_area(seed)
            if administrative_area:
                return administrative_area

    return ""


def get_destination_administrative_area(destination: dict[str, Any]) -> str:
    saved = _normalize_administrative_area(destination.get("administrative_area"))
    if saved:
        return saved
    return _infer_administrative_area_from_seed(destination.get("city"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    return str(value).strip()


def _normalize_city_key(city: Any, country: Any = "") -> tuple[str, str]:
    return (_normalize_text(city).lower(), _normalize_text(country).lower())


def _resolve_subregion(location: dict[str, Any]) -> str:
    if callable(resolve_subregion):
        try:
            value = resolve_subregion(location)
            if value:
                return str(value)
        except (TypeError, ValueError, KeyError):
            pass

    return COUNTRY_SUBREGION_MAP.get(_normalize_text(location.get("country")), "")


def _ensure_csv_schema(df: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "city": "",
        "country": "",
        "region": "",
        "subregion": "",
        "administrative_area": "",
        "trip_type_1": "unknown",
        "trip_type_2": "unknown",
        "trip_type_3": "unknown",
        "climate_tag": "unknown",
        "estimated_nightly_cost": 150,
        "safety_score": 5,
        "attraction_score": 5,
        "destination_description": "",
    }

    optional_columns = [
        "average_humidity",
        "latitude",
        "longitude",
        "airport_code",
    ]

    for column, default_value in defaults.items():
        if column not in df.columns:
            df[column] = default_value
        else:
            df[column] = df[column].fillna(default_value)

    for column in optional_columns:
        if column not in df.columns:
            df[column] = None
        else:
            df[column] = df[column].where(df[column].notna(), None)

    if "administrative_area" in df.columns:
        admin_missing = (
            df["administrative_area"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"", "unknown", "none", "nan"})
        )
        if admin_missing.any():
            df.loc[admin_missing, "administrative_area"] = df.loc[
                admin_missing, "city"
            ].apply(_infer_administrative_area_from_seed)

    # Migrate any remaining legacy trip_type values into trip_type_1.
    if "trip_type" in df.columns:
        legacy = df["trip_type"].fillna("unknown").astype(str)
        primary = df["trip_type_1"].fillna("unknown").astype(str)
        use_legacy = primary.str.strip().str.lower().isin({"", "unknown", "none", "nan"})
        df.loc[use_legacy, "trip_type_1"] = legacy[use_legacy]
        df = df.drop(columns=["trip_type"])

    for column in CSV_COLUMNS:
        if column not in df.columns:
            df[column] = None

    return df[CSV_COLUMNS]


@lru_cache(maxsize=1)
def load_locations() -> list[dict[str, Any]]:
    """Loads and normalizes the local travel destination inventory."""
    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)
    df = _ensure_csv_schema(df)
    return df.to_dict(orient="records")


def clear_location_cache() -> None:
    """Clears the cached destination inventory after a CSV update."""
    load_locations.cache_clear()


def repair_missing_administrative_areas() -> int:
    """
    Persistently backfills blank state/province/territory values when the
    curated destination seed inventory provides deterministic evidence.

    This intentionally avoids an external API call for locations GreenBookAI
    already knows, such as Key West -> Florida or Denver -> Colorado.

    Returns the number of CSV rows updated.
    """
    if not TRAVEL_LOCATIONS_FILE.exists():
        return 0

    df = pd.read_csv(TRAVEL_LOCATIONS_FILE)

    if "administrative_area" not in df.columns:
        df["administrative_area"] = ""

    updated = 0

    for index, row in df.iterrows():
        current = _normalize_administrative_area(
            row.get("administrative_area")
        )

        if current:
            continue

        inferred = _infer_administrative_area_from_seed(
            row.get("city")
        )

        if not inferred:
            continue

        df.at[index, "administrative_area"] = inferred
        updated += 1

    if updated:
        df = _ensure_csv_schema(df)
        df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)
        clear_location_cache()

    return updated


def get_location_by_city(city_name: str, country_name: str | None = None):
    """Finds one location using case-insensitive city and optional country matching."""
    requested_city = _normalize_text(city_name).lower()
    requested_country = _normalize_text(country_name).lower()

    for location in load_locations():
        if _normalize_text(location.get("city")).lower() != requested_city:
            continue
        if requested_country and _normalize_text(location.get("country")).lower() != requested_country:
            continue
        return location

    return None


def get_candidate_locations() -> list[dict[str, Any]]:
    """Returns all destinations currently available to the recommender."""
    return load_locations()


def _clean_airport_code(value: Any):
    """Returns a valid three-letter airport code or None."""
    if value is None or pd.isna(value):
        return None

    airport_code = str(value).strip().upper()
    return airport_code if re.fullmatch(r"[A-Z]{3}", airport_code) else None


def _extract_airport_code(feature: dict[str, Any]):
    properties = feature.get("properties", {})
    datasource = properties.get("datasource", {})
    raw = datasource.get("raw", {}) if isinstance(datasource, dict) else {}

    candidates = [
        properties.get("iata"),
        properties.get("iata_code"),
        properties.get("airport_code"),
        raw.get("iata"),
        raw.get("iata_code"),
        raw.get("airport:iata"),
        raw.get("ref"),
    ]

    for candidate in candidates:
        airport_code = _clean_airport_code(candidate)
        if airport_code:
            return airport_code

    return None


def discover_airport_code(latitude: Any, longitude: Any, radius_meters: int = 200000):
    """Finds the nearest usable airport code with Geoapify Places."""
    if not GEOAPIFY_API_KEY or latitude is None or longitude is None:
        return None

    for categories in ("airport.international", "airport"):
        params = {
            "categories": categories,
            "filter": f"circle:{longitude},{latitude},{radius_meters}",
            "bias": f"proximity:{longitude},{latitude}",
            "limit": 20,
            "apiKey": GEOAPIFY_API_KEY,
        }

        try:
            response = requests.get(PLACES_URL, params=params, timeout=(3, 8))
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue

        for feature in data.get("features", []):
            airport_code = _extract_airport_code(feature)
            if airport_code:
                return airport_code

    return None


def _default_description(city: str, country: str, trip_types: list[str]) -> str:
    labels = [trip_type.replace("_", " ") for trip_type in trip_types if trip_type != "unknown"]
    if labels:
        focus = ", ".join(labels[:3])
        return f"{city} in {country} is a destination associated with {focus} travel."
    return f"{city} is a travel destination in {country}."


def discover_location(city_name: str):
    """Discovers a location with Geoapify and returns the current CSV schema."""
    if not GEOAPIFY_API_KEY:
        return None

    params = {
        "text": city_name,
        "format": "json",
        "limit": 1,
        "apiKey": GEOAPIFY_API_KEY,
    }

    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=(3, 8))
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("results", [])
    if not results:
        return None

    result = results[0]
    city = result.get("city") or result.get("name") or city_name.split(",")[0].strip()
    country = result.get("country", "")
    latitude = result.get("lat")
    longitude = result.get("lon")

    administrative_area = (
        result.get("state")
        or result.get("state_district")
        or result.get("county")
        or ""
    )

    location = {
        "city": city,
        "country": country,
        "region": result.get("continent", ""),
        "administrative_area": _normalize_administrative_area(administrative_area),
        "latitude": latitude,
        "longitude": longitude,
    }

    location["region"] = resolve_region(location)
    location["subregion"] = _resolve_subregion(location)
    airport_code = discover_airport_code(latitude, longitude)

    return {
        "city": city,
        "country": country,
        "region": location["region"],
        "subregion": location["subregion"],
        "administrative_area": location["administrative_area"],
        "trip_type_1": "unknown",
        "trip_type_2": "unknown",
        "trip_type_3": "unknown",
        "climate_tag": "unknown",
        "average_humidity": None,
        "estimated_nightly_cost": 150,
        "safety_score": 5,
        "attraction_score": 5,
        "latitude": latitude,
        "longitude": longitude,
        "airport_code": airport_code,
        "destination_description": _default_description(city, country, []),
        "source": "Geoapify",
        "discovered_at": _utc_now_iso(),
    }


def update_location_airport_code(city_name: str, airport_code: str, country_name: str | None = None) -> bool:
    """Saves a discovered airport code to an existing CSV row."""
    airport_code = _clean_airport_code(airport_code)
    if not airport_code:
        return False

    df = _ensure_csv_schema(pd.read_csv(TRAVEL_LOCATIONS_FILE))
    city_mask = df["city"].astype(str).str.strip().str.lower() == city_name.strip().lower()

    if country_name:
        country_mask = df["country"].astype(str).str.strip().str.lower() == country_name.strip().lower()
        city_mask &= country_mask

    if not city_mask.any():
        return False

    df.loc[city_mask, "airport_code"] = airport_code
    df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)
    clear_location_cache()
    return True


def refresh_dynamic_fields(location: dict[str, Any]):
    """Enriches a location with an airport code when one is missing."""
    if _clean_airport_code(location.get("airport_code")):
        return location

    airport_code = discover_airport_code(location.get("latitude"), location.get("longitude"))
    if airport_code:
        update_location_airport_code(
            location.get("city", ""),
            airport_code,
            location.get("country"),
        )
        location["airport_code"] = airport_code

    return location


def validate_location(location: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validates a destination before it is written to the CSV."""
    errors: list[str] = []

    if not _normalize_text(location.get("city")):
        errors.append("city is required")
    if not _normalize_text(location.get("country")):
        errors.append("country is required")

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if latitude is not None and not (-90 <= float(latitude) <= 90):
        errors.append("latitude must be between -90 and 90")
    if longitude is not None and not (-180 <= float(longitude) <= 180):
        errors.append("longitude must be between -180 and 180")

    airport_code = location.get("airport_code")
    if airport_code and not _clean_airport_code(airport_code):
        errors.append("airport_code must contain exactly three letters")

    for field in ("safety_score", "attraction_score"):
        value = float(location.get(field, 5))
        if not 1 <= value <= 10:
            errors.append(f"{field} must be between 1 and 10")

    if float(location.get("estimated_nightly_cost", 150)) <= 0:
        errors.append("estimated_nightly_cost must be positive")

    return not errors, errors


def save_location(location: dict[str, Any]):
    """Appends a discovered destination using the current 16-column schema."""
    existing_location = get_location_by_city(location.get("city", ""), location.get("country"))
    if existing_location:
        return refresh_dynamic_fields(existing_location)

    enriched = dict(location)
    enriched["region"] = resolve_region(enriched)
    enriched["subregion"] = _resolve_subregion(enriched)

    airport_code = _clean_airport_code(enriched.get("airport_code"))
    if not airport_code:
        airport_code = discover_airport_code(enriched.get("latitude"), enriched.get("longitude"))
    enriched["airport_code"] = airport_code

    trip_types = [
        _normalize_text(enriched.get("trip_type_1"), "unknown").lower(),
        _normalize_text(enriched.get("trip_type_2"), "unknown").lower(),
        _normalize_text(enriched.get("trip_type_3"), "unknown").lower(),
    ]

    if not _normalize_text(enriched.get("destination_description")):
        enriched["destination_description"] = _default_description(
            _normalize_text(enriched.get("city")),
            _normalize_text(enriched.get("country")),
            trip_types,
        )

    new_row = {
        "city": enriched.get("city"),
        "country": enriched.get("country"),
        "region": enriched.get("region", ""),
        "subregion": enriched.get("subregion", ""),
        "administrative_area": _normalize_administrative_area(
            enriched.get("administrative_area")
        ),
        "trip_type_1": trip_types[0],
        "trip_type_2": trip_types[1],
        "trip_type_3": trip_types[2],
        "climate_tag": _normalize_text(enriched.get("climate_tag"), "unknown").lower(),
        "average_humidity": enriched.get("average_humidity"),
        "estimated_nightly_cost": enriched.get("estimated_nightly_cost", 150),
        "safety_score": enriched.get("safety_score", 5),
        "attraction_score": enriched.get("attraction_score", 5),
        "latitude": enriched.get("latitude"),
        "longitude": enriched.get("longitude"),
        "airport_code": airport_code,
        "destination_description": enriched.get("destination_description", ""),
    }

    is_valid, errors = validate_location(new_row)
    if not is_valid:
        raise ValueError(f"Cannot save invalid location: {', '.join(errors)}")

    df = _ensure_csv_schema(pd.read_csv(TRAVEL_LOCATIONS_FILE))
    df = pd.concat([df, pd.DataFrame([new_row], columns=CSV_COLUMNS)], ignore_index=True)
    df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)
    clear_location_cache()

    saved_location = dict(new_row)
    saved_location["source"] = enriched.get("source", "Geoapify")
    return saved_location


def get_or_discover_location(city_name: str):
    """Returns a local destination or discovers and saves it for future use."""
    location = get_location_by_city(city_name)

    if location:
        location = refresh_dynamic_fields(location)
        location["source"] = "Local"
        return location

    discovered_location = discover_location(city_name)
    if not discovered_location:
        return None

    from app.services.enrichment_service import enrich_location

    enriched_location = enrich_location(discovered_location)
    return save_location(enriched_location)


def _detect_requested_trip_types(prompt: str) -> list[str]:
    prompt_lower = prompt.lower()
    matches = []

    for trip_type, keywords in TRIP_TYPE_KEYWORDS.items():
        if any(keyword in prompt_lower for keyword in keywords):
            matches.append(trip_type)

    return matches


def _detect_requested_trip_type(prompt: str):
    """Backward-compatible helper returning the strongest detected trip type."""
    matches = _detect_requested_trip_types(prompt)
    return matches[0] if matches else None


def _detect_climate_tag(prompt: str) -> str:
    prompt_lower = prompt.lower()

    if any(word in prompt_lower for word in ["warm", "hot", "tropical", "beach", "summer"]):
        return "warm"
    if any(word in prompt_lower for word in ["cold", "snow", "winter", "ski"]):
        return "cold"
    if any(word in prompt_lower for word in ["mild", "comfortable", "cool", "spring", "fall"]):
        return "mild"

    return "unknown"


def _seed_matches_prompt_geography(seed: str, prompt: str) -> bool:
    """Prioritizes seeds whose country/area text appears in the prompt."""
    prompt_lower = prompt.lower()
    seed_parts = [part.strip().lower() for part in seed.split(",") if part.strip()]
    return any(part in prompt_lower for part in seed_parts)


def _ordered_discovery_seeds(prompt: str) -> list[tuple[str, str]]:
    """Builds a deduplicated, prompt-relevant discovery queue."""
    requested_types = _detect_requested_trip_types(prompt)
    requested_administrative_areas = detect_requested_administrative_areas(prompt)
    category_order = requested_types + [
        category for category in DESTINATION_DISCOVERY_SEEDS if category not in requested_types
    ]

    prioritized: list[tuple[str, str]] = []
    regular: list[tuple[str, str]] = []
    seen: set[str] = set()

    for category in category_order:
        for seed in DESTINATION_DISCOVERY_SEEDS.get(category, []):
            if requested_administrative_areas:
                seed_area = _seed_administrative_area(seed)
                if seed_area not in requested_administrative_areas:
                    continue

            key = seed.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            item = (seed, category)
            if _seed_matches_prompt_geography(seed, prompt):
                prioritized.append(item)
            else:
                regular.append(item)

    return prioritized + regular


def discover_destination_candidates(prompt: str, limit: int = DEFAULT_DISCOVERY_LIMIT):
    """
    Aggressively expands the inventory with prompt-relevant destinations.

    While the CSV contains fewer than TARGET_INVENTORY_SIZE rows, the service
    automatically raises the requested discovery amount, up to MAX_DISCOVERY_LIMIT.
    It starts with matching trip types, then backfills from other categories so
    the inventory does not remain stuck around 50 destinations.
    """
    existing_locations = load_locations()
    current_size = len(existing_locations)

    requested_types = _detect_requested_trip_types(prompt)
    climate_tag = _detect_climate_tag(prompt)

    # Ordinary requests remain conservative so inventory growth does not create
    # unnecessary geocoding/enrichment calls. When the traveler explicitly names
    # a state/province/territory, however, GreenBookAI expands that area enough
    # to support a meaningful local comparison in the same request.
    requested_administrative_areas = detect_requested_administrative_areas(prompt)

    effective_limit = min(
        MAX_DISCOVERY_LIMIT,
        max(0, limit),
    )

    if requested_administrative_areas:
        existing_in_requested_area = sum(
            1
            for location in existing_locations
            if get_destination_administrative_area(location)
            in requested_administrative_areas
        )

        area_deficit = max(
            0,
            MIN_ADMINISTRATIVE_AREA_CANDIDATES
            - existing_in_requested_area,
        )

        # Discover the number actually needed to build a useful candidate pool.
        # Example: if Colorado has only Denver, discover up to four additional
        # Colorado destinations during this request rather than one per run.
        effective_limit = min(
            MAX_DISCOVERY_LIMIT,
            max(effective_limit, area_deficit),
        )

    existing_keys = {
        _normalize_city_key(location.get("city"), location.get("country"))
        for location in existing_locations
    }
    existing_city_names = {
        _normalize_text(location.get("city")).lower() for location in existing_locations
    }

    new_locations = []

    for seed, seed_category in _ordered_discovery_seeds(prompt):
        if len(new_locations) >= effective_limit:
            break

        seed_city = seed.split(",")[0].strip().lower()
        if seed_city in existing_city_names:
            continue

        discovered = discover_location(seed)
        if not discovered:
            continue

        discovered_key = _normalize_city_key(discovered.get("city"), discovered.get("country"))
        if discovered_key in existing_keys:
            continue

        # Enrich every newly discovered destination from Geoapify evidence.
        # The original seed category remains a fallback only when external
        # enrichment is unavailable.
        primary_type = requested_types[0] if requested_types else seed_category
        discovered["trip_type_1"] = primary_type
        discovered["trip_type_2"] = "unknown"
        discovered["trip_type_3"] = "unknown"
        discovered["climate_tag"] = climate_tag

        from app.services.enrichment_service import enrich_location
        discovered = enrich_location(discovered)

        try:
            saved = save_location(discovered)
        except ValueError:
            continue

        if saved:
            new_locations.append(saved)
            existing_keys.add(discovered_key)
            existing_city_names.add(_normalize_text(saved.get("city")).lower())

    return new_locations


def bootstrap_destination_inventory(target_size: int = TARGET_INVENTORY_SIZE, batch_size: int = 20):
    """
    Expands the CSV across several trip types until it reaches target_size.

    Call this manually once during setup when you want to grow the inventory
    quickly without waiting for many different recommendation prompts.
    """
    target_size = max(len(load_locations()), target_size)
    batch_size = max(1, min(batch_size, MAX_DISCOVERY_LIMIT))
    added: list[dict[str, Any]] = []

    bootstrap_prompts = [
        "beach vacation",
        "city vacation",
        "culture and history vacation",
        "nature and adventure vacation",
        "food vacation",
        "nightlife vacation",
        "wellness retreat",
    ]

    while len(load_locations()) < target_size:
        before = len(load_locations())

        for prompt in bootstrap_prompts:
            remaining = target_size - len(load_locations())
            if remaining <= 0:
                break
            added.extend(discover_destination_candidates(prompt, limit=min(batch_size, remaining)))

        after = len(load_locations())
        if after == before:
            break

    return added


ENRICHMENT_FIELDS = [
    "trip_type_1",
    "trip_type_2",
    "trip_type_3",
    "climate_tag",
    "destination_description",
]


_MISSING_ENRICHMENT_VALUES = {
    "",
    "unknown",
    "none",
    "null",
    "nan",
    "n/a",
    "not available",
}


def _enrichment_value_is_missing(value: Any) -> bool:
    """Returns True for blank, null, NaN, or placeholder enrichment values."""
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return str(value).strip().lower() in _MISSING_ENRICHMENT_VALUES


def _destination_description_is_incomplete(value: Any) -> bool:
    """Treats only blank or null-like descriptions as incomplete."""
    return _enrichment_value_is_missing(value)


def enrich_incomplete_locations(limit: int | None = None) -> dict[str, int]:
    """
    Scans existing CSV rows and fills incomplete semantic metadata.

    This function updates existing rows only. It does not discover, append,
    or save new destinations. Valid existing values are preserved.
    """
    from app.services.enrichment_service import enrich_location

    if limit is not None and limit < 1:
        return {"attempted": 0, "updated": 0, "failed": 0}

    df = _ensure_csv_schema(pd.read_csv(TRAVEL_LOCATIONS_FILE))

    attempted_rows = 0
    updated_rows = 0
    failed_rows = 0

    for index, row in df.iterrows():
        missing_fields: list[str] = []

        for field in ENRICHMENT_FIELDS:
            current_value = row.get(field)

            if field == "destination_description":
                if _destination_description_is_incomplete(current_value):
                    missing_fields.append(field)
            elif _enrichment_value_is_missing(current_value):
                missing_fields.append(field)

        if not missing_fields:
            continue

        if limit is not None and attempted_rows >= limit:
            break

        attempted_rows += 1
        location = row.to_dict()
        city = _normalize_text(location.get("city"), "Unknown city")
        country = _normalize_text(location.get("country"), "Unknown country")

        print(
            f"Enriching {city}, {country} — missing: "
            f"{', '.join(missing_fields)}"
        )

        try:
            enriched = enrich_location(location)
        except Exception as exc:
            failed_rows += 1
            print(f"Failed to enrich {city}: {exc}")
            continue

        row_updated = False

        for field in missing_fields:
            new_value = enriched.get(field)

            if field == "destination_description":
                if _destination_description_is_incomplete(new_value):
                    continue
            elif _enrichment_value_is_missing(new_value):
                continue

            df.at[index, field] = new_value
            row_updated = True

        if row_updated:
            updated_rows += 1
            print(f"Updated {city}.")
        else:
            print(f"No usable enrichment returned for {city}.")

    if updated_rows:
        df.to_csv(TRAVEL_LOCATIONS_FILE, index=False)
        clear_location_cache()

    result = {
        "attempted": attempted_rows,
        "updated": updated_rows,
        "failed": failed_rows,
    }

    print(
        "Destination enrichment complete. "
        f"Attempted: {attempted_rows}, "
        f"updated: {updated_rows}, "
        f"failed: {failed_rows}."
    )

    return result