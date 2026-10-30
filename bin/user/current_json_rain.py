#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""More about the rain, for the file's optional "rain" section.

    "rain": {"last_24h": 3.05, "last": 1761228000, "storm": 12.7, "storm_start": 1761170400}

"last_24h" is the rain in the 24 hours to the record, in mm, and "last" the time of the last
archive record with rain. The storm is the rain since it started raining with no dry spell longer
than storm_gap hours (24 by default) between: "storm" its total in mm and "storm_start" the time of
its first rain. It's left out when it hasn't rained within storm_gap hours.
"""

import logging

import weewx
import weewx.units
import weewx.xtypes
from weeutil.weeutil import TimeSpan, to_bool, to_float

log = logging.getLogger(__name__)

DEFAULT_STORM_GAP_HOURS = 24
# How far back a storm is followed.
STORM_LOOKBACK = 30 * 86400


def options_from_config(rain_dict):
    """Returns the read_rain() options from [CurrentJSON] [[Rain]], or None if it's off."""
    rain_dict = rain_dict or {}
    if not to_bool(rain_dict.get('enable', True)):
        return None
    gap = to_float(rain_dict.get('storm_gap', DEFAULT_STORM_GAP_HOURS))
    return {'storm_gap': max(1.0, gap) * 3600}


def read_rain(manager, timestamp, storm_gap=DEFAULT_STORM_GAP_HOURS * 3600):
    """Returns the rain section, or an empty dict for a station without a rain gauge."""
    if 'rain' not in manager.sqlkeys:
        return {}
    section = {}
    try:
        total = weewx.xtypes.get_aggregate('rain', TimeSpan(timestamp - 86400, timestamp), 'sum', manager)
        if total is not None and total.value is not None:
            section['last_24h'] = round(weewx.units.convert(total, 'mm').value, 2)
    except (weewx.UnknownType, weewx.UnknownAggregation):
        pass
    last = last_rain(manager, timestamp)
    if last is None:
        return section
    section['last'] = last
    if timestamp - last <= storm_gap:
        section.update(storm(manager, timestamp, storm_gap))
    return section


def last_rain(manager, timestamp):
    """Returns the time of the last record with rain, at or before timestamp, or None.

    The daily summaries find the day, so it doesn't matter how long it has been dry. Only
    timestamp's own day can have rain after it, so the two latest days with rain are enough.
    """
    table = manager.table_name
    sql = 'SELECT MAX(dateTime) FROM %s WHERE dateTime >= ? AND dateTime <= ? AND rain > 0' % table
    if 'rain' in (getattr(manager, 'daykeys', None) or ()):
        days = [row[0] for row in manager.genSql(
            'SELECT dateTime FROM %s_day_rain WHERE sum > 0 AND dateTime <= ? ORDER BY dateTime DESC LIMIT 2' % table,
            (timestamp,))]
    else:
        days = [timestamp - STORM_LOOKBACK]
    for day in days:
        row = manager.getSql(sql, (day, timestamp))
        if row and row[0] is not None:
            return int(row[0])
    return None


def storm(manager, timestamp, storm_gap):
    """Returns the current storm's total and start, following its rain back until a long enough dry spell."""
    sql = ('SELECT dateTime, usUnits, rain FROM %s WHERE dateTime > ? AND dateTime <= ? AND rain > 0 '
           'ORDER BY dateTime DESC' % manager.table_name)
    total = 0.0
    start = None
    for stamp, us_units, rain in manager.genSql(sql, (timestamp - STORM_LOOKBACK, timestamp)):
        if start is not None and start - stamp > storm_gap:
            break
        unit, group = weewx.units.getStandardUnitType(us_units, 'rain')
        total += weewx.units.convert(weewx.units.ValueTuple(rain, unit, group), 'mm').value
        start = stamp
    if start is None:
        return {}
    return {'storm': round(total, 2), 'storm_start': int(start)}
