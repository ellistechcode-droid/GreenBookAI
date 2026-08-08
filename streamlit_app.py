import base64
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st

API_BASE_URL = "http://127.0.0.1:8000"
START_RECOMMENDATION_URL = f"{API_BASE_URL}/recommend/start"

LOGO_PATH = Path("assets/logo.png")
BACKGROUND_PATH = Path("assets/Background.gif")

st.set_page_config(
    page_title="GreenBookAI",
    page_icon=str(LOGO_PATH),
    layout="wide",
)


def set_animated_background(background_path: Path) -> None:
    """Set an animated GIF as the Streamlit page background."""

    if not background_path.exists():
        st.warning(
            f"Background image was not found at: {background_path}"
        )
        return

    encoded_background = base64.b64encode(
        background_path.read_bytes()
    ).decode("utf-8")

    st.markdown(
        f"""
        <style>
        .stApp {{
            background:
                linear-gradient(
                    rgba(4, 9, 13, 0.80),
                    rgba(4, 9, 13, 0.90)
                ),
                url("data:image/gif;base64,{encoded_background}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}

        [data-testid="stHeader"] {{
            background: transparent;
        }}

        .block-container {{
            max-width: 1500px;
            padding-top: 3rem;
            padding-bottom: 4rem;
        }}

        [data-testid="stHorizontalBlock"] {{
            align-items: flex-start;
        }}

        [data-testid="column"] {{
            align-self: flex-start;
        }}

        [data-testid="stForm"] {{
            background: rgba(8, 14, 20, 0.82);
            border: 1px solid rgba(120, 255, 170, 0.24);
            border-radius: 22px;
            padding: 2rem;
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.40);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
        }}

        [data-baseweb="input"] > div,
        [data-baseweb="textarea"] > div {{
            background-color: rgba(20, 25, 33, 0.90);
            border-radius: 14px;
        }}

        [data-testid="stFormSubmitButton"] button {{
            background: linear-gradient(
                90deg,
                #33d6a6,
                #b8ed52
            );
            color: #06110d;
            border: none;
            border-radius: 14px;
            min-height: 3.2rem;
            font-size: 1.05rem;
            font-weight: 750;
            transition:
                transform 0.2s ease,
                filter 0.2s ease,
                box-shadow 0.2s ease;
        }}

        [data-testid="stFormSubmitButton"] button:hover {{
            color: #06110d;
            border: none;
            filter: brightness(1.08);
            transform: translateY(-2px);
            box-shadow: 0 10px 24px rgba(82, 230, 157, 0.22);
        }}

        h1, h2, h3, p, label {{
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.72);
        }}

        [data-testid="stImage"] img {{
            opacity: 0.82;
            border-radius: 22px;
            transition:
                opacity 0.25s ease,
                transform 0.25s ease;
        }}

        [data-testid="stImage"] img:hover {{
            opacity: 0.92;
            transform: scale(1.01);
        }}

        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] em {{
            font-family: Arial, Helvetica, sans-serif !important;
            letter-spacing: normal !important;
            word-spacing: normal !important;
            font-kerning: normal !important;
        }}

        @media (max-width: 900px) {{
            .block-container {{
                padding-top: 1.5rem;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def start_recommendation_job(
    start_destination: str,
    prompt: str,
    budget: float | None,
) -> str:
    payload = {
        "start_destination": start_destination.strip(),
        "prompt": prompt.strip(),
        "budget": budget,
    }

    response = requests.post(
        START_RECOMMENDATION_URL,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    job_id = data.get("job_id")

    if not job_id:
        raise RuntimeError(
            "The backend did not return a recommendation job ID."
        )

    return job_id


def wait_for_recommendation(
    job_id: str,
    progress,
) -> dict[str, Any]:
    """Polls real backend progress and updates the Streamlit progress bar."""
    status_url = f"{API_BASE_URL}/recommend/status/{job_id}"

    while True:
        response = requests.get(
            status_url,
            timeout=15,
        )
        response.raise_for_status()
        job = response.json()

        percent = int(job.get("progress", 0))
        percent = max(0, min(percent, 100))
        stage = str(job.get("stage") or "Working...")

        progress.progress(
            percent,
            text=f"{stage} — {percent}%",
        )

        status = job.get("status")

        if status == "complete":
            result = job.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(
                    "The recommendation job completed without a valid result."
                )
            return result

        if status == "failed":
            raise RuntimeError(
                job.get("error")
                or "The recommendation job failed."
            )

        time.sleep(0.5)


def format_ai_recommendation(text: str) -> str:
    """Prepares AI recommendation text for safe Streamlit Markdown rendering."""
    if not text:
        return "No AI recommendation was returned."

    return text.replace("$", r"\$")


set_animated_background(BACKGROUND_PATH)

left_column, right_column = st.columns(
    [1.05, 1.35],
    gap="large",
    vertical_alignment="top",
)

with left_column:
    if LOGO_PATH.exists():
        st.image(
            str(LOGO_PATH),
            width="stretch",
        )
    else:
        st.warning(
            f"Logo image was not found at: {LOGO_PATH}"
        )

with right_column:
    with st.form("trip_search_form"):
        start_destination = st.text_input(
            "Starting city",
            value="Boston",
            placeholder="Example: Boston",
        )

        trip_prompt = st.text_area(
            "Describe your ideal trip",
            placeholder=(
                "Example: I want a five-night warm beach vacation "
                "with good food and nightlife."
            ),
            height=130,
        )

        budget_input = st.number_input(
            "Maximum budget in USD (optional if included in prompt)",
            min_value=0.0,
            value=None,
            step=100.0,
            placeholder="Example: 2500",
        )

        submitted = st.form_submit_button(
            "Find My Trip",
            width="stretch",
            type="primary",
        )

if submitted:
    if not start_destination.strip():
        st.error("Enter a starting city.")

    elif not trip_prompt.strip():
        st.error("Describe the type of trip you want.")

    else:
        combined_prompt = trip_prompt.strip()

        progress = st.progress(
            0,
            text="Queued... — 0%",
        )

        try:
            job_id = start_recommendation_job(
                start_destination=start_destination,
                prompt=combined_prompt,
                budget=(
                    budget_input
                    if budget_input is not None and budget_input > 0
                    else None
                ),
            )

            result = wait_for_recommendation(
                job_id=job_id,
                progress=progress,
            )

            st.success(
                "GreenBookAI found your recommendations."
            )

            st.subheader("AI Recommendation")

            ai_recommendation = format_ai_recommendation(
                result.get(
                    "ai_recommendation",
                    "No AI recommendation was returned.",
                )
            )

            st.markdown(ai_recommendation)

            st.subheader("Recommendation Data")

            recommendations = result.get(
                "recommendations",
                [],
            )

            if recommendations:
                st.json(recommendations)
            else:
                st.warning(
                    "The backend returned no viable destinations."
                )

            with st.expander("Full API response"):
                st.json(result)

        except requests.exceptions.ConnectionError:
            st.error(
                "GreenBookAI could not connect to the FastAPI backend. "
                "Make sure Uvicorn is running on port 8000."
            )

        except requests.exceptions.Timeout:
            st.error(
                "A GreenBookAI network request timed out. "
                "Check the backend terminal for errors."
            )

        except requests.exceptions.HTTPError as error:
            st.error(
                f"The backend returned an error: {error}"
            )

        except (requests.exceptions.RequestException, RuntimeError) as error:
            st.error(
                "Something went wrong while generating recommendations: "
                f"{error}"
            )