#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""The sun and moon at the station, for the file's optional "almanac" section.

From WeeWX's almanac, for the station's day:

    "almanac": {
      "sunrise": 1761218383, "sunset": 1761257375,
      "civil_dawn": 1761216697, "civil_dusk": 1761259060,
      "moonrise": 1761226268, "moonset": 1761260206,
      "moon_phase": 1, "moon_fullness": 4,
      "next_full_moon": 1762348755, "next_new_moon": 1763621233
    }

Times are Unix seconds. WeeWX always has the sunrise, sunset and moon phase; the rest need PyEphem
(the ephem module) installed with WeeWX, and are left out without it. A sunrise or sunset that
doesn't happen that day, near the poles, is left out too. "moon_phase" is 0 to 7: new, waxing
crescent, first quarter, waxing gibbous, full, waning gibbous, last quarter and waning crescent.
"moon_fullness" is the percentage of the moon that's lit.
"""

import logging

import weewx.almanac
from weeutil.weeutil import to_bool

log = logging.getLogger(__name__)

# Degrees below the horizon the sun's center is at civil dawn and dusk.
CIVIL_TWILIGHT = -6


def enabled(almanac_dict):
    """Whether [CurrentJSON] [[Almanac]] wants the section."""
    return to_bool((almanac_dict or {}).get('enable', True))


def read_almanac(timestamp, latitude, longitude, altitude=None):
    """Returns the almanac section for the station's day at timestamp, or an empty dict.

    Args:
        timestamp (float): Unix seconds; the day is the computer's local day, like WeeWX's.
        latitude (float): Degrees.
        longitude (float): Degrees.
        altitude (float|None): Meters.
    """
    try:
        almanac = weewx.almanac.Almanac(timestamp, latitude, longitude, altitude=altitude)
        section = {}
        _put(section, 'sunrise', almanac.sunrise)
        _put(section, 'sunset', almanac.sunset)
        if almanac.hasExtras:
            twilight = almanac(horizon=CIVIL_TWILIGHT).sun(use_center=1)
            _put(section, 'civil_dawn', twilight.rise)
            _put(section, 'civil_dusk', twilight.set)
            _put(section, 'moonrise', almanac.moon.rise)
            _put(section, 'moonset', almanac.moon.set)
        section['moon_phase'] = int(almanac.moon_index)
        section['moon_fullness'] = int(round(almanac.moon_fullness))
        if almanac.hasExtras:
            _put(section, 'next_full_moon', almanac.next_full_moon)
            _put(section, 'next_new_moon', almanac.next_new_moon)
        return section
    except Exception as e:  # noqa: BLE001 - an almanac extension that fails shouldn't stop the file
        log.info("Could not calculate the almanac: %s", e)
        return {}


def _put(section, key, value_helper):
    """Adds a time from the almanac, as whole Unix seconds, unless it doesn't happen."""
    value = value_helper.raw
    if value is not None:
        section[key] = int(round(value))
