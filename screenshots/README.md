# GreenBookAI

## Overview

GreenBookAI is an AI-powered travel recommendation application developed as part of a graduate capstone project at Wentworth Institute of Technology. The system recommends vacation destinations by combining real-time travel information, historical climate data, travel advisories, safety metrics, estimated trip costs, flight logistics, and destination characteristics into a single recommendation engine.

Unlike traditional travel search engines that primarily filter destinations, GreenBookAI evaluates multiple contextual factors simultaneously to recommend destinations that best align with a traveler's preferences.

---

## Current Features

- Natural language travel requests
- Origin-aware trip recommendations
- Automatic location discovery
- Persistent location storage
- Real-time weather integration
- Historical seasonal climate analysis
- International travel advisory integration
- Budget-aware recommendations
- Safety scoring
- Destination attraction scoring
- Google Flights connectivity through SerpAPI
- Modular service-oriented backend architecture

---

## Example Request

```json
{
    "start_destination": "Boston",
    "prompt": "I want a warm beach vacation for 5 nights in February. Safety is important.",
    "budget": 1800
}
```

---

## Recommendation Methodology

The current recommendation engine uses a weighted scoring algorithm:

```text
Recommendation Score =
Trip Type Match
+ Current Weather Match
+ Historical Seasonal Weather Match
+ Budget Compatibility
+ Safety Score
+ Destination Attraction Score
− Travel Advisory Penalty
```

Each destination is evaluated against the user's natural language request. The recommendation engine currently considers trip type compatibility, preferred climate, current weather, historical weather during the intended travel month, estimated trip cost, safety score, destination attraction score, and travel advisories.

Destinations that significantly exceed the user's budget are filtered before scoring. The five highest-ranked destinations are returned with explanations describing why each location was selected.

---

## System Architecture

- **Recommendation Service**
  - Coordinates the recommendation pipeline
  - Combines all supporting services
  - Calculates destination rankings

- **Location Service**
  - Automatic location discovery
  - Persistent location storage
  - Dataset caching
  - Candidate location retrieval

- **Weather Service**
  - Current weather retrieval
  - Historical seasonal weather analysis

- **Advisory Service**
  - Travel advisory retrieval
  - Travel risk scoring

- **Travel Logistics Service**
  - Google Flights integration through SerpAPI
  - Flight pricing
  - Flight duration
  - Travel practicality analysis
  - Planned hotel pricing

---

## APIs Required

To run the full version of GreenBookAI, create API keys for the following services:

| API | Purpose | Required Environment Variable |
|---|---|---|
| Geoapify | Geocoding and automatic location discovery | `GEOAPIFY_API_KEY` |
| OpenWeather | Current weather conditions | `OPENWEATHER_API_KEY` |
| SerpAPI | Google Flights data and future hotel search | `SERPAPI_API_KEY` |
| GOV.UK Travel Advice | Travel advisory data | No key required |
| Open-Meteo Archive API | Historical seasonal weather data | No key required |

Create a `.env` file in the project root:

```env
GEOAPIFY_API_KEY=your_geoapify_key_here
OPENWEATHER_API_KEY=your_openweather_key_here
SERPAPI_API_KEY=your_serpapi_key_here
```

---

## Technologies and Packages

GreenBookAI uses Python 3.12 and the following packages:

```text
fastapi
uvicorn
pandas
numpy
pydantic
requests
beautifulsoup4
python-dotenv
```

Install the dependencies with:

```bash
pip install fastapi uvicorn pandas numpy pydantic requests beautifulsoup4 python-dotenv
```

If using a `requirements.txt` file, install with:

```bash
pip install -r requirements.txt
```

---

## Running the Application

From the project root, start the FastAPI server with:

```bash
uvicorn app.main:app --reload
```

Then open the interactive API documentation at:

```text
http://127.0.0.1:8000/docs
```

Use the `/recommend` endpoint to test trip recommendations.

---

## Current Data Source

Destination and location data are stored in:

```text
data/travel_locations.csv
```

The dataset includes fields such as:

- City
- Country
- Region
- Trip type
- Climate tag
- Estimated nightly cost
- Safety score
- Attraction score
- Latitude
- Longitude

When a starting location is not found in the dataset, the Location Service can discover it using Geoapify and append it to the CSV for future use.

---

## Recent Improvements

Recent development milestones include:

- Created a centralized Location Service for location management
- Implemented automatic discovery of unknown locations using Geoapify
- Added persistent storage of newly discovered locations
- Implemented dataset caching for improved performance
- Developed a modular Travel Logistics Service
- Connected GreenBookAI to Google Flights data through SerpAPI
- Added international travel advisory scoring
- Refactored the application into a modular service-oriented architecture

---

## Future Enhancements

Planned improvements include:

- Live hotel pricing
- Flight practicality filtering based on travel duration and number of connections
- Automatic airport code discovery and storage
- Dynamic attraction scoring using live attraction data
- More detailed travel advisory explanations, including affected regions and traveler-specific guidance
- Expanded destination inventory
- Interactive web-based user interface
- Transition from the current weighted scoring algorithm to a K-Nearest Neighbors recommendation model

In the planned KNN implementation, the user's natural language prompt will be transformed into a structured, prompt-generated ideal trip profile. Candidate destinations will then be compared against that profile using similarity distance to recommend the destinations that most closely match the user's travel preferences.

---

## Development Status

GreenBookAI is an active graduate capstone project currently under development. The application demonstrates how multiple real-time travel data sources can be integrated into a unified recommendation engine while providing a scalable architecture for future machine learning enhancements and intelligent travel planning capabilities.