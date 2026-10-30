"""Tests for records, yesterday, rain, lightning, sensors, health and the archive files, over a real
WeeWX database with daily summaries, as WeeWX itself keeps one."""
import json
import os
import shutil
import tempfile
import time
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import weewx
import weewx.manager
from weeutil.weeutil import TimeSpan, archiveDaySpan
import user.current_json as sl
import user.current_json_archives as ar
import user.current_json_rain as rn
import user.current_json_records as rc
import user.current_json_sensors as sn
from tests.test_current_json import RECORD, FakeStation

NOW = RECORD['dateTime']        # 2025-10-23 11:00 EDT, a Thursday.
HOUR = 3600
DAY = 86400


def config(root):
    return {
        'WEEWX_ROOT': root,
        'Station': {'location': 'Backyard', 'latitude': '39.9524', 'longitude': '-75.1636'},
        'StdReport': {'HTML_ROOT': 'public_html'},
        'DataBindings': {'wx_binding': {
            'database': 'archive_sqlite', 'table_name': 'archive',
            'manager': 'weewx.manager.DaySummaryManager', 'schema': 'weewx.schemas.wview_extended.schema',
        }},
        'Databases': {'archive_sqlite': {'database_name': 'weewx.sdb', 'database_type': 'SQLite'}},
        'DatabaseTypes': {'SQLite': {'driver': 'weedb.sqlite', 'SQLITE_ROOT': root}},
        'CurrentJSON': {'Conditions': {'sources': 'sensors_precipitation'}},
    }


