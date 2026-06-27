GreenBookAI is a travel recommendation application being developed as part of a graduate capstone project at Wentworth Institute of Technology. The system attempts to identify destinations that align with a user's vacation preferences by combining weather information, historical climate patterns, estimated travel costs, attraction ratings, safety scores, and travel advisory data.

The current implementation is built using FastAPI and Python. User input is presently separated into three fields consisting of a starting location, a natural language travel prompt, and a budget. The travel prompt is analyzed to extract information such as trip duration, preferred travel month, desired climate conditions, and vacation type. For example, the system currently expects an input structure similar to the following:


{
   "start_destination": "Boston",
    "prompt": "I want a warm beach vacation for 4 nights in January",
    "budget": 1500
}


Destinations are stored within a CSV dataset containing destination metadata such as country, region, climate tags, nightly lodging estimates, safety ratings, attraction ratings, and geographic coordinates. Current weather conditions are obtained through the OpenWeather API, while historical monthly weather estimates are retrieved from the Open-Meteo Archive API. These data sources allow recommendations to consider both present conditions and expected seasonal trends associated with a user's intended travel month.

Recommendations are generated through a weighted scoring methodology that evaluates trip type compatibility, current weather suitability, seasonal weather compatibility, estimated travel costs, safety scores, attraction ratings, and travel advisory penalties. Destinations that significantly exceed the user's budget are filtered prior to scoring, and the five highest-ranked recommendations are returned alongside explanations describing why each location was selected.

GreenBookAI currently utilizes Python 3.12, FastAPI, Uvicorn, Pandas, NumPy, Pydantic, Requests, BeautifulSoup4, and python-dotenv. Version control is maintained using Git and GitHub. At its current stage, GreenBookAI should be considered a prototype intended to investigate travel recommendation methodologies and the integration of multiple travel-related data sources into a single decision-support application. Future work may include improved flight pricing estimates, expanded destination inventories, additional travel advisory integrations, and machine learning techniques capable of refining recommendation rankings.
