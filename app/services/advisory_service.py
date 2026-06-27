import re
import requests


GOVUK_INDEX_URL = "https://www.gov.uk/api/content/foreign-travel-advice"
GOVUK_API_BASE_URL = "https://www.gov.uk/api/content/foreign-travel-advice"
GOVUK_PAGE_BASE_URL = "https://www.gov.uk/foreign-travel-advice"


DOMESTIC_COUNTRIES = {
    "usa",
    "us",
    "u.s.",
    "u.s.a.",
    "united states",
    "united states of america",
}


def normalize_country_name(country_name):
    return re.sub(r"\s+", " ", country_name.strip().lower())


def get_country_slug_map():
    try:
        response = requests.get(GOVUK_INDEX_URL, timeout=10)

        if response.status_code != 200:
            return {}

        data = response.json()
        children = data.get("links", {}).get("children", [])

        slug_map = {}

        for child in children:
            title = child.get("title", "")
            base_path = child.get("base_path", "")

            if not title or not base_path:
                continue

            country = title.replace(" travel advice", "").strip()
            slug = base_path.split("/")[-1]

            slug_map[normalize_country_name(country)] = slug

        return slug_map

    except Exception as e:
        print("GOV.UK slug map error:", e)
        return {}


def map_govuk_status_to_level(alert_status):
    if not alert_status:
        return "Level 1"

    status_text = " ".join(alert_status).lower()

    if "avoid_all_travel" in status_text:
        return "Level 4"

    if "avoid_all_but_essential_travel" in status_text:
        return "Level 3"

    return "Level 2"


def map_level_to_text(level):
    level_text = {
        "Level 1": "Exercise normal precautions",
        "Level 2": "Exercise increased caution",
        "Level 3": "Reconsider travel / avoid all but essential travel",
        "Level 4": "Do not travel / avoid all travel",
    }

    return level_text.get(level, "Travel advisory available")


def get_govuk_advisory(country_name):
    country_key = normalize_country_name(country_name)

    if country_key in DOMESTIC_COUNTRIES:
        return {
            "country": country_name,
            "advisory_level": "Level 1",
            "advisory_text": "Domestic destination; no international travel advisory penalty applied",
            "risk_indicators": None,
            "date_issued": None,
            "url": None,
            "source": "Domestic",
            "latest_update": None
        }

    slug_map = get_country_slug_map()
    slug = slug_map.get(country_key)

    if not slug:
        return None

    api_url = f"{GOVUK_API_BASE_URL}/{slug}"
    response = requests.get(api_url, timeout=10)

    if response.status_code != 200:
        return None

    data = response.json()
    details = data.get("details", {})

    alert_status = details.get("alert_status", [])
    advisory_level = map_govuk_status_to_level(alert_status)
    advisory_text = map_level_to_text(advisory_level)

    return {
        "country": data.get("title", country_name).replace(" travel advice", "").strip(),
        "advisory_level": advisory_level,
        "advisory_text": advisory_text,
        "risk_indicators": ", ".join(alert_status) if alert_status else None,
        "date_issued": data.get("public_updated_at") or data.get("updated_at"),
        "url": f"{GOVUK_PAGE_BASE_URL}/{slug}",
        "source": "GOV.UK",
        "latest_update": details.get("change_description")
    }


def get_travel_advisories():
    """
    Preserved for compatibility with older code.
    GOV.UK works best by fetching individual countries.
    """
    return {"data": []}


def find_advisory_by_country(country_name):
    try:
        advisory = get_govuk_advisory(country_name)

        if advisory:
            return advisory

    except Exception as e:
        print("Travel advisory fetch error:", e)

    return {
        "country": country_name,
        "advisory_level": None,
        "advisory_text": "No travel advisory found or feed unavailable",
        "risk_indicators": None,
        "date_issued": None,
        "url": None,
        "source": None,
        "latest_update": None
    }


def calculate_advisory_penalty(advisory_level):
    penalties = {
        "Level 1": 0,
        "Level 2": -5,
        "Level 3": -15,
        "Level 4": -30
    }

    return penalties.get(advisory_level, 0)