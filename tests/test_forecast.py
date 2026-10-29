"""Tests for user.current_json_forecast, over a WeeWX database shaped like weewx-nws's."""
import json
import os
import shutil
import tempfile
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import weedb
import weewx
import weewx.manager
import user.current_json as sl
import user.current_json_forecast as f
from tests.test_current_json import RECORD, FakeStation

# weewx-nws's table, as in its bin/user/nws.py.
NWS_SCHEMA = {'table': [
    ('dateTime', 'INTEGER NOT NULL'), ('interval', 'INTEGER NOT NULL'), ('latitude', 'STRING NOT NULL'),
    ('longitude', 'STRING NOT NULL'), ('usUnits', 'INTEGER NOT NULL'), ('generatedTime', 'INTEGER NOT NULL'),
    ('number', 'INTEGER NOT NULL'), ('name', 'STRING'), ('startTime', 'FLOAT'), ('expirationTime', 'FLOAT'),
    ('id', 'STRING'), ('endTime', 'FLOAT'), ('isDaytime', 'INTEGER NOT NULL'), ('outTemp', 'FLOAT NOT NULL'),
    ('outTempTrend', 'STRING'), ('pop', 'INTEGER'), ('dewpoint', 'FLOAT'), ('outHumidity', 'INTEGER'),
    ('windSpeed', 'FLOAT'), ('windSpeed2', 'FLOAT'), ('windDir', 'FLOAT'), ('iconUrl', 'STRING NOT NULL'),
    ('shortForecast', 'STRING NOT NULL'), ('detailedForecast', 'STRING'), ('instruction', 'STRING'),
    ('sent', 'FLOAT'), ('status', 'STRING'), ('messageType', 'STRING'), ('category', 'STRING'),
    ('severity', 'STRING'), ('certainty', 'STRING'), ('urgency', 'STRING'), ('sender', 'STRING'),
    ('senderName', 'STRING'), ('nwsHeadline', 'STRING'), ('areaDesc', 'STRING'), ('response', 'STRING'),
    ('parameters', 'STRING'),
]}

NOW = RECORD['dateTime']
HOUR = 3600
ICON = 'https://api.weather.gov/icons/land/%s/%s?size=small'


def forecast_row(interval, generated, start, length, **values):
    """A weewx-nws forecast row, in US units like the ones it stores."""
    row = {
        'dateTime': generated, 'interval': interval, 'latitude': '39.9524', 'longitude': '-75.1636',
        'usUnits': weewx.US, 'generatedTime': generated, 'number': 1, 'startTime': start,
        'endTime': start + length, 'isDaytime': 1, 'outTemp': 68.0, 'iconUrl': ICON % ('day', 'sct'),
        'shortForecast': 'Partly Sunny',
    }
    row.update(values)
    return row


def alert_row(polled, **values):
    row = {
        'dateTime': polled, 'interval': 0, 'latitude': '39.9524', 'longitude': '-75.1636',
        'usUnits': weewx.US, 'generatedTime': NOW - HOUR, 'number': 0, 'name': 'Heat Advisory',
        'startTime': NOW - HOUR, 'expirationTime': NOW + 6 * HOUR, 'id': 'urn:oid:1', 'endTime': NOW + 9 * HOUR,
        'isDaytime': 1, 'outTemp': 0.0, 'iconUrl': '', 'shortForecast': 'Heat Advisory until 9 PM',
        'detailedForecast': 'Heat index values up to 105.', 'instruction': 'Drink plenty of fluids.',
        'severity': 'Moderate', 'certainty': 'Likely', 'urgency': 'Expected', 'senderName': 'NWS Philadelphia',
        'areaDesc': 'Philadelphia', 'status': 'Actual',
    }
    row.update(values)
    return row


class NWSDatabase:
    """A weewx-nws database in a temporary directory, and the weewx.conf sections to reach it."""

    def __init__(self, root):
        self.config = {
            'WEEWX_ROOT': root,
            'NWS': {'data_binding': 'nws_binding'},
            'DataBindings': {
                'nws_binding': {
                    'database': 'nws_sqlite',
                    'table_name': 'archive',
                    'manager': 'weewx.manager.Manager',
                    'schema': 'tests.test_forecast.NWS_SCHEMA',
                },
            },
            'Databases': {'nws_sqlite': {'database_name': 'nws.sdb', 'database_type': 'SQLite'}},
            'DatabaseTypes': {'SQLite': {'driver': 'weedb.sqlite', 'SQLITE_ROOT': root}},
        }

    def manager(self):
        return weewx.manager.open_manager_with_config(self.config, 'nws_binding', initialize=True)

    def insert(self, *rows):
        with self.manager() as manager, weedb.Transaction(manager.connection) as cursor:
            for row in rows:
                columns = list(row)
                cursor.execute(
                    'INSERT INTO archive (%s) VALUES (%s)' % (', '.join(columns), ', '.join('?' * len(columns))),
                    [row[c] for c in columns])


class TestReadForecast(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.db = NWSDatabase(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def read(self, **options):
        with self.db.manager() as manager:
            return f.read_forecast(manager, NOW, **options)

    def test_nothing(self):
        self.assertEqual({}, self.read())

    def test_hourly_in_metric(self):
        self.db.insert(forecast_row(60, NOW - HOUR, NOW, HOUR, dewpoint=50.0, outHumidity=53, windSpeed=9.0,
                                    windDir=225.0, pop=20, iconUrl=ICON % ('day', 'rain_showers,20')))
        forecast = self.read()
        self.assertEqual('nws', forecast['source'])
        self.assertEqual(NOW - HOUR, forecast['generated'])
        self.assertEqual([{
            'time': NOW, 'end': NOW + HOUR, 'daytime': True, 'temperature': 20.0, 'windspeed': 4.02,
            'winddegree': 225, 'pop': 20, 'code': 521, 'summary': 'Partly Sunny', 'dewpoint': 10.0, 'humidity': 53,
        }], forecast['hourly'])
        self.assertNotIn('periods', forecast)
        self.assertNotIn('alerts', forecast)

    def test_only_the_latest_forecast_and_hours_not_ended(self):
        self.db.insert(
            forecast_row(60, NOW - 2 * HOUR, NOW, HOUR, outTemp=50.0),       # An older forecast.
            forecast_row(60, NOW - HOUR, NOW - HOUR, HOUR, outTemp=59.0),    # Ended at NOW.
            forecast_row(60, NOW - HOUR, NOW + HOUR, HOUR, outTemp=77.0),
            forecast_row(60, NOW - HOUR, NOW, HOUR, outTemp=68.0),
        )
        self.assertEqual([20.0, 25.0], [h['temperature'] for h in self.read()['hourly']])

    def test_limits(self):
        self.db.insert(*[forecast_row(60, NOW, NOW + i * HOUR, HOUR) for i in range(30)])
        self.assertEqual(24, len(self.read()['hourly']))
        self.assertEqual(3, len(self.read(hours=3)['hourly']))
        self.assertEqual({}, self.read(hours=0))

    def test_periods(self):
        self.db.insert(
            forecast_row(720, NOW - HOUR, NOW, 12 * HOUR, number=1, name='Tonight', isDaytime=0, outTemp=55.0,
                         windSpeed=5.0, windSpeed2=10.0, windDir=180.0, pop=60, iconUrl=ICON % ('night', 'tsra,60'),
                         shortForecast='Chance Showers And Thunderstorms', detailedForecast='Showers likely after 2am.'),
            forecast_row(720, NOW - HOUR, NOW + 12 * HOUR, 12 * HOUR, number=2, name='Friday', outTemp=79.0),
        )
        periods = self.read()['periods']
        self.assertEqual({
            'name': 'Tonight', 'time': NOW, 'end': NOW + 12 * HOUR, 'daytime': False, 'temperature': 12.8,
            'windspeed': 2.24, 'windspeed_max': 4.47, 'winddegree': 180, 'pop': 60, 'code': 211,
            'summary': 'Chance Showers And Thunderstorms', 'details': 'Showers likely after 2am.',
        }, periods[0])
        self.assertEqual(['Tonight', 'Friday'], [p['name'] for p in periods])
        self.assertEqual(['Tonight'], [p['name'] for p in self.read(periods=1)['periods']])

    def test_alerts(self):
        self.db.insert(alert_row(NOW - 600))
        self.assertEqual([{
            'id': 'urn:oid:1', 'event': 'Heat Advisory', 'headline': 'Heat Advisory until 9 PM',
            'description': 'Heat index values up to 105.', 'instruction': 'Drink plenty of fluids.',
            'severity': 'Moderate', 'urgency': 'Expected', 'certainty': 'Likely', 'sender': 'NWS Philadelphia',
            'area': 'Philadelphia', 'issued': NOW - HOUR, 'onset': NOW - HOUR, 'ends': NOW + 9 * HOUR,
            'expires': NOW + 6 * HOUR,
        }], self.read()['alerts'])
        self.assertNotIn('generated', self.read(), 'Alerts alone are not a forecast.')
        self.assertEqual({}, self.read(alerts=False))

    def test_alerts_of_the_last_poll_that_have_not_ended(self):
        self.db.insert(
            alert_row(NOW - 1200, id='older poll', name='Older'),
            alert_row(NOW - 600, id='ended', endTime=NOW - 60),
            alert_row(NOW - 600, id='no end, not expired', endTime=None),
            alert_row(NOW - 600, id='no end, expired', endTime=None, expirationTime=NOW - 60),
            alert_row(NOW - 600, id='expired a day ago', expirationTime=NOW - 25 * HOUR),
            alert_row(NOW - 600, id='current'),
        )
        self.assertEqual({'no end, not expired', 'current'}, {a['id'] for a in self.read()['alerts']})

    def test_options(self):
        self.assertEqual({'hours': 24, 'periods': 14, 'alerts': True}, f.options_from_config({}))
        self.assertEqual({'hours': 6, 'periods': 0, 'alerts': False},
                         f.options_from_config({'hours': '6', 'periods': '0', 'alerts': 'false'}))
        self.assertIsNone(f.options_from_config({'enable': 'false'}))


class TestGeneratorForecast(unittest.TestCase):
    """Runs the generator with weewx-nws's database alongside the archive."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.nws = NWSDatabase(self.root)
        self.config = {
            'WEEWX_ROOT': self.root,
            'Station': {'location': 'Backyard', 'latitude': '39.9524', 'longitude': '-75.1636'},
            'StdReport': {'HTML_ROOT': 'public_html'},
            'NWS': self.nws.config['NWS'],
            'DataBindings': dict(self.nws.config['DataBindings'], wx_binding={
                'database': 'archive_sqlite',
                'table_name': 'archive',
                'manager': 'weewx.manager.Manager',
                'schema': 'weewx.schemas.wview_extended.schema',
            }),
            'Databases': dict(self.nws.config['Databases'],
                              archive_sqlite={'database_name': 'weewx.sdb', 'database_type': 'SQLite'}),
            'DatabaseTypes': self.nws.config['DatabaseTypes'],
            'CurrentJSON': {'Conditions': {'sources': 'sensors_precipitation'}},
        }
        with weewx.manager.open_manager_with_config(self.config, 'wx_binding', initialize=True) as manager:
            manager.addRecord(RECORD)

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_generator(self):
        generator = sl.CurrentJSONGenerator(self.config, {'REPORT_NAME': 'CurrentJSON'}, NOW, True, FakeStation(), None)
        try:
            generator.run()
        finally:
            generator.finalize()
        with open(os.path.join(self.root, 'public_html', 'current.json')) as fh:
            return json.load(fh)

    def test_adds_forecast_without_changing_the_rest(self):
        without = self.run_generator()
        self.assertNotIn('forecast', without, 'No forecast in an empty weewx-nws database.')
        self.nws.insert(forecast_row(60, NOW - HOUR, NOW, HOUR), alert_row(NOW - 600))
        document = self.run_generator()
        self.assertEqual(1, document['version'])
        self.assertEqual(['hourly', 'alerts'], [k for k in document['forecast'] if k in ('hourly', 'periods', 'alerts')])
        del document['forecast']
        self.assertEqual(without, document)

    def test_disabled(self):
        self.nws.insert(forecast_row(60, NOW - HOUR, NOW, HOUR))
        self.config['CurrentJSON']['Forecast'] = {'enable': 'false'}
        self.assertNotIn('forecast', self.run_generator())

    def test_without_weewx_nws(self):
        del self.config['NWS']
        self.assertNotIn('forecast', self.run_generator())

    def test_unreadable_database(self):
        # A weewx-nws binding whose table doesn't have the forecast's columns.
        self.config['DataBindings']['nws_binding']['schema'] = 'weewx.schemas.wview_extended.schema'
        self.assertNotIn('forecast', self.run_generator())


if __name__ == '__main__':
    unittest.main()
