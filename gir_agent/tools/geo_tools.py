
from google.adk.tools import ToolContext
from geopy.geocoders import Nominatim

def locations_to_geo_json(locations):
    features = []
    for loc in locations:
        if loc is None:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
            "type": "Point",
            "coordinates": [loc.longitude, loc.latitude]
            },
            "properties": {
                "address": loc.address,
                "display_name": loc.raw.get("display_name"),
                }
            })

    return {"type": "FeatureCollection","features": features}


# The function now accepts a LIST of subreddit names
def geo_coding(query: str, tool_context) -> list[str]:
    """
    Searches osm entities, return  a list of entities.

    Args:
        query: A free text geographic search query.

    Returns:
        A list of geo entities
    """
    geolocator = Nominatim(user_agent="gir-agent")
    try:
        locations = geolocator.geocode(query=query, exactly_one=False, timeout=10, geometry='geojson')
        if not locations:
            locations = []
        geo_json = locations_to_geo_json(locations=locations)
        tool_context.state['user:geo_json'] = geo_json
        return geo_json


    except Exception as e:
        print(f"Error in geocoding: {str(e)}")
        return []

