GreenBookAI

GreenBookAI is a context-aware travel recommendation system built with FastAPI. The application recommends travel destinations based on a user's starting location, budget, trip length, travel preferences, estimated cost, safety score, attraction score, and live weather data.

Current Features
Recommend destinations based on a natural language prompt
Use starting location to estimate flight cost
Extract trip length from prompts such as "4 nights" or "7 days"
Estimate total trip cost using flight cost and nightly cost
Pull live weather data from OpenWeather
Adjust scores based on weather conditions
Apply safety and attraction scores
Filter out weaker candidates before making weather API calls
Return the top 5 destination recommendations
Provide explanation notes for each recommendation

Requirements

Install the required packages with:

pip install -r requirements.txt

Main packages used:

FastAPI
Uvicorn
Requests
Pandas
Python-dotenv
Pydantic
API Keys Required

This project uses external APIs. You will need to create your own API keys and store them in a .env file.

OpenWeather API

Used for live weather data.

Sign up here:

https://openweathermap.org/api
Geoapify API

Used for location/place lookup.

Sign up here:

https://www.geoapify.com/
Environment File Setup

Create a .env file in the main project folder:

GEOAPIFY_API_KEY=your_geoapify_key_here
OPENWEATHER_API_KEY=your_openweather_key_here

Do not upload your .env file to GitHub.

Running the Application

Start the FastAPI server with:

python -m uvicorn app.main:app --reload

Then open:

http://127.0.0.1:8000

To test the API in Swagger Docs, open:

http://127.0.0.1:8000/docs
Available Endpoints
Root Endpoint
GET /

Returns the project status.

Example response:

{
  "project": "GreenBookAI",
  "status": "Running"
}
Places Endpoint
GET /places/{city}

Uses Geoapify to search for location information about a city.

Example:

http://127.0.0.1:8000/places/Miami
Weather Endpoint
GET /weather/{city}

Uses OpenWeather to return current weather data.

Example:

http://127.0.0.1:8000/weather/Miami
Recommendation Endpoint
POST /recommend

Generates the top 5 destination recommendations.

Example request:

{
  "start_destination": "Boston",
  "prompt": "I want a warm beach vacation for 4 nights",
  "budget": 1500
}

Example output includes:

destination
country
region
trip type
score
estimated total cost
estimated flight cost
estimated nightly cost
safety score
attraction score
current temperature
current weather condition
explanation reasons
How Recommendations Work

GreenBookAI currently uses a weighted scoring system. It considers:

Whether the destination matches the requested trip type
Whether the weather matches the user's climate preference
Whether the estimated trip cost fits the user's budget
Safety score
Attraction score
Rain or storm conditions from live weather data

The system filters weaker candidates before making weather API calls, then returns only the top 5 ranked destinations.

Current Limitations
Flight costs are estimated using region-based values, not live ticket prices.
Nightly hotel costs are estimated from the destination dataset.
Safety and attraction scores are currently prototype values.
The destination list currently comes from data/destinations.csv.
Future versions may use APIs for destination discovery, seasonal weather, travel advisories, health notices, and improved cost estimation.
Planned Improvements
Add seasonal and historical weather analysis using Open-Meteo
Add CDC Travel Health Notices for health-risk awareness
Add U.S. State Department Travel Advisories for safety/risk indicators
Improve flight and hotel cost estimation
Explore API-generated destination discovery
Add a frontend dashboard
Add more explainable scoring details
Explore KNN for final recommendation refinement