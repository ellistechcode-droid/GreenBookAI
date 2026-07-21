import base64
from pathlib import Path
from typing import Any

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000/recommend"

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

        @media (max-width: 900px) {{
            .block-container {{
                padding-top: 1.5rem;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def request_recommendations(
    start_destination: str,
    prompt: str,
    budget: float | None,
) -> dict[str, Any]:
    payload = {
        "start_destination": start_destination.strip(),
        "prompt": prompt.strip(),
        "budget": budget,
    }

    response = requests.post(
        API_URL,
        json=payload,
        timeout=180,
    )

    response.raise_for_status()
    return response.json()


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
            use_container_width=True,
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

        avoid_prompt = st.text_area(
            "Preferences to avoid",
            placeholder=(
                "Example: Cold weather, hostels, long layovers, "
                "or overly crowded destinations."
            ),
            height=100,
        )

        budget_input = st.number_input(
            "Maximum budget in USD",
            min_value=0.0,
            value=2500.0,
            step=100.0,
        )

        submitted = st.form_submit_button(
            "Find My Trip",
            use_container_width=True,
            type="primary",
        )


if submitted:
    if not start_destination.strip():
        st.error("Enter a starting city.")

    elif not trip_prompt.strip():
        st.error("Describe the type of trip you want.")

    else:
        combined_prompt = trip_prompt.strip()

        if avoid_prompt.strip():
            combined_prompt += (
                "\n\nThe traveler would prefer to avoid: "
                + avoid_prompt.strip()
                + ". Treat these as preferences rather than "
                "guaranteed exclusions."
            )

        progress = st.progress(
            0,
            text="Understanding your trip request...",
        )

        try:
            progress.progress(
                20,
                text="Understanding your trip request...",
            )

            progress.progress(
                40,
                text="Searching destinations...",
            )

            progress.progress(
                55,
                text="Checking weather and travel advisories...",
            )

            progress.progress(
                70,
                text="Finding flight and lodging estimates...",
            )

            result = request_recommendations(
                start_destination=start_destination,
                prompt=combined_prompt,
                budget=budget_input if budget_input > 0 else None,
            )

            progress.progress(
                90,
                text="Generating your AI recommendation...",
            )

            progress.progress(
                100,
                text="Your recommendations are ready.",
            )

            st.success(
                "GreenBookAI found your recommendations."
            )

            st.subheader("AI Recommendation")
            st.write(
                result.get(
                    "ai_recommendation",
                    "No AI recommendation was returned.",
                )
            )

            st.subheader("Recommendation Data")

            recommendations = result.get(
                "recommendations",
                [],
            )

            if recommendations:
                st.json(recommendations)
            else:
                st.warning(
                    "The backend returned no destinations."
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
                "The recommendation request took too long. "
                "Try again or check the backend terminal for errors."
            )

        except requests.exceptions.HTTPError as error:
            st.error(
                f"The backend returned an error: {error}"
            )

        except requests.exceptions.RequestException as error:
            st.error(
                "Something went wrong while contacting the backend: "
                f"{error}"
            )