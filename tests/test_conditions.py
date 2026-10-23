"""Tests for user.current_json_conditions."""
import json
import os
import sqlite3
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import user.current_json_conditions as c

T = c.DEFAULT_THRESHOLDS


class FakeManager:
    """A database manager over an in-memory sqlite table shaped like weewx-nws's."""

    table_name = 'archive'

    def __init__(self, rows):
        self.connection = sqlite3.connect(':memory:')
        self.connection.execute('CREATE TABLE archive (interval INTEGER, startTime REAL, endTime REAL, generatedTime REAL, iconUrl TEXT)')
        self.connection.executemany('INSERT INTO archive VALUES (?, ?, ?, ?, ?)', rows)

    def getSql(self, sql, args):
        return self.connection.execute(sql, args).fetchone()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()


class TestPrecipitation(unittest.TestCase):

    def test_lightning(self):
        self.assertEqual(211, c.from_sensors_precipitation({'temperature': 25}, T, lightning_count=3))
        self.assertEqual(201, c.from_sensors_precipitation({'temperature': 25, 'rainrate': 4}, T, lightning_count=1))
        self.assertIsNone(c.from_sensors_precipitation({'temperature': 25}, T, lightning_count=0))

    def test_rain_intensity(self):
        self.assertEqual(500, c.from_sensors_precipitation({'temperature': 15, 'rainrate': 1.0}, T))
        self.assertEqual(503, c.from_sensors_precipitation({'temperature': 15, 'rainrate': 2.5}, T))
        self.assertEqual(504, c.from_sensors_precipitation({'temperature': 15, 'rainrate': 10}, T))
        # Without a rate, the hour's rain stands in for it.
        self.assertEqual(503, c.from_sensors_precipitation({'temperature': 15, 'rain': 3.0}, T))

    def test_snow_and_mix(self):
        self.assertEqual(601, c.from_sensors_precipitation({'temperature': -2, 'rainrate': 1}, T))
        self.assertEqual(601, c.from_sensors_precipitation({'temperature': 0, 'rainrate': 1}, T))
        self.assertEqual(616, c.from_sensors_precipitation({'temperature': 1.5, 'rainrate': 1}, T))

    def test_fog_and_mist(self):
        fog = {'temperature': 8, 'dewpoint': 7.6, 'humidity': 98, 'windspeed': 1}
        self.assertEqual(741, c.from_sensors_precipitation(fog, T))
        self.assertEqual(701, c.from_sensors_precipitation(dict(fog, humidity=95), T))
        self.assertIsNone(c.from_sensors_precipitation(dict(fog, windspeed=6), T), 'Too windy for fog.')
        self.assertIsNone(c.from_sensors_precipitation(dict(fog, dewpoint=5), T), 'Too dry.')

    def test_nothing(self):
        self.assertIsNone(c.from_sensors_precipitation({'temperature': 20, 'humidity': 50, 'rainrate': 0, 'rain': 0}, T))
        self.assertIsNone(c.from_sensors_precipitation({}, T))
        self.assertIsNone(c.from_sensors_precipitation({'temperature': 'warm'}, T))


class TestClouds(unittest.TestCase):

    def test_ratios(self):
        self.assertEqual(800, c.from_sensors_clouds(800, 900, T))
        self.assertEqual(801, c.from_sensors_clouds(540, 900, T))
        self.assertEqual(802, c.from_sensors_clouds(400, 900, T))
        self.assertEqual(803, c.from_sensors_clouds(200, 900, T))
        self.assertEqual(804, c.from_sensors_clouds(50, 900, T))

    def test_not_daytime(self):
        self.assertIsNone(c.from_sensors_clouds(0, 0, T), 'Night.')
        self.assertIsNone(c.from_sensors_clouds(20, 80, T), 'The sun is too low.')
        self.assertIsNone(c.from_sensors_clouds(None, 900, T), 'No radiation sensor.')

    def test_wind(self):
        self.assertEqual(400, c.from_sensors_wind({'windspeed': 12}, T))
        self.assertIsNone(c.from_sensors_wind({'windspeed': 5}, T))
        self.assertIsNone(c.from_sensors_wind({}, T))


class TestMetar(unittest.TestCase):

    def test_weather(self):
        cases = {
            '-RA BR': 500,
            'RA': 503,
            '+RA': 504,
            'TSRA': 201,
            'TS': 211,
            '-SHRA': 520,
            '+SN': 602,
            'RASN': 616,
            'FZRA': 511,
            'BR': 701,
            'FG': 741,
            'HZ': 721,
            'BR -RA': 500,
            'VCSH': None,
            'VCTS BR': 701,
            '': None,
            None: None,
        }
        for wx, code in cases.items():
            self.assertEqual(code, c.metar_weather_code(wx), wx)

    def test_report(self):
        with open(os.path.join(helpers.DATA, 'metar-kphl-clear.json')) as f:
            report = json.load(f)[0]
        observed = report['obsTime']
        self.assertEqual(800, c.from_metar_report(report, observed + 600, 90))
        self.assertIsNone(c.from_metar_report(report, observed + 91 * 60, 90), 'Too old.')
        self.assertEqual(503, c.from_metar_report(dict(report, wxString='RA'), observed, 90), 'Weather beats cover.')
        self.assertEqual(803, c.from_metar_report({'obsTime': observed, 'clouds': [{'cover': 'FEW'}, {'cover': 'BKN'}]}, observed, 90))
        self.assertIsNone(c.from_metar_report(None, observed, 90))


class TestNws(unittest.TestCase):

    def test_icon_codes(self):
        self.assertEqual(802, c.nws_icon_code('https://api.weather.gov/icons/land/day/sct?size=small'))
        self.assertEqual(800, c.nws_icon_code('https://api.weather.gov/icons/land/night/skc,10?size=medium'))
        self.assertEqual(211, c.nws_icon_code('https://api.weather.gov/icons/land/night/tsra_sct,40/rain,60?size=small'))
        self.assertEqual(521, c.nws_icon_code('https://api.weather.gov/icons/land/day/rain_showers,30'))
        self.assertIsNone(c.nws_icon_code('https://api.weather.gov/icons/land/night/unknown?size=medium'))
        self.assertIsNone(c.nws_icon_code(''))

    def test_current_hour(self):
        rows = [
            (60, 1000, 4600, 10, 'https://api.weather.gov/icons/land/day/few'),
            (60, 1000, 4600, 20, 'https://api.weather.gov/icons/land/day/bkn'),  # Newer forecast.
            (60, 4600, 8200, 20, 'https://api.weather.gov/icons/land/day/rain'),
            (720, 0, 43200, 30, 'https://api.weather.gov/icons/land/day/skc'),   # Twelve-hour.
        ]
        with FakeManager(rows) as manager:
            self.assertEqual('https://api.weather.gov/icons/land/day/bkn', c.nws_current_icon(manager, 2000))
            self.assertIsNone(c.nws_current_icon(manager, 9000))


class TestSources(unittest.TestCase):

    def test_order_and_first_wins(self):
        sources = c.ConditionSources({}, 'test', metar_fetcher=lambda *a: None)
        self.assertEqual(c.DEFAULT_SOURCES, sources.sources)
        # Raining at the station beats cloud cover.
        self.assertEqual((503, 'sensors_precipitation'), sources.condition({'rainrate': 3, 'temperature': 15}, 0, radiation=800, max_solar_radiation=900))
        self.assertEqual((800, 'sensors_clouds'), sources.condition({'temperature': 15}, 0, radiation=800, max_solar_radiation=900))
        self.assertEqual((None, None), sources.condition({'temperature': 15}, 0))

    def test_metar_source(self):
        calls = []

        def fetcher(station, agent):
            calls.append((station, agent))
            return {'obsTime': 1000, 'cover': 'OVC'}

        sources = c.ConditionSources({'metar_station': 'kphl'}, 'agent', metar_fetcher=fetcher)
        self.assertEqual((804, 'metar'), sources.condition({'temperature': 15}, 1200, radiation=800, max_solar_radiation=900))
        self.assertEqual([('KPHL', 'agent')], calls)
        # Not fetched when an earlier source answers.
        sources.condition({'rainrate': 1, 'temperature': 15}, 1200)
        self.assertEqual(1, len(calls))

    def test_nws_source(self):
        rows = [(60, 0, 3600, 1, 'https://api.weather.gov/icons/land/night/ovc')]
        sources = c.ConditionSources({'sources': 'sensors_clouds, nws'}, 'test', nws_manager_opener=lambda: FakeManager(rows))
        self.assertEqual((804, 'nws'), sources.condition({}, 100))

        def broken():
            raise RuntimeError('no database')

        self.assertEqual((None, None), c.ConditionSources({'sources': 'nws'}, 'test', nws_manager_opener=broken).condition({}, 100))
        self.assertEqual((None, None), c.ConditionSources({'sources': 'nws'}, 'test').condition({}, 100), 'weewx-nws not installed.')

    def test_config(self):
        sources = c.ConditionSources(
            {'sources': ['sensors_wind', 'bogus'], 'Thresholds': {'windy_speed': '8', 'nope': '1', 'rain_heavy': 'x'}},
            'test',
        )
        self.assertEqual(['sensors_wind'], sources.sources)
        self.assertEqual(8.0, sources.thresholds['windy_speed'])
        self.assertEqual(T['rain_heavy'], sources.thresholds['rain_heavy'])
        self.assertEqual((400, 'sensors_wind'), sources.condition({'windspeed': 9}, 0))


if __name__ == '__main__':
    unittest.main()
