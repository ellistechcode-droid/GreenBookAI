from app.services.flight_service import get_flight_pricing
from app.services.lodging_service import get_lodging_pricing


def get_trip_pricing(
    origin,
    destination,
    nights,
    fallback_flight_cost,
    outbound_date,
    return_date,
):
    """
    Combines live flight and lodging pricing.

    Regional flight and CSV lodging estimates remain available as fallbacks.
    """
    flight = get_flight_pricing(
        origin=origin,
        destination=destination,
        outbound_date=outbound_date,
        return_date=return_date,
    )

    lodging = get_lodging_pricing(
        destination=destination,
        nights=nights,
        check_in_date=outbound_date,
        check_out_date=return_date,
        adults=2,
    )

    flight_total = (
        flight["total_price"]
        if flight["total_price"] is not None
        else fallback_flight_cost
    )

    estimated_total_cost = flight_total + lodging["lodging_total"]

    return {
        "flight": flight,
        "lodging": lodging,
        "flight_total": flight_total,
        "estimated_total_cost": round(estimated_total_cost, 2),
        "flight_fallback_used": flight["source"] == "fallback",
        "lodging_fallback_used": lodging["source"] == "csv_fallback",
        "fallback_used": (
            flight["source"] == "fallback"
            or lodging["source"] == "csv_fallback"
        ),
        "outbound_date": outbound_date,
        "return_date": return_date,
    }