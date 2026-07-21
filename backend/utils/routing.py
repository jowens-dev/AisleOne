import pgeocode
import requests
import time
from typing import Tuple, Optional

# Global cache for resolved coordinates to optimize repetitive requests
_coords_cache = {}

# Lazy-loaded geocoder Nominatim instance
_geocoder = None

def get_geocoder():
    global _geocoder
    if _geocoder is None:
        _geocoder = pgeocode.Nominatim('us')
    return _geocoder

def get_store_zip_code(user_zip: str, store_name: str) -> str:
    """Deterministically map a store to a nearby zip code based on the user's zip code."""
    try:
        # Standardize store name to match our offsets mapping
        # E.g. "Sams Club" vs "Sam's Club"
        norm_store = store_name.replace("'", "").replace(" ", "")
        
        # Parse zip code as integer to apply offset
        zip_int = int(user_zip)
    except Exception:
        return user_zip

    offsets = {
        "Walmart": 2,
        "Target": -3,
        "Kroger": 1,
        "Safeway": -1,
        "Costco": 5,
        "SamsClub": -4
    }
    
    offset = offsets.get(norm_store, 0)
    store_zip_int = zip_int + offset
    return f"{store_zip_int:05d}"

def geocode_zip_code(zip_code: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Resolve zip code to (longitude, latitude) tuple using pgeocode.
    Returns (None, None) on failure or if coordinates are not found.
    """
    if zip_code in _coords_cache:
        return _coords_cache[zip_code]

    try:
        nomi = get_geocoder()
        res = nomi.query_postal_code(zip_code)
        
        import pandas as pd
        if pd.notna(res.latitude) and pd.notna(res.longitude):
            coords = (float(res.longitude), float(res.latitude))
            _coords_cache[zip_code] = coords
            return coords
    except Exception as e:
        print(f"pgeocode resolution failed for zip code {zip_code}: {e}")
        
    return None, None

def get_drive_distance_osrm(origin_coords: Tuple[float, float], dest_coords: Tuple[float, float]) -> Tuple[Optional[float], Optional[float]]:
    """
    Queries OSRM driving API to calculate distance and duration.
    origin_coords: (longitude, latitude)
    dest_coords: (longitude, latitude)
    Returns (distance_miles, duration_minutes) or (None, None) on error.
    """
    coords_string = f"{origin_coords[0]},{origin_coords[1]};{dest_coords[0]},{dest_coords[1]}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_string}?overview=false"
    
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
            # Convert meters to miles
            distance_miles = data["routes"][0]["distance"] * 0.000621371
            # Convert seconds to minutes
            duration_minutes = data["routes"][0]["duration"] / 60
            
            # Rate limit throttling for public OSRM API (1 requests/sec limit)
            time.sleep(1)
            
            return round(distance_miles, 2), round(duration_minutes, 2)
    except Exception as e:
        print(f"OSRM request failed, triggering fallback: {e}")
        
    return None, None