class DatabaseTest(unittest.TestCase):
    """Ten days of hourly records: 50 °F, but 77 °F at noon three days ago and 32 °F at 5am five
    days ago; rain at 4am yesterday and in the last two hours."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.config = config(self.root)
        with self.open(initialize=True) as manager:
            for hours_ago in range(10 * 24, -1, -1):
                stamp = NOW - hours_ago * HOUR
                record = dict(RECORD, dateTime=stamp, interval=60, outTemp=50.0, rain=0.0, rainRate=0.0)
                if hours_ago == 3 * 24 - 1:
                    record['outTemp'] = 77.0
                if hours_ago == 5 * 24 + 6:
                    record['outTemp'] = 32.0
                if stamp == archiveDaySpan(NOW).start - 20 * HOUR:      # 4am yesterday.
                    record['rain'] = 0.1
                if hours_ago in (0, 1):
                    record['rain'] = 0.05
                manager.addRecord(record)

    def tearDown(self):
        shutil.rmtree(self.root)

    def open(self, initialize=False):
        return weewx.manager.open_manager_with_config(self.config, 'wx_binding', initialize=initialize)


class TestRecords(DatabaseTest):

    def test_periods(self):
        self.assertEqual(['week', 'month', 'year', 'rain_year', 'all_time'], rc.options_from_config({}))
        self.assertEqual(['month', 'all_time'], rc.options_from_config({'periods': 'all_time, month'}))
        self.assertIsNone(rc.options_from_config({'enable': 'false'}))

    def test_spans_end_at_midnight(self):
        spans = rc.period_spans(NOW, rc.PERIODS, first_timestamp=NOW - 10 * DAY)
        tomorrow = archiveDaySpan(NOW).stop
        self.assertEqual({'week', 'month', 'year', 'all_time'}, set(spans), 'No rain year starting in January.')
        self.assertTrue(all(span.stop == tomorrow for span in spans.values()))
        self.assertEqual(time.mktime((2025, 10, 19, 0, 0, 0, 0, 0, -1)), spans['week'].start, 'The Sunday before.')
        self.assertEqual(time.mktime((2025, 10, 1, 0, 0, 0, 0, 0, -1)), spans['month'].start)
        rain_year = rc.period_spans(NOW, ['rain_year'], rain_year_start=10)['rain_year']
        self.assertEqual(time.mktime((2025, 10, 1, 0, 0, 0, 0, 0, -1)), rain_year.start)

    def test_degree_days(self):
        bases = rc.degree_day_bases({})
        self.assertAlmostEqual(18.33, bases['heatdeg'], places=2)
        with self.open() as manager:
            yesterday = rc.degree_days(manager, archiveDaySpan(NOW, days_ago=1), bases)
        # A day at 10 °C is 8.3 heating degree days below 65 °F, and 0 cooling or growing above it.
        self.assertEqual({'heatdeg': 8.3, 'cooldeg': 0.0, 'growdeg': 0.0}, yesterday)

    def test_custom_bases(self):
        bases = rc.degree_day_bases({'StdReport': {'Defaults': {'Units': {'DegreeDays': {'growing_base': ['5', 'degree_C']}}}}})
        self.assertEqual(5.0, bases['growdeg'])


class TestRain(DatabaseTest):

    def test_rain(self):
        with self.open() as manager:
            rain = rn.read_rain(manager, NOW)
        self.assertEqual(2.54, rain['last_24h'], 'The last two hours; yesterday 4am was 31 hours ago.')
        self.assertEqual(NOW, rain['last'])
        self.assertEqual({'storm': 2.54, 'storm_start': NOW - HOUR}, {k: rain[k] for k in ('storm', 'storm_start')})

    def test_longer_storm_gap_joins_yesterday(self):
        with self.open() as manager:
            rain = rn.read_rain(manager, NOW, storm_gap=36 * HOUR)
        self.assertEqual(5.08, rain['storm'])
        self.assertEqual(archiveDaySpan(NOW).start - 20 * HOUR, rain['storm_start'])

    def test_no_storm_when_dry(self):
        with self.open() as manager:
            rain = rn.read_rain(manager, NOW - 3 * HOUR)
        self.assertNotIn('storm', rain, 'Its last rain, 4am yesterday, was 28 hours before.')
        self.assertEqual(archiveDaySpan(NOW).start - 20 * HOUR, rain['last'])

    def test_options(self):
        self.assertEqual({'storm_gap': 12 * HOUR}, rn.options_from_config({'storm_gap': '12'}))
        self.assertIsNone(rn.options_from_config({'enable': 'false'}))


class TestSensors(unittest.TestCase):

    RECORD = dict(RECORD, inTemp=70.0, inHumidity=40.0, extraTemp1=59.0, soilMoist2=18.0, leafWet1=3.0,
                  windBatteryStatus=1.0, outTempBatteryStatus=0.0, batteryStatus3=1.0, consBatteryVoltage=4.623,
                  rxCheckPercent=42.0)

    def test_off_by_default(self):
        self.assertEqual((False, False, {}), sn.sensor_options({}))

    def test_indoor(self):
        self.assertEqual({'temperature': 21.1, 'humidity': 40}, sn.indoor(self.RECORD))

    def test_extra(self):
        self.assertEqual([
            {'field': 'extraTemp1', 'name': 'Greenhouse', 'kind': 'temperature', 'value': 15.0},
            {'field': 'soilMoist2', 'name': 'Soil moisture 2', 'kind': 'soil_moisture', 'value': 18},
            {'field': 'leafWet1', 'name': 'Leaf wetness 1', 'kind': 'leaf_wetness', 'value': 3},
        ], sn.extra(self.RECORD, {'extraTemp1': 'Greenhouse'}))

    def test_health(self):
        health = sn.health(self.RECORD, {'Batteries': {'batteryStatus3': 'level'}, 'Names': {'batteryStatus3': 'Pool'}})
        self.assertEqual({'windBatteryStatus': 1, 'outTempBatteryStatus': 0, 'batteryStatus3': 1}, health['batteries'])
        self.assertEqual({'consBatteryVoltage': 4.62}, health['voltages'])
        self.assertEqual({'rxCheckPercent': 42}, health['signal'])
        self.assertEqual([
            {'field': 'windBatteryStatus', 'message': 'Wind sensor battery low'},
            {'field': 'batteryStatus3', 'message': 'Pool battery low'},
            {'field': 'rxCheckPercent', 'message': 'Weak signal from the sensors (42% received)'},
        ], health['warnings'])

    def test_level_battery_that_is_fine(self):
        health = sn.health(dict(RECORD, batteryStatus1=4.0), {'Batteries': {'batteryStatus1': 'level'}})
        self.assertNotIn('warnings', health)

    def test_no_health_readings(self):
        self.assertEqual({}, sn.health(RECORD))
        self.assertEqual({}, sn.health(self.RECORD, {'enable': 'false'}))


class TestArchives(DatabaseTest):

    def test_options(self):
        self.assertIsNone(ar.options_from_config({}), 'Off by default.')
        self.assertEqual({'week': 'history-week.json', 'year': 'history-year.json'}, ar.options_from_config({'enable': 'true'}))
        self.assertEqual({'year': 'y.json'}, ar.options_from_config({'enable': 'true', 'week': '', 'year': 'y.json'}))

    def test_week(self):
        with self.open() as manager:
            document = ar.week_document(manager, NOW, sl.OBSERVATIONS, 'weewx', sl.PRECISION)
        history = document['history']
        self.assertEqual('current-conditions-history', document['format'])
        self.assertEqual(3600, history['interval'])
        self.assertEqual(168, len(history['temperature']))
        self.assertEqual(25.0, max(v for v in history['temperature'] if v is not None))

    def test_year(self):
        with self.open() as manager:
            daily = ar.year_document(manager, NOW, sl.OBSERVATIONS, 'weewx', sl.PRECISION)['daily']
        self.assertEqual(365, len(daily['time']))
        self.assertEqual(archiveDaySpan(NOW).start, daily['time'][-1])
        self.assertIsNone(daily['temperature'][0], 'No data a year ago.')
        self.assertEqual(25.0, max(v for v in daily['temperature_max'] if v is not None))
        self.assertEqual(0.0, min(v for v in daily['temperature_min'] if v is not None))
        self.assertEqual(2.54, daily['rain'][-2], 'Yesterday 4am.')
        self.assertNotIn('rain_min', daily)

    def test_rewritten_only_when_due(self):
        names = {'week': 'w.json'}
        written = []

        def write(path, document):
            written.append(path)
            sl.write_atomically(path, document)

        with self.open() as manager:
            self.assertEqual(names, ar.write_archives(manager, NOW, sl.OBSERVATIONS, 'weewx', names, self.root, write=write))
            ar.write_archives(manager, NOW, sl.OBSERVATIONS, 'weewx', names, self.root, write=write)
            self.assertEqual(1, len(written))
            ar.write_archives(manager, NOW, sl.OBSERVATIONS, 'weewx', names, self.root, write=write, now=time.time() + 3601)
            self.assertEqual(2, len(written))


class TestGenerator(DatabaseTest):

    def run_generator(self):
        generator = sl.CurrentJSONGenerator(self.config, {'REPORT_NAME': 'CurrentJSON'}, NOW, True, FakeStation())
        try:
            generator.run()
        finally:
            generator.finalize()
        with open(os.path.join(self.root, 'public_html', 'current.json')) as f:
            return json.load(f)

    def test_sections(self):
        document = self.run_generator()
        self.assertEqual(8.3, document['today']['heatdeg'])
        self.assertEqual(10.0, document['yesterday']['temperature_max'])
        self.assertEqual(2.54, document['yesterday']['rain'])
        records = document['records']
        self.assertEqual({'week', 'month', 'year', 'all_time'}, set(records))
        self.assertEqual(25.0, records['week']['temperature_max'])
        self.assertEqual(0.0, records['month']['temperature_min'])
        self.assertEqual(5.08, records['all_time']['rain'])
        self.assertIn('heatdeg', records['month'])
        self.assertNotIn('heatdeg', records['all_time'])
        self.assertEqual(NOW, document['rain']['last'])
        for key in ('indoor', 'sensors', 'archives', 'health'):
            self.assertNotIn(key, document)

    def test_options(self):
        self.config['CurrentJSON'].update({
            'Sensors': {'indoor': 'true', 'extra': 'true'},
            'Records': {'periods': 'year'},
            'Today': {'yesterday': 'false'},
            'Rain': {'enable': 'false'},
            'Archives': {'enable': 'true'},
        })
        with self.open() as manager:
            manager.addRecord(dict(RECORD, dateTime=NOW + 300, interval=5, inTemp=70.0, extraTemp1=59.0,
                                   windBatteryStatus=1.0, rain=0.0))
        generator = sl.CurrentJSONGenerator(self.config, {'REPORT_NAME': 'CurrentJSON'}, NOW + 300, True, FakeStation())
        generator.run()
        generator.finalize()
        with open(os.path.join(self.root, 'public_html', 'current.json')) as f:
            document = json.load(f)
        self.assertEqual({'temperature': 21.1}, document['indoor'])
        self.assertEqual('extraTemp1', document['sensors'][0]['field'])
        self.assertEqual(['year'], list(document['records']))
        self.assertNotIn('yesterday', document)
        self.assertNotIn('rain', document)
        self.assertEqual('Wind sensor battery low', document['health']['warnings'][0]['message'])
        self.assertEqual({'week': 'history-week.json', 'year': 'history-year.json'}, document['archives'])
        for name in document['archives'].values():
            self.assertTrue(os.path.exists(os.path.join(self.root, 'public_html', name)))


class TestLightning(DatabaseTest):

    def test_lightning(self):
        with self.open() as manager:
            self.assertEqual({}, sl.CurrentJSONGenerator.lightning(manager, NOW), 'No strike counts: no sensor.')
            manager.addRecord(dict(RECORD, dateTime=NOW + 300, interval=5, lightning_strike_count=7.0,
                                   lightning_distance=5.0))
            self.assertEqual({'lightning_strikes': 7, 'lightning_distance': 8.0},
                             sl.CurrentJSONGenerator.lightning(manager, NOW + 300))


if __name__ == '__main__':
    unittest.main()
