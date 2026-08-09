GreenBookAI

Overview

GreenBookAI is an AI-assisted travel decision-support application developed as a graduate capstone project at Wentworth Institute of Technology.

The system transforms natural-language travel requests into ranked destination recommendations by combining explicit constraint filtering, semantic retrieval, deterministic scoring, live travel-data enrichment, and evidence-grounded natural-language explanations.

Rather than allowing a large language model to determine destination rankings, GreenBookAI separates recommendation computation from explanation generation. Destination ordering is produced by a two-stage deterministic ranking pipeline, while Gemini is used only after ranking to explain the resulting recommendations.

Key Features

Natural-language travel requests

Origin-aware trip recommendations

Explicit geographic and trip-type constraint filtering

Semantic destination retrieval using Jina embeddings

Cosine-similarity scoring

Persistent destination embedding cache

Two-stage deterministic recommendation scoring

Budget-aware trip evaluation

Five-year historical seasonal climate analysis

Current weather integration

Live Google Flights data through SerpAPI

Live lodging search and pricing through SerpAPI

Flight duration, connection, and layover analysis

GOV.UK international travel-advisory integration

Destination safety and attraction scoring

Live-data viability filtering

Automatic candidate replenishment

Automatic location discovery through Geoapify

Persistent storage of newly discovered destinations

Gemini-generated recommendation explanations

Deterministic explanation fallback

FastAPI backend

Streamlit web interface

Example Travel Request

I want a warm beach vacation for 5 nights in February.
My budget is $1,800 and safety is important.

Boston is used as the default starting destination in the current application.

Recommendation Pipeline

Natural-Language Travel Request
        |
        v
Request Parsing
        |
        v
Explicit Constraint Filtering
        |
        v
Semantic Retrieval
(Jina Embeddings + Cosine Similarity)
        |
        v
Preliminary Deterministic Scoring
        |
        v
Candidate Shortlist
        |
        v
Live / Historical Data Enrichment
  - Flights
  - Lodging
  - Current Weather
  - Historical Seasonal Climate
  - Travel Advisories
        |
        v
Final Deterministic Scoring
        |
        v
Live-Data Viability Filtering
        |
        v
Candidate Replenishment if Needed
        |
        v
Final Ranked Recommendations
        |
        v
Gemini Explanation Generation

Gemini does not determine destination order. It receives structured evidence only after ranking has been completed.

APIs and External Services

Credentials Required

Service

Purpose

Geoapify

Geocoding and automatic destination discovery

OpenWeather

Current weather information

SerpAPI

Live Google Flights and lodging information

Jina AI

Query and destination embeddings for semantic retrieval

Google Gemini

Natural-language recommendation explanations

No API Key Required

Service

Purpose

Open-Meteo

Historical climate observations

GOV.UK Travel Advice

International travel-advisory information

You must obtain credentials for the services in the first table for all application features to operate.

Important: Environment-variable names must exactly match the names referenced by the current application source. Never commit API keys or the .env file to a public repository.

Installation and Setup

Prerequisites

Install Python 3.12, Git, and pip.

Verify them with:

python --version
git --version
pip --version

1. Clone the Repository

git clone <repository-url>
cd GreenBookAI

Replace <repository-url> with the repository's Git URL.

2. Create a Virtual Environment

python -m venv .venv

Windows Git Bash

source .venv/Scripts/activate

Windows PowerShell

.venv\Scripts\Activate.ps1

macOS/Linux

source .venv/bin/activate

3. Install Dependencies

python -m pip install --upgrade pip
pip install -r requirements.txt

requirements.txt is the authoritative dependency list for the repository.

4. Configure API Credentials

Create a .env file in the project root.

The application requires credentials for Geoapify, OpenWeather, SerpAPI, Jina AI, and Gemini. The exact variable names must match those referenced by the current source code.

A typical configuration is:

GEOAPIFY_API_KEY=your_key_here
OPENWEATHER_API_KEY=your_key_here
SERPAPI_API_KEY=your_key_here
JINA_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here

If the current source uses different names, use the source-defined names instead.

Make sure .env is excluded by .gitignore.

Running the Application

GreenBookAI has two locally running components:

FastAPI backend

Streamlit frontend

Both should be running for the complete application.

Terminal 1 — Start FastAPI

From the project root with the virtual environment activated:

uvicorn app.main:app --reload

Backend:

http://127.0.0.1:8000

FastAPI interactive documentation:

http://127.0.0.1:8000/docs

Leave this terminal running.

Terminal 2 — Start Streamlit

Open a second terminal in the repository directory and activate the same virtual environment.

On Windows Git Bash:

source .venv/Scripts/activate

Then run:

streamlit run streamlit_app.py

Streamlit normally displays a local address similar to:

http://localhost:8501

Open that address in a browser and leave both terminals running.

Quick Start — Existing Windows Git Bash Installation

Terminal 1

source .venv/Scripts/activate
uvicorn app.main:app --reload

Terminal 2

source .venv/Scripts/activate
streamlit run streamlit_app.py

Stopping the Application

Press Ctrl+C in both terminals.

Then deactivate the virtual environment:

deactivate

Semantic Retrieval and Ranking

The user's travel request is embedded as a Jina query, while destination descriptions are represented as passage embeddings. Cosine similarity measures semantic alignment.

semantic_similarity = cosine(query_embedding, destination_embedding)

The first ranking stage combines explicit constraints, local destination attributes, trip-type compatibility, climate preference, budget information, safety, attraction value, and semantic similarity.

Shortlisted candidates are then enriched with live flight and lodging information, current weather, five-year historical seasonal climate data, and international travel advisories before deterministic reranking.

Final recommendations must also satisfy live flight and lodging viability requirements. If too few viable destinations remain, the candidate pool can be replenished.

Current Data

The primary destination inventory is stored in:

data/travel_locations.csv

The final capstone dataset contains:

199 destination records
17 fields

The inventory includes attributes used for filtering, semantic retrieval, scoring, enrichment, and travel planning.

Unknown locations can be discovered through Geoapify and persisted for later use.

Embedding Cache

Destination embeddings are stored in:

data/destination_embeddings.json

The cache reduces repeated embedding requests for destination descriptions that have already been processed.

Technology Stack

The project uses technologies including:

Python 3.12

FastAPI

Uvicorn

Streamlit

Pydantic

Pandas

NumPy

Requests

BeautifulSoup

python-dotenv

Jina AI

Google Gemini

SerpAPI

Install the repository-defined dependencies with:

pip install -r requirements.txt

Project Structure

GreenBookAI/
├── app/
│   └── main.py
├── assets/
│   ├── Background.gif
│   └── logo.png
├── data/
│   ├── destination_embeddings.json
│   └── travel_locations.csv
├── screenshots/
├── .env
├── .gitignore
├── requirements.txt
├── streamlit_app.py
└── README.md

Do not commit .env or API credentials to the repository.

Evaluation

The final capstone evaluation used nine completed scenario-based travel requests and produced 44 final recommendations.

The strongest observed behavior involved:

Explicit numeric budgets

Dates and trip durations

Positive travel categories

Supported geographic restrictions

The evaluation also identified limitations involving:

Negative preference interpretation

Relative preference-priority language

Lodging geographic validation

Accommodation classification

Missing travel-advisory states

Extremely long flight itineraries

These results evaluate the implemented prototype and do not establish that its rankings are objectively optimal or superior to other recommendation systems.

Known Limitations

Ranking weights are developer-defined rather than learned from user behavior.

Some natural-language exclusions are not consistently converted into hard constraints.

Relative priority statements do not always modify ranking weights.

External lodging results can require stronger geographic validation.

Accommodation-type filtering can misclassify some properties.

Travel-advisory information may be unavailable for some destinations.

Very long flight itineraries can remain viable when other destination characteristics score highly.

Static safety, attraction, and fallback cost attributes are prototype ranking values rather than validated real-time measurements.

Live flight and lodging information can change after a recommendation is generated.

Historical seasonal climate data provide historical context rather than a forecast.

Recommendation-job storage is not durable across backend restarts.

No labeled relevance dataset or baseline recommender was used to establish objective ranking superiority.

Future Work

Future improvements identified during evaluation include:

Explicit representation of negative preferences

Separation of hard constraints and soft preferences

Improved interpretation of preference-priority language

Geographic validation of lodging properties

Stronger accommodation-type validation

Explicit handling of unavailable travel-advisory evidence

Flight-practicality penalties relative to total trip duration

Sensitivity analysis for deterministic scoring weights

Persistent recommendation-job storage

More consistent external-service caching

User studies evaluating recommendation and explanation usefulness

Evaluation against independently judged destination relevance

Comparison of deterministic ranking with learned ranking methods if suitable interaction or relevance data become available

Development Status

GreenBookAI is a functional graduate capstone prototype developed at Wentworth Institute of Technology.

The completed system demonstrates how explicit constraints, semantic retrieval, deterministic decision rules, live travel information, historical climate evidence, and generative explanations can be combined in an inspectable travel recommendation architecture.

The project is intended as a decision-support prototype rather than a production travel-booking platform. Live travel information should be independently verified before making travel or purchasing decisions.