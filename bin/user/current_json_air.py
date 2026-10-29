#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Calculate an air quality index for the current conditions file.

The index is calculated from the station's PM2.5, which should already be corrected for the sensor
(for example, the EPA's correction for Plantower sensors, which the AirGradient ESPHome packages
apply before sending it). It is only written to the file, never stored in WeeWX.

Scales, chosen with aqi_scale in [CurrentJSON] [[AirQuality]]:

    us_epa      The US EPA AQI for PM2.5, as the hourly NowCast, with the breakpoints that took
                effect on 2024-05-06.
    none        No index.

Without enough PM2.5 to calculate it, such as during a sensor outage, there is no index, rather
than a stale or partial one.

Every function here works on plain values, so the rules can be tested without WeeWX running.
"""

import logging
import math

log = logging.getLogger(__name__)

DEFAULT_SCALE = 'us_epa'

# US EPA AQI for PM2.5, 2024 breakpoints (EPA fact sheet, "Final Updates to the Air Quality Index
# (AQI) for Particulate Matter", effective 2024-05-06). Each row: lowest and highest concentration in
# micrograms per cubic meter, lowest and highest index, category slug, name and color. The EPA's
# colors are RGB 0,228,0; 255,255,0; 255,126,0; 255,0,0; 143,63,151; 126,0,35. The top of the
# Hazardous row, 325.4 for 500, is from the EPA's AQI Technical Assistance Document.
US_EPA_PM2_5 = (
    (0.0, 9.0, 0, 50, 'good', 'Good', '#00e400'),
    (9.1, 35.4, 51, 100, 'moderate', 'Moderate', '#ffff00'),
    (35.5, 55.4, 101, 150, 'unhealthy_sensitive', 'Unhealthy for Sensitive Groups', '#ff7e00'),
    (55.5, 125.4, 151, 200, 'unhealthy', 'Unhealthy', '#ff0000'),
    (125.5, 225.4, 201, 300, 'very_unhealthy', 'Very Unhealthy', '#8f3f97'),
    (225.5, 325.4, 301, 500, 'hazardous', 'Hazardous', '#7e0023'),
)

# Hours of PM2.5 the NowCast uses, the most recent first, and how many of the most recent three
# must have data.
NOWCAST_HOURS = 12
NOWCAST_RECENT = 3
NOWCAST_RECENT_NEEDED = 2


def _truncate(value, places=1):
    """Truncates, as the EPA does for PM2.5 concentrations, rather than rounding."""
    factor = 10 ** places
    return math.floor(value * factor + 1e-9) / factor


def nowcast(hourly):
    """Returns the EPA NowCast of PM2.5 hourly means, or None without enough data.

    Args:
        hourly (list): Up to 12 hourly means, in micrograms per cubic meter, the most recent first,
            with None for an hour without data.

    Returns:
        float|None: The NowCast, truncated to one decimal place, or None if fewer than 2 of the 3
        most recent hours have data.
    """
    hours = list(hourly[:NOWCAST_HOURS])
    if sum(1 for c in hours[:NOWCAST_RECENT] if c is not None) < NOWCAST_RECENT_NEEDED:
        return None
    values = [c for c in hours if c is not None]
    highest = max(values)
    if highest <= 0:
        return 0.0
    # The weight factor follows how much the concentration has changed, but is at least 0.5.
    weight = max(min(values) / highest, 0.5)
    total = 0.0
    weights = 0.0
    for age, c in enumerate(hours):
        if c is not None:
            total += (weight ** age) * c
            weights += weight ** age
    return _truncate(total / weights)


def us_epa_aqi(concentration):
    """Returns the US EPA AQI of a PM2.5 concentration, and its category.

    Above the top breakpoint, the index continues on the Hazardous row's line, above 500.

    Args:
        concentration (float|None): PM2.5, micrograms per cubic meter, such as a NowCast.

    Returns:
        tuple: (index, slug, name, color), or (None, None, None, None) without a concentration.
    """
    if not isinstance(concentration, (int, float)) or isinstance(concentration, bool) or concentration < 0:
        return None, None, None, None
    c = _truncate(float(concentration))
    for c_low, c_high, i_low, i_high, slug, name, color in US_EPA_PM2_5:
        if c <= c_high:
            # A truncated concentration is never between two rows: each row starts 0.1 after the
            # last one ends.
            index = (i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low
            return int(math.floor(index + 0.5)), slug, name, color
    c_low, c_high, i_low, i_high, slug, name, color = US_EPA_PM2_5[-1]
    index = (i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low
    return int(math.floor(index + 0.5)), slug, name, color


def scale_from_config(air_dict):
    """Returns the AQI scale from [[AirQuality]], or None for no index."""
    scale = str((air_dict or {}).get('aqi_scale', DEFAULT_SCALE)).strip().lower()
    if scale in ('', 'none', 'false', 'off'):
        return None
    if scale != 'us_epa':
        log.error("Unknown aqi_scale %r; no AQI is written. Known: us_epa, none", scale)
        return None
    return scale


def air_quality(scale, current_pm2_5, hourly):
    """Returns the AQI properties for the file, or an empty dict without enough data.

    Args:
        scale (str|None): The AQI scale, from scale_from_config().
        current_pm2_5 (float|None): PM2.5 in the current record. Without it, the sensor isn't
            reporting, and there is no index.
        hourly (list): Hourly PM2.5 means for the NowCast, the most recent first.

    Returns:
        dict: 'aqi', 'aqi_category' and 'aqi_color', or empty.
    """
    if scale != 'us_epa' or not isinstance(current_pm2_5, (int, float)) or isinstance(current_pm2_5, bool):
        return {}
    index, _slug, name, color = us_epa_aqi(nowcast(hourly))
    if index is None:
        return {}
    return {'aqi': index, 'aqi_category': name, 'aqi_color': color}
