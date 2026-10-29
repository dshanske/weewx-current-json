"""Tests for user.current_json, including a run of the generator over a real WeeWX database."""
import glob
import json
import os
import shutil
import tempfile
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import weewx
import weewx.manager
import weewx.units
import user.current_json as sl

# An archive record from a US-units station: 70.7 F, 29.98 inHg, 8 mph, 0.12 in/h.
RECORD = {
    'dateTime': 1761231600,
    'usUnits': weewx.US,
    'interval': 5,
    'outTemp': 70.7,
    'outHumidity': 61.0,
    'dewpoint': 56.6,
    'barometer': 29.98,
    'windSpeed': 8.0,
    'windDir': 230.0,
    'windGust': 14.0,
    'rainRate': 0.12,
    'radiation': 412.4,
    'maxSolarRad': 820.0,
    'UV': 3.14,
    'pm2_5': 8.25,
    'heatindex': None,
}

# A record with an SGP41 gas sensor's indices, in custom voc_index and nox_index columns, and CO2.
GAS_RECORD = dict(RECORD, voc_index=112.4, nox_index=1.0, co2=421.0)


class FakeStation:
    altitude_vt = weewx.units.ValueTuple(40, 'foot', 'group_altitude')


class TestObservations(unittest.TestCase):

    def test_converts_to_metric(self):
        observations = sl.observations_from_record(RECORD, hour_rain_mm=1.27)
        self.assertEqual(21.5, observations['temperature'])
        self.assertEqual(61, observations['humidity'])
        self.assertIsInstance(observations['humidity'], int, 'Whole numbers are written as integers.')
        self.assertIsInstance(observations['winddegree'], int)
        self.assertEqual(13.7, observations['dewpoint'])
        self.assertEqual(1015.2, observations['pressure'])
        self.assertEqual(3.58, observations['windspeed'])
        self.assertEqual(230, observations['winddegree'])
        self.assertEqual(6.26, observations['windgust'])
        self.assertEqual(3.05, observations['rainrate'])
        self.assertEqual(1.27, observations['rain'])
        self.assertEqual(412, observations['radiation'])
        self.assertEqual(3.1, observations['uv'])
        self.assertEqual(8.25, observations['pm2_5'])

    def test_gas_indices(self):
        observations = sl.observations_from_record(GAS_RECORD)
        self.assertEqual(112, observations['voc_index'])
        self.assertEqual(1, observations['nox_index'])
        self.assertIsInstance(observations['voc_index'], int)
        self.assertEqual(421.0, observations['co2'])
        self.assertNotIn('voc_index', sl.observations_from_record(RECORD), 'No gas sensor.')

    def test_fields(self):
        fields = sl.fields_from_config({'Fields': {'voc_index': 'voc', 'nox_index': 'nox', 'uv': 'none', 'bogus': 'x'}})
        self.assertEqual('voc_index', fields['voc'])
        self.assertNotIn('voc_index', fields, 'The default field is replaced, not kept as well.')
        self.assertNotIn('UV', fields, 'An empty or none field leaves the key out.')
        self.assertNotIn('x', fields, 'Only the file\'s keys can be mapped.')
        self.assertEqual('temperature', fields['outTemp'], 'Unmapped keys keep their defaults.')

        observations = sl.observations_from_record(dict(RECORD, voc=112.4, nox=2.0, voc_index=999), fields=fields)
        self.assertEqual(112, observations['voc_index'], 'Read from voc, not the default field.')
        self.assertEqual(2, observations['nox_index'])
        self.assertNotIn('uv', observations)

    def test_fields_default(self):
        self.assertEqual(sl.OBSERVATIONS, sl.fields_from_config({}))
        self.assertEqual(sl.OBSERVATIONS, sl.fields_from_config({'Fields': {}}))

    def test_missing_readings_left_out(self):
        observations = sl.observations_from_record(RECORD)
        self.assertNotIn('heatindex', observations, 'None is left out.')
        self.assertNotIn('rain', observations, 'No rain gauge total.')
        self.assertNotIn('maxSolarRad', observations, 'Only the format\'s keys.')
        self.assertNotIn('illuminance', observations, 'Not measured.')

    def test_metric_station(self):
        record = {'dateTime': 1, 'usUnits': weewx.METRIC, 'outTemp': 21.5, 'windSpeed': 36.0, 'rain': 1.0}
        observations = sl.observations_from_record(record)
        self.assertEqual(21.5, observations['temperature'])
        self.assertEqual(10.0, observations['windspeed'], 'METRIC is km/h, converted to m/s.')


class TestStation(unittest.TestCase):

    def test_from_config(self):
        config = {
            'Station': {
                'location': ['Backyard', ' Philadelphia'],
                'latitude': '39.9524',
                'longitude': '-75.1636',
                'station_url': 'https://weather.example.com/',
            },
            'CurrentJSON': {'station_id': 'backyard', 'attribution_text': 'Weather from Backyard Weather'},
        }
        station = sl.station_from_config(config, FakeStation())
        self.assertEqual(
            {
                'id': 'backyard',
                'name': 'Backyard,  Philadelphia',
                'latitude': 39.9524,
                'longitude': -75.1636,
                'altitude': 12,
                'url': 'https://weather.example.com/',
                'attribution': {'text': 'Weather from Backyard Weather', 'url': 'https://weather.example.com/'},
            },
            station,
        )

    def test_defaults(self):
        station = sl.station_from_config({'Station': {}})
        self.assertEqual({'id': 'weewx'}, station)


