#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Longer history in files of its own, which apps fetch only when they want it.

current.json is fetched often, so it only holds the last day. With [CurrentJSON] [[Archives]]
enabled, two more files are written beside it, less often, and current.json names them in
"archives":

    "archives": {"week": "history-week.json", "year": "history-year.json"}

history-week.json holds the last 7 days in hourly intervals, in the same shape as "history", and
is rewritten at most once an hour:

    {"format": "current-conditions-history", "version": 1, "time": ..., "units": "metric",
     "station": {"id": "weewx"}, "history": {"start": ..., "interval": 3600, "temperature": [...]}}

history-year.json holds the last 365 days, one value per day from WeeWX's daily summaries, and is
rewritten at most every 3 hours. "time" is the start of each day, since days aren't all the same
length. A total, such as rain, is the day's sum and the gust its highest; anything else has its
mean under its own key and its lowest and highest under key_min and key_max:

    {"format": "current-conditions-history", "version": 1, "time": ..., "units": "metric",
     "station": {"id": "weewx"},
     "daily": {"time": [...], "temperature": [...], "temperature_min": [...], "temperature_max": [...],
               "rain": [...]}}
"""

import logging
import os
import time

import weewx
import weewx.units
from weeutil.weeutil import archiveDaySpan, genDaySpans, to_bool

import user.current_json_history as histories

log = logging.getLogger(__name__)

FORMAT = 'current-conditions-history'
FORMAT_VERSION = 1

WEEK_HOURS = 7 * 24
YEAR_DAYS = 365
# Seconds after which each file is rewritten.
WEEK_EVERY = 3600
YEAR_EVERY = 3 * 3600


def options_from_config(archives_dict):
    """Returns {'week': filename, 'year': filename} from [[Archives]], without empty names, or None if it's off."""
    archives_dict = archives_dict or {}
    if not to_bool(archives_dict.get('enable', False)):
        return None
    names = {}
    for key, default in (('week', 'history-week.json'), ('year', 'history-year.json')):
        name = str(archives_dict.get(key, default) or '').strip()
        if name and name.lower() != 'none':
            names[key] = name
    return names or None


def is_due(path, every, now=None):
    """Whether a file is missing or older than every seconds."""
    try:
        return (now or time.time()) - os.path.getmtime(path) >= every
    except OSError:
        return True


def week_document(manager, timestamp, fields, station_id, precision=None):
    history = histories.read_history(manager, timestamp, fields, hours=WEEK_HOURS, interval=3600, precision=precision)
    return _document(timestamp, station_id, 'history', history)


def year_document(manager, timestamp, fields, station_id, precision=None):
    return _document(timestamp, station_id, 'daily', read_daily(manager, timestamp, fields, precision=precision))


def read_daily(manager, timestamp, fields, days=YEAR_DAYS, precision=None):
    """Returns the daily series of the last days to timestamp's, from the daily summaries, or {}."""
    precision = precision or {}
    daykeys = set(getattr(manager, 'daykeys', None) or ())
    fields = {name: key for name, key in histories.history_fields(fields, manager.sqlkeys).items() if name in daykeys}
    end = archiveDaySpan(timestamp).stop
    starts = [span.start for span in genDaySpans(end - days * 86400 + 43200, end)]
    if not starts or not fields:
        return {}
    index = {start: i for i, start in enumerate(starts)}

    daily = {}
    for name, key in fields.items():
        sql = ('SELECT dateTime, min, max, sum, wsum, sumtime FROM %s_day_%s WHERE dateTime >= ? AND dateTime < ? '
               'ORDER BY dateTime' % (manager.table_name, name))
        lows, highs, means, totals = ([None] * len(starts) for _ in range(4))
        for day, low, high, total, wsum, sumtime in manager.genSql(sql, (starts[0], end)):
            i = index.get(day)
            if i is None:
                continue
            lows[i], highs[i], totals[i] = low, high, total
            means[i] = wsum / sumtime if wsum is not None and sumtime else None
        places = precision.get(key, 2)
        convert = _converter(manager.std_unit_system, name)
        if key in histories.TOTALS:
            series = {key: totals}
        elif key in histories.HIGHEST:
            series = {key: highs}
        else:
            series = {key: means, key + '_min': lows, key + '_max': highs}
        for series_key, values in series.items():
            values = [None if v is None else _round(convert(v), places) for v in values]
            if any(v is not None for v in values):
                daily[series_key] = values
    if not daily:
        return {}
    return dict(time=starts, **daily)


def write_archives(manager, timestamp, fields, station_id, names, root, precision=None, write=None, now=None):
    """Writes each archive file that's due, and returns the names of those that exist."""
    builders = {'week': (week_document, WEEK_EVERY), 'year': (year_document, YEAR_EVERY)}
    written = {}
    for key, name in names.items():
        path = os.path.join(root, name)
        build, every = builders[key]
        if is_due(path, every, now):
            try:
                document = build(manager, timestamp, fields, station_id, precision)
            except Exception as e:  # noqa: BLE001 - an archive file mustn't stop current.json
                log.error("Could not build %s: %s", name, e)
                document = None
            if document:
                write(path, document)
        if os.path.exists(path):
            written[key] = name
    return written


def _document(timestamp, station_id, key, section):
    if not section:
        return None
    return {
        'format': FORMAT,
        'version': FORMAT_VERSION,
        'time': int(timestamp),
        'units': 'metric',
        'station': {'id': station_id},
        key: section,
    }


def _converter(us_units, name):
    unit, group = weewx.units.getStandardUnitType(us_units, name)
    target = weewx.units.getStandardUnitType(weewx.METRICWX, name)[0]
    if not unit or not target or unit == target:
        return float
    return lambda value: weewx.units.convert(weewx.units.ValueTuple(float(value), unit, group), target).value


def _round(value, places):
    return int(round(value)) if places == 0 else round(value, places)
