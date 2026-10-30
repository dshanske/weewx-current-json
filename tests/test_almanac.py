"""Tests for user.current_json_almanac, with WeeWX's own almanac and, if installed, PyEphem's."""
import time
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import user.current_json_almanac as a
from tests.test_current_json import RECORD

try:
    import ephem  # noqa: F401
    HAS_EPHEM = True
except ImportError:
    HAS_EPHEM = False

NOW = RECORD['dateTime']    # 2025-10-23 11:00 EDT, in Philadelphia.
LATITUDE, LONGITUDE = 39.9524, -75.1636


def local_hour(timestamp):
    t = time.localtime(timestamp)
    return t.tm_hour + t.tm_min / 60


class TestAlmanac(unittest.TestCase):

    def setUp(self):
        self.almanac = a.read_almanac(NOW, LATITUDE, LONGITUDE, 12)

    def test_sun(self):
        # The sun rose at about 7:19 and set at about 6:13 in Philadelphia that day.
        self.assertAlmostEqual(7.3, local_hour(self.almanac['sunrise']), delta=0.1)
        self.assertAlmostEqual(18.2, local_hour(self.almanac['sunset']), delta=0.1)

    def test_moon(self):
        # The new moon was on 2025-10-21, two days before.
        self.assertIn(self.almanac['moon_phase'], (0, 1))
        self.assertLess(self.almanac['moon_fullness'], 10)

    @unittest.skipIf(HAS_EPHEM, 'PyEphem is installed')
    def test_without_ephem(self):
        self.assertEqual({'sunrise', 'sunset', 'moon_phase', 'moon_fullness'}, set(self.almanac))

    @unittest.skipUnless(HAS_EPHEM, 'PyEphem is not installed')
    def test_with_ephem(self):
        self.assertLess(self.almanac['civil_dawn'], self.almanac['sunrise'])
        self.assertGreater(self.almanac['civil_dusk'], self.almanac['sunset'])
        self.assertIn('moonrise', self.almanac)
        self.assertIn('moonset', self.almanac)
        # The next full moon was 2025-11-05, and the next new moon 2025-11-20.
        self.assertEqual(time.strftime('%Y-%m-%d', time.localtime(self.almanac['next_full_moon'])), '2025-11-05')
        self.assertEqual(time.strftime('%Y-%m-%d', time.localtime(self.almanac['next_new_moon'])), '2025-11-20')

    def test_enabled(self):
        self.assertTrue(a.enabled({}))
        self.assertFalse(a.enabled({'enable': 'false'}))


if __name__ == '__main__':
    unittest.main()