class TestDocument(unittest.TestCase):

    def test_document(self):
        document = sl.build_document(RECORD, {'id': 'weewx'}, {'temperature': 21.5}, 802, 'sensors_clouds')
        self.assertEqual('current-conditions', document['format'])
        self.assertEqual(1, document['version'])
        self.assertEqual(1761231600, document['time'])
        self.assertEqual('metric', document['units'])
        self.assertEqual({'temperature': 21.5, 'code': 802}, document['observations'])
        self.assertEqual({'code': 'sensors_clouds'}, document['derived'])
        self.assertTrue(document['generator'].startswith('weewx-current-json '))

        document = sl.build_document(RECORD, {'id': 'weewx'}, {'temperature': 21.5})
        self.assertNotIn('derived', document)
        self.assertNotIn('code', document['observations'])

    def test_document_cloudiness(self):
        document = sl.build_document(RECORD, {'id': 'weewx'}, {'temperature': 21.5}, 803, 'metar', 75, 'metar')
        self.assertEqual({'temperature': 21.5, 'code': 803, 'cloudiness': 75}, document['observations'])
        self.assertEqual({'code': 'metar', 'cloudiness': 'metar'}, document['derived'])

        # Cloud cover without a condition, such as at night from the airport while it's windy elsewhere.
        document = sl.build_document(RECORD, {'id': 'weewx'}, {}, cloudiness=0, cloud_source='metar')
        self.assertEqual({'cloudiness': 0}, document['observations'])
        self.assertEqual({'cloudiness': 'metar'}, document['derived'])

    def test_write_atomically(self):
        directory = tempfile.mkdtemp()
        try:
            path = os.path.join(directory, 'public_html', 'current.json')
            sl.write_atomically(path, {'a': 1})
            sl.write_atomically(path, {'a': 2})
            with open(path) as f:
                self.assertEqual({'a': 2}, json.load(f))
            self.assertEqual(['current.json'], os.listdir(os.path.dirname(path)), 'No temporary files left.')
        finally:
            shutil.rmtree(directory)


class TestGenerator(unittest.TestCase):
    """Runs the generator over a real WeeWX SQLite database."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.config = {
            'WEEWX_ROOT': self.root,
            'Station': {'location': 'Backyard', 'latitude': '39.9524', 'longitude': '-75.1636'},
            'StdReport': {'HTML_ROOT': 'public_html'},
            'DataBindings': {
                'wx_binding': {
                    'database': 'archive_sqlite',
                    'table_name': 'archive',
                    'manager': 'weewx.manager.Manager',
                    'schema': 'weewx.schemas.wview_extended.schema',
                },
            },
            'Databases': {'archive_sqlite': {'database_name': 'weewx.sdb', 'database_type': 'SQLite'}},
            'DatabaseTypes': {'SQLite': {'driver': 'weedb.sqlite', 'SQLITE_ROOT': self.root}},
            'CurrentJSON': {'Conditions': {'sources': 'sensors_precipitation, sensors_clouds'}},
        }
        with weewx.manager.open_manager_with_config(self.config, 'wx_binding', initialize=True) as manager:
            # An hour of five-minute records, the last two with 0.05 in of rain each.
            for i in range(12):
                record = dict(RECORD, dateTime=RECORD['dateTime'] - (11 - i) * 300, rain=0.05 if i >= 10 else 0.0)
                record['rainRate'] = 0.0
                manager.addRecord(record)

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_generator(self, record=None):
        generator = sl.CurrentJSONGenerator(self.config, {'REPORT_NAME': 'CurrentJSON'}, RECORD['dateTime'], True, FakeStation(), record)
        try:
            generator.run()
        finally:
            generator.finalize()
        with open(os.path.join(self.root, 'public_html', 'current.json')) as f:
            return json.load(f)

    def test_writes_file(self):
        document = self.run_generator()
        self.assertEqual(RECORD['dateTime'], document['time'])
        self.assertEqual({'id': 'weewx', 'name': 'Backyard', 'latitude': 39.9524, 'longitude': -75.1636, 'altitude': 12}, document['station'])
        self.assertEqual(21.5, document['observations']['temperature'])
        self.assertEqual(2.54, document['observations']['rain'], 'The last hour of rain, in mm.')
        # Rain in the hour makes it light rain; sensors_precipitation comes first.
        self.assertEqual(500, document['observations']['code'])
        # 412 W/m^2 of a clear sky's 820 is scattered cloud, measured at the station.
        self.assertEqual(44, document['observations']['cloudiness'])
        self.assertEqual({'code': 'sensors_precipitation', 'cloudiness': 'sensors_clouds'}, document['derived'])

    def test_no_cloud_source(self):
        self.config['CurrentJSON']['Conditions']['cloud_sources'] = 'metar'
        document = self.run_generator()
        self.assertNotIn('cloudiness', document['observations'], 'No METAR station is set.')
        self.assertEqual({'code': 'sensors_precipitation'}, document['derived'])

    def test_fields_config(self):
        self.config['CurrentJSON']['Fields'] = {'uv': 'none', 'voc_index': 'voc'}
        record = dict(RECORD, rainRate=0.0, voc=140.0)
        document = self.run_generator(record)
        self.assertNotIn('uv', document['observations'], '[[Fields]] from weewx.conf is used.')
        self.assertEqual(140, document['observations']['voc_index'])

    def test_uses_report_record(self):
        record = dict(RECORD, outTemp=50.0, rainRate=0.0)
        document = self.run_generator(record)
        self.assertEqual(10.0, document['observations']['temperature'], 'The record the report engine passed.')

    def test_disabled(self):
        self.config['CurrentJSON']['enable'] = 'false'
        generator = sl.CurrentJSONGenerator(self.config, {}, RECORD['dateTime'], True, FakeStation())
        generator.run()
        generator.finalize()
        self.assertEqual([], glob.glob(os.path.join(self.root, 'public_html', '*.json')))


if __name__ == '__main__':
    unittest.main()
