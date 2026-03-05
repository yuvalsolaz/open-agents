from typing import Any, Optional

import httpx
from google.adk.tools import ToolContext
from geopy.geocoders import Nominatim

from gir_agent.config import GOOGLE_API_KEY


def locations_to_geo_json(locations):
    features = []
    for loc in locations:
        if loc is None:
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [loc.longitude, loc.latitude],
                },
                "properties": {
                    "address": loc.address,
                    "display_name": loc.raw.get("display_name"),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def geo_coding(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """
    Search OSM entities and return a GeoJSON feature collection.

    Args:
        query: A free text geographic search query.
    """
    geolocator = Nominatim(user_agent="gir-agent")
    try:
        locations = geolocator.geocode(
            query=query, exactly_one=False, timeout=10, geometry="geojson"
        )
        if not locations:
            locations = []
        geo_json = locations_to_geo_json(locations=locations)
        tool_context.state["user:geo_json"] = geo_json
        return geo_json
    except Exception as e:
        print(f"Error in geocoding: {str(e)}")
        return {"type": "FeatureCollection", "features": []}


def reverse_geocoding(
    latitude: float,
    longitude: float,
    radius_meters: int = 1500,
    max_results: int = 10,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """
    Find nearby places around a coordinate using Google Places API.

    Args:
        latitude: Coordinate latitude.
        longitude: Coordinate longitude.
        radius_meters: Search radius in meters.
        max_results: Maximum number of returned places.

    Returns:
        A dict containing the center point and nearby places.
    """
    if not GOOGLE_API_KEY:
        return {"error": "GOOGLE_API_KEY is not configured."}

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": max(1, int(radius_meters)),
        "key": GOOGLE_API_KEY,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        return {"error": f"Failed to call Google Places API: {str(e)}"}

    api_status = payload.get("status", "UNKNOWN_ERROR")
    if api_status not in {"OK", "ZERO_RESULTS"}:
        return {
            "error": "Google Places API returned an error.",
            "status": api_status,
            "message": payload.get("error_message"),
        }

    results = payload.get("results", [])[: max(1, int(max_results))]
    places = []
    for place in results:
        geometry = place.get("geometry", {}).get("location", {})
        places.append(
            {
                "name": place.get("name"),
                "address": place.get("vicinity") or place.get("formatted_address"),
                "place_id": place.get("place_id"),
                "location": {
                    "lat": geometry.get("lat"),
                    "lng": geometry.get("lng"),
                },
                "types": place.get("types", []),
                "rating": place.get("rating"),
                "user_ratings_total": place.get("user_ratings_total"),
                "open_now": (place.get("opening_hours") or {}).get("open_now"),
            }
        )

    output = {
        "center": {"lat": latitude, "lng": longitude},
        "radius_meters": max(1, int(radius_meters)),
        "count": len(places),
        "places": places,
    }

    if tool_context is not None and getattr(tool_context, "state", None) is not None:
        tool_context.state["user:reverse_geo_places"] = output

    return output
