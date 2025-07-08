
from geopy.geocoders import Nominatim

# The function now accepts a LIST of subreddit names
def geo_coding(query: str, ) -> list[str]:
    """
    Searches osm entities, return  a list of entities.

    Args:
        query: A free text geographic search query.

    Returns:
        A list of geo entities
    """
    geolocator = Nominatim(user_agent="gir-agent")
    try:
        entities = geolocator.geocode(query=query, exactly_one=False, timeout=10, geometry='geojson')
        if not entities:
            return []
        results = "\n".join([f"{l.raw['name']} : {l.raw['addresstype']}" for l in entities])
        print(f"entities:{results}")       
        return results


    except Exception as e:
        print(f"Error in geocoding: {str(e)}")
        return []

