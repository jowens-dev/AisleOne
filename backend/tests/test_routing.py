import pytest
from unittest.mock import patch, MagicMock
from utils.routing import get_store_zip_code, geocode_zip_code, get_drive_distance_osrm
from api.app import calculate_travel_metrics

def test_get_store_zip_code():
    assert get_store_zip_code("90210", "Walmart") == "90212"
    assert get_store_zip_code("90210", "Target") == "90207"
    assert get_store_zip_code("invalid", "Walmart") == "invalid"

def test_geocode_zip_code():
    coords = geocode_zip_code("90210")
    assert coords is not None
    assert coords[0] is not None
    assert isinstance(coords[0], float)

@patch('requests.get')
def test_get_drive_distance_osrm_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "distance": 1609.34,  # 1 mile in meters
                "duration": 60.0       # 1 minute in seconds
            }
        ]
    }
    mock_get.return_value = mock_response
    
    # Temporarily disable time.sleep to speed up tests
    with patch('time.sleep'):
        dist, dur = get_drive_distance_osrm((-118.4, 34.0), (-118.3, 34.1))
        assert dist == 1.0
        assert dur == 1.0

@patch('requests.get')
def test_get_drive_distance_osrm_failure(mock_get):
    mock_get.side_effect = Exception("OSRM offline")
    dist, dur = get_drive_distance_osrm((-118.4, 34.0), (-118.3, 34.1))
    assert dist is None
    assert dur is None

@patch('utils.routing.get_drive_distance_osrm')
def test_calculate_travel_metrics_fallback_behavior(mock_osrm):
    # Simulate OSRM failure to trigger legacy fallback
    mock_osrm.return_value = (None, None)
    
    metrics = calculate_travel_metrics("90210", ["Walmart"])
    assert metrics is not None
    assert "total_distance" in metrics
    assert "total_travel_cost" in metrics
    assert metrics["total_distance"] > 0
