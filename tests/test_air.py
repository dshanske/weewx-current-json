"""Tests for user.current_json_air."""
import unittest

from tests import helpers  # noqa: F401 - sets up the path
import user.current_json_air as air
import user.current_json_conditions as c

T = c.DEFAULT_THRESHOLDS


class TestUsEpaAqi(unittest.TestCase):

    def test_breakpoints(self):
        cases = {
            0.0: (0, 'good'),
            9.0: (50, 'good'),
            9.1: (51, 'moderate'),
            35.4: (100, 'moderate'),
            35.5: (101, 'unhealthy_sensitive'),
            55.4: (150, 'unhealthy_sensitive'),
            55.5: (151, 'unhealthy'),
            125.4: (200, 'unhealthy'),
            125.5: (201, 'very_unhealthy'),
            225.4: (300, 'very_unhealthy'),
            225.5: (301, 'hazardous'),
            325.4: (500, 'hazardous'),
        }
        for concentration, (index, slug) in cases.items():
            result = air.us_epa_aqi(concentration)
            self.assertEqual((index, slug), result[:2], concentration)

    def test_between_breakpoints(self):
        # 20.0 in Moderate: (100 - 51) / (35.4 - 9.1) * (20.0 - 9.1) + 51 = 71.3, rounded to 71.
        self.assertEqual(71, air.us_epa_aqi(20.0)[0])
        # Truncated, not rounded: 9.05 is 9.0, still Good.
        self.assertEqual((50, 'good'), air.us_epa_aqi(9.05)[:2])
        self.assertEqual((100, 'moderate'), air.us_epa_aqi(35.49)[:2])

    def test_names_and_colors(self):
        self.assertEqual((42, 'good', 'Good', '#00e400'), air.us_epa_aqi(7.5))
        self.assertEqual('#ffff00', air.us_epa_aqi(12)[3])
        self.assertEqual(('Unhealthy for Sensitive Groups', '#ff7e00'), air.us_epa_aqi(40)[2:])
        self.assertEqual(('Unhealthy', '#ff0000'), air.us_epa_aqi(80)[2:])
        self.assertEqual(('Very Unhealthy', '#8f3f97'), air.us_epa_aqi(150)[2:])
        self.assertEqual(('Hazardous', '#7e0023'), air.us_epa_aqi(250)[2:])

    def test_beyond_the_index(self):
        index, slug = air.us_epa_aqi(400.0)[:2]
        self.assertGreater(index, 500)
        self.assertEqual('hazardous', slug)

    def test_no_concentration(self):
        for value in (None, -1, 'high', True):
            self.assertEqual((None, None, None, None), air.us_epa_aqi(value), value)


class TestNowCast(unittest.TestCase):

    def test_steady(self):
        self.assertEqual(12.0, air.nowcast([12.0] * 12))

    def test_weights(self):
        # Rising from 10 to 40 over two hours: the weight is the 0.5 floor (10 / 40 is less), so
        # (40 + 0.5 * 20 + 0.25 * 10) / (1 + 0.5 + 0.25) = 30.0.
        self.assertEqual(30.0, air.nowcast([40.0, 20.0, 10.0]))
        # A gentler change uses min / max as the weight: 16 / 20 = 0.8, so
        # (20 + 0.8 * 16) / 1.8 = 18.22, truncated to 18.2.
        self.assertEqual(18.2, air.nowcast([20.0, 16.0]))

    def test_gaps(self):
        # A missing hour is left out, and the older hour keeps its age: (20 + 0.8^2 * 16) / (1 + 0.8^2)
        # = 18.44, truncated to 18.4.
        self.assertEqual(18.4, air.nowcast([20.0, None, 16.0]))
        # Older hours beyond 12 are ignored.
        self.assertEqual(12.0, air.nowcast([12.0] * 12 + [500.0]))

    def test_needs_two_of_last_three_hours(self):
        self.assertIsNone(air.nowcast([10.0, None, None, 10.0, 10.0]))
        self.assertIsNone(air.nowcast([None, None, 10.0]))
        self.assertIsNone(air.nowcast([]))
        self.assertIsNotNone(air.nowcast([None, 10.0, 10.0]))

    def test_zero(self):
        self.assertEqual(0.0, air.nowcast([0.0, 0.0, 0.0]))


class TestAirQuality(unittest.TestCase):

    def test_properties(self):
        self.assertEqual(
            {'aqi': 50, 'aqi_category': 'Good', 'aqi_color': '#00e400'},
            air.air_quality('us_epa', 9.0, [9.0] * 12),
        )

    def test_no_data_no_index(self):
        self.assertEqual({}, air.air_quality('us_epa', None, [9.0] * 12), 'The sensor isn\'t reporting now.')
        self.assertEqual({}, air.air_quality('us_epa', 9.0, [9.0, None, None]), 'Too little history.')
        self.assertEqual({}, air.air_quality('us_epa', 9.0, []), 'No PM2.5 in the archive.')
        self.assertEqual({}, air.air_quality(None, 9.0, [9.0] * 12), 'No scale.')

    def test_scale_from_config(self):
        self.assertEqual('us_epa', air.scale_from_config({}))
        self.assertEqual('us_epa', air.scale_from_config({'aqi_scale': 'US_EPA'}))
        self.assertIsNone(air.scale_from_config({'aqi_scale': 'none'}))
        self.assertIsNone(air.scale_from_config({'aqi_scale': 'eu_caqi'}), 'Not supported yet.')


class TestSmokeAndHaze(unittest.TestCase):

    def test_smoke(self):
        self.assertEqual(711, c.from_sensors_air({'pm2_5': 60, 'voc_index': 220, 'humidity': 40}, T))
        self.assertEqual(711, c.from_sensors_air({'pm2_5': 60, 'voc_index': 220, 'humidity': 99}, T), 'Smoke in humid air.')
        self.assertIsNone(c.from_sensors_air({'pm2_5': 20, 'voc_index': 300}, T), 'VOCs alone aren\'t smoke.')

    def test_haze(self):
        self.assertEqual(721, c.from_sensors_air({'pm2_5': 40, 'voc_index': 100, 'humidity': 50}, T))
        self.assertEqual(721, c.from_sensors_air({'pm2_5': 40, 'humidity': 50}, T), 'Without a VOC sensor.')
        self.assertEqual(721, c.from_sensors_air({'pm2_5': 40}, T), 'Without humidity.')
        self.assertIsNone(c.from_sensors_air({'pm2_5': 40, 'humidity': 95}, T), 'Humid air is mist, not haze.')

    def test_clean(self):
        self.assertIsNone(c.from_sensors_air({'pm2_5': 8, 'voc_index': 100, 'humidity': 50}, T))
        self.assertIsNone(c.from_sensors_air({}, T))

    def test_source_order(self):
        sources = c.ConditionSources({}, 'test', metar_fetcher=lambda *a: None)
        self.assertEqual('sensors_air', sources.sources[1])
        smoky = {'temperature': 25, 'pm2_5': 70, 'voc_index': 250}
        # Smoke before the sunlight, which would only call it cloudy.
        self.assertEqual((711, 'sensors_air'), sources.condition(smoky, 0, radiation=200, max_solar_radiation=900))
        # Rain still comes first.
        self.assertEqual((503, 'sensors_precipitation'), sources.condition(dict(smoky, rainrate=3), 0))

    def test_thresholds(self):
        sources = c.ConditionSources({'sources': 'sensors_air', 'Thresholds': {'smoke_voc': '120', 'smoke_pm2_5': '20'}}, 'test')
        self.assertEqual((711, 'sensors_air'), sources.condition({'pm2_5': 25, 'voc_index': 130}, 0))


if __name__ == '__main__':
    unittest.main()
