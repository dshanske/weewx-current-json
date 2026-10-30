"""Tests for user.current_json_history, including reading it from a real WeeWX database."""
import shutil
import tempfile
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import weewx
import weewx.manager
import user.current_json as sl
import user.current_json_history as h
from tests.test_current_json import RECORD

NOW = RECORD['dateTime']
HALF_HOUR = 1800


class TestOptions(unittest.TestCase):

    def test_defaults(self):
        self.assertEqual({'hours': 24, 'interval': 1800}, h.options_from_config({}))

    def test_config(self):
        self.assertEqual({'hours': 12, 'interval': 3600}, h.options_from_config({'hours': '12', 'interval': '60'}))

    def test_off(self):
        self.assertIsNone(h.options_from_config({'hours': '0'}))

    def test_shortest_interval(self):
        self.assertEqual(300, h.options_from_config({'interval': '1'})['interval'])


class TestHistory(unittest.TestCase):

    def test_window_ends_with_the_current_interval(self):
        start, count = h.window(NOW + 60, 24, HALF_HOUR)
        self.assertEqual(48, count)
        self.assertEqual(NOW + HALF_HOUR - 48 * HALF_HOUR, start, 'NOW is on a half hour, so NOW + 60 is in the next.')

    def test_fields(self):
        fields = h.history_fields(sl.OBSERVATIONS, ['dateTime', 'outTemp', 'windDir', 'rain', 'windGust'])
        self.assertEqual({'outTemp': 'temperature', 'rain': 'rain', 'windGust': 'windgust'}, fields)

    def test_summaries(self):
        start = NOW - 2 * HALF_HOUR
        rows = [
            # The first interval: two records. A record's time is the end of its interval, so the
            # one at start + 1800 is the first interval's last.
            {'dateTime': start + 900, 'usUnits': weewx.US, 'outTemp': 50.0, 'rain': 0.01, 'windGust': 10.0},
            {'dateTime': start + 1800, 'usUnits': weewx.US, 'outTemp': 59.0, 'rain': 0.02, 'windGust': 20.0},
            # The second: a metric record, mixed in.
            {'dateTime': start + 2700, 'usUnits': weewx.METRICWX, 'outTemp': 20.0, 'rain': None, 'windGust': 3.0},
            # Outside the window.
            {'dateTime': start, 'usUnits': weewx.US, 'outTemp': 100.0},
        ]
        fields = {'outTemp': 'temperature', 'rain': 'rain', 'windGust': 'windgust'}
        history = h.history_from_rows(rows, fields, start, HALF_HOUR, 2, sl.PRECISION)
        self.assertEqual({
            'start': start,
            'interval': HALF_HOUR,
            'temperature': [12.5, 20.0],        # The mean of 10 and 15 °C.
            'rain': [0.76, None],               # The total, in mm.
            'windgust': [8.94, 3.0],            # The highest, in m/s.
        }, history)

    def test_empty_interval_is_null(self):
        rows = [{'dateTime': NOW, 'usUnits': weewx.METRICWX, 'outTemp': 20.0}]
        history = h.history_from_rows(rows, {'outTemp': 'temperature'}, NOW - 3 * HALF_HOUR, HALF_HOUR, 3)
        self.assertEqual([None, None, 20.0], history['temperature'])

    def test_nothing(self):
        self.assertEqual({}, h.history_from_rows([], {'outTemp': 'temperature'}, NOW, HALF_HOUR, 2))

    def test_unknown_unit_taken_as_is(self):
        rows = [{'dateTime': NOW, 'usUnits': weewx.US, 'voc_index': 112.4}]
        history = h.history_from_rows(rows, {'voc_index': 'voc_index'}, NOW - HALF_HOUR, HALF_HOUR, 1, sl.PRECISION)
        self.assertEqual([112], history['voc_index'])


class TestReadHistory(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.config = {
            'WEEWX_ROOT': self.root,
            'DataBindings': {'wx_binding': {
                'database': 'archive_sqlite', 'table_name': 'archive', 'manager': 'weewx.manager.Manager',
                'schema': 'weewx.schemas.wview_extended.schema',
            }},
            'Databases': {'archive_sqlite': {'database_name': 'weewx.sdb', 'database_type': 'SQLite'}},
            'DatabaseTypes': {'SQLite': {'driver': 'weedb.sqlite', 'SQLITE_ROOT': self.root}},
        }

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_reads_archive(self):
        with weewx.manager.open_manager_with_config(self.config, 'wx_binding', initialize=True) as manager:
            # Two hours of five-minute records, warming by 0.9 °F (0.5 °C) each half hour.
            for i in range(24):
                stamp = NOW - (23 - i) * 300
                manager.addRecord(dict(RECORD, dateTime=stamp, outTemp=50.0 + 0.9 * (i // 6), rain=0.0))
            history = h.read_history(manager, NOW, sl.OBSERVATIONS, hours=2, interval=HALF_HOUR, precision=sl.PRECISION)
        self.assertEqual(NOW - 4 * HALF_HOUR, history['start'])
        self.assertEqual([10.0, 10.5, 11.0, 11.5], history['temperature'])
        self.assertEqual([0.0, 0.0, 0.0, 0.0], history['rain'])
        self.assertNotIn('winddegree', history)
        self.assertNotIn('snow', history, 'No snow column in the archive.')


if __name__ == '__main__':
    unittest.main()
