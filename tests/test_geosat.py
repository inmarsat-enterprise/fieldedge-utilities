import pytest
from fieldedge_utilities.geosat import geo_closest, geo_azimuth, geo_elevation


test_locs = {
    'Ottawa USCA': {
        'lat': 45.36886,
        'lon': -75.75179,
        'alt': 125,
        'exclude': [],
        'closest': 'USCA',
        'az': 214,
        'el': 32,
    },
    'Carlsbad': {
        'lat': 33.12706,
        'lon': -117.26689,
        'alt': 50,
        'exclude': ['USCA'],
        'closest': 'AMER',
        'az': 147,
        'el': 46,
    },
    'Mexico': {
        'lat': 19.37058,
        'lon': -99.16217,
        'alt': 2240,
        'exclude': [],
        'closest': 'AMER',
        'az': 176,
        'el': 67,
    },
    'Sao Paolo AORW': {
        'lat': -23.43216,
        'lon': -46.47483,
        'alt': 2461,
        'exclude': [],
        'closest': 'AORW',
        'az': 342,
        'el': 61,
    },
    'Sao Paolo': {
        'lat': -23.43216,
        'lon': -46.47483,
        'alt': 2461,
        'exclude': ['AORW'],
        'closest': 'AMER',
        'az': 288,
        'el': 27,
    },
    'London': {
        'lat': 51.52047,
        'lon': -0.08669,
        'alt': 24,
        'exclude': [],
        'closest': 'EMEA',
        'az': 149,
        'el': 27,
    },
    'Singapore': {
        'lat': 1.33717,
        'lon': 103.84917,
        'alt': 15,
        'exclude': [],
        'closest': 'IOE',
        'az': 266,
        'el': 66,
    },
    'Tokyo': {
        'lat': 35.62149,
        'lon': 139.77630,
        'alt': 40,
        'exclude': [],
        'closest': 'APAC',
        'az': 174,
        'el': 48,
    }
}


@pytest.mark.parametrize('test_case,test_params', test_locs.items())
def test_geosat(test_case, test_params):
    lat = test_params['lat']
    lon = test_params['lon']
    exclude = test_params['exclude']
    expected_closest = test_params['closest']
    expected_az = test_params['az']
    expected_el = test_params['el']
    closest = geo_closest(lat, lon, exclude)
    assert closest.name == expected_closest
    az = geo_azimuth(closest.value, lat, lon)
    assert az == expected_az
    el = geo_elevation(closest.value, lat, lon)
    assert el == expected_el
