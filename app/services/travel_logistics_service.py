from datetime import date

from app.services.flight_service import get_flight_pricing
from app.services.lodging_service import get_lodging_pricing


def _validated_nights(outbound_date, return_date, requested_nights):
    """
    Enforces one source of truth for itinerary length.

    Hotel check-in is the outbound-flight date and check-out is the return-flight
    date. The date difference determines the billable hotel-night count.
    """
    try:
        calculated = (
            date.fromisoformat(return_date)
            - date.fromisoformat(outbound_date)
        ).days
    except (TypeError, ValueError):
        calculated = requested_nights

    if not isinstance(calculated, int) or calculated <= 0:
        calculated = requested_nights

    return int(calculated)


def get_trip_pricing(
    origin,
    destination,
    nights,
    fallback_flight_cost,
    outbound_date,
    return_date,
    budget=None,
):
    """
    Combines flight and lodging pricing using one validated itinerary window.
    """
    validated_nights = _validated_nights(
        outbound_date,
        return_date,
        nights,
    )

    flight = get_flight_pricing(
        origin=origin,
        destination=destination,
        outbound_date=outbound_date,
        return_date=return_date,
    )

    flight_total = (
        flight["total_price"]
        if flight["total_price"] is not None
        else fallback_flight_cost
    )

    hotel_budget_available = None
    if isinstance(budget, (int, float)) and budget > 0:
        hotel_budget_available = max(
            0.0,
            float(budget) - float(flight_total),
        )

    lodging = get_lodging_pricing(
        destination=destination,
        nights=validated_nights,
        check_in_date=outbound_date,
        check_out_date=return_date,
        adults=2,
        max_total_budget=hotel_budget_available,
    )

    estimated_total_cost = flight_total + lodging["lodging_total"]

    return {
        "flight": flight,
        "lodging": lodging,
        "flight_total": flight_total,
        "hotel_budget_available": (
            round(hotel_budget_available, 2)
            if hotel_budget_available is not None
            else None
        ),
        "estimated_total_cost": round(estimated_total_cost, 2),
        "flight_fallback_used": flight["source"] == "fallback",
        "lodging_fallback_used": lodging["source"] == "csv_fallback",
        "fallback_used": (
            flight["source"] == "fallback"
            or lodging["source"] == "csv_fallback"
        ),
        "outbound_date": outbound_date,
        "return_date": return_date,
        "hotel_check_in_date": outbound_date,
        "hotel_check_out_date": return_date,
        "requested_nights": nights,
        "validated_nights": validated_nights,
        "dates_consistent": validated_nights == int(nights),
    }