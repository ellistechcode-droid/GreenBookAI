import os
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.llm_service import generate_ai_recommendation
from app.services.location_service import enrich_incomplete_locations
from app.services.recommendation_service import (
    get_recommendations,
    resolve_budget,
)

load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

RECOMMENDATION_JOBS = {}
RECOMMENDATION_JOBS_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("GreenBookAI backend starting.")
    yield
    print("GreenBookAI backend shutting down.")


app = FastAPI(
    title="GreenBookAI",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "project": "GreenBookAI",
        "status": "Running",
    }


@app.post("/maintenance/enrich")
def start_destination_enrichment(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=3, ge=1, le=10),
):
    background_tasks.add_task(enrich_incomplete_locations, limit)

    return {
        "status": "started",
        "message": (
            "Destination enrichment started in the background for "
            f"up to {limit} locations."
        ),
        "limit": limit,
    }


@app.get("/places/{city}")
def get_places(city: str):
    url = "https://api.geoapify.com/v1/geocode/search"

    params = {
        "text": city,
        "format": "json",
        "apiKey": GEOAPIFY_API_KEY,
    }

    response = requests.get(
        url,
        params=params,
        timeout=(3, 8),
    )
    response.raise_for_status()
    return response.json()


@app.get("/weather/{city}")
def get_weather(city: str):
    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "imperial",
    }

    response = requests.get(
        url,
        params=params,
        timeout=(3, 8),
    )
    response.raise_for_status()

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


def _set_job_progress(job_id, progress, stage):
    with RECOMMENDATION_JOBS_LOCK:
        job = RECOMMENDATION_JOBS.get(job_id)
        if not job:
            return

        job["progress"] = max(
            int(job.get("progress", 0)),
            min(int(progress), 99),
        )
        job["stage"] = str(stage)


def _run_recommendation_job(job_id, request_data):
    try:
        resolved_budget = resolve_budget(
            prompt=request_data["prompt"],
            budget=request_data.get("budget"),
        )

        _set_job_progress(job_id, 3, "Starting recommendation...")

        recommendations = get_recommendations(
            start_destination=request_data["start_destination"],
            prompt=request_data["prompt"],
            budget=resolved_budget,
            progress_callback=lambda progress, stage: _set_job_progress(
                job_id,
                progress,
                stage,
            ),
        )

        _set_job_progress(
            job_id,
            96,
            "Generating recommendation explanation...",
        )

        ai_recommendation = generate_ai_recommendation(
            user_prompt=request_data["prompt"],
            budget=resolved_budget,
            recommendations=recommendations,
        )

        result = {
            "user_prompt": request_data["prompt"],
            "start_destination": request_data["start_destination"],
            "budget": resolved_budget,
            "ai_recommendation": ai_recommendation,
            "recommendations": recommendations,
        }

        with RECOMMENDATION_JOBS_LOCK:
            RECOMMENDATION_JOBS[job_id].update({
                "status": "complete",
                "progress": 100,
                "stage": "Your recommendations are ready.",
                "result": result,
                "error": None,
            })

    except Exception as error:
        with RECOMMENDATION_JOBS_LOCK:
            RECOMMENDATION_JOBS[job_id].update({
                "status": "failed",
                "stage": "Recommendation failed.",
                "error": str(error),
            })


@app.post("/recommend/start")
def start_recommendation(request: TripRequest):
    job_id = str(uuid.uuid4())

    request_data = {
        "start_destination": request.start_destination,
        "prompt": request.prompt,
        "budget": request.budget,
    }

    with RECOMMENDATION_JOBS_LOCK:
        RECOMMENDATION_JOBS[job_id] = {
            "job_id": job_id,
            "status": "running",
            "progress": 0,
            "stage": "Queued...",
            "result": None,
            "error": None,
        }

    worker = threading.Thread(
        target=_run_recommendation_job,
        args=(job_id, request_data),
        daemon=True,
    )
    worker.start()

    return {
        "job_id": job_id,
        "status": "running",
        "progress": 0,
        "stage": "Queued...",
    }


@app.get("/recommend/status/{job_id}")
def recommendation_status(job_id: str):
    with RECOMMENDATION_JOBS_LOCK:
        job = RECOMMENDATION_JOBS.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Recommendation job not found",
            )
        return dict(job)


@app.post("/recommend")
def recommend_trip(request: TripRequest):
    """
    Backward-compatible synchronous endpoint.
    """
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