#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""The last day of observations, for the file's optional "history" section.

Each reading is summarized over equal intervals, half an hour by default, for the last 24 hours, so
that a reader can chart how it changed:

    "history": {
      "start": 1761145200,
      "interval": 1800,
      "temperature": [12.1, 11.8, null, ...],
      "rain": [0.0, 0.25, ...]
    }

"start" is when the first interval begins, in Unix seconds, and "interval" the length of each in
seconds. Each list has one value per interval, oldest first, with null for an interval without
data; the last interval is the one the current record is in, so it may not have ended. Rain and
snow are each interval's totals, the gust, rain rate and snow rate its highest, and everything else
its mean. Readings the archive doesn't have are left out.
"""

import logging

import weewx
import weewx.units

log = logging.getLogger(__name__)

DEFAULT_HOURS = 24
DEFAULT_INTERVAL_MINUTES = 30

# How each of the file's keys is summarized over an interval; anything else is averaged.
TOTALS = ('rain', 'snow')
HIGHEST = ('windgust', 'rainrate', 'snowrate')

# The wind direction can't be averaged as a number, so it's left out.
SKIPPED = ('winddegree',)


def options_from_config(history_dict):
    """Returns the read_history() options from [CurrentJSON] [[History]], or None if it's off."""
    history_dict = history_dict or {}
    try:
        hours = int(history_dict.get('hours', DEFAULT_HOURS))
        minutes = int(history_dict.get('interval', DEFAULT_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        log.error("Ignoring [[History]]: hours and interval must be whole numbers")
        hours, minutes = DEFAULT_HOURS, DEFAULT_INTERVAL_MINUTES
    if hours <= 0:
        return None
    return {'hours': hours, 'interval': max(5, minutes) * 60}


def history_fields(fields, columns):
    """Returns the file's keys keyed by WeeWX field for the history, of fields the archive has.

    Args:
        fields (dict): File keys keyed by WeeWX field, from current_json.fields_from_config().
        columns (iterable): The archive's columns.
    """
    columns = set(columns)
    chosen = {name: key for name, key in fields.items() if key not in SKIPPED}
    chosen.update(rain='rain', snow='snow')
    return {name: key for name, key in chosen.items() if name in columns}


def window(timestamp, hours, interval):
    """Returns (start, count): the start of the first interval and how many, ending with timestamp's."""
    end = -(-int(timestamp) // interval) * interval
    count = max(1, hours * 3600 // interval)
    return end - count * interval, count


def history_from_rows(rows, fields, start, interval, count, precision=None):
    """Returns the history section from archive rows, or an empty dict if there's nothing in it.

    Args:
        rows (iterable): Archive records, as dicts with dateTime, usUnits and the fields.
        fields (dict): File keys keyed by WeeWX field, from history_fields().
        start (int): The start of the first interval, Unix seconds.
        interval (int): Seconds in each interval.
        count (int): How many intervals.
        precision (dict|None): Decimal places of each file key; anything else gets 2.
    """
    precision = precision or {}
    values = {key: [[] for _ in range(count)] for key in fields.values()}
    for row in rows:
        # A record's time is the end of the archive interval it covers.
        index = (int(row['dateTime']) - start - 1) // interval
        if not 0 <= index < count:
            continue
        for name, key in fields.items():
            value = _metric(row.get(name), row.get('usUnits'), name)
            if value is not None:
                values[key][index].append(value)

    history = {}
    for key, buckets in values.items():
        series = [_summarize(key, bucket, precision.get(key, 2)) for bucket in buckets]
        if any(value is not None for value in series):
            history[key] = series
    if not history:
        return {}
    return dict(start=start, interval=interval, **history)


def read_history(manager, timestamp, fields, hours=DEFAULT_HOURS, interval=DEFAULT_INTERVAL_MINUTES * 60,
                 precision=None):
    """Returns the history section from the archive, in one query, or an empty dict."""
    fields = history_fields(fields, manager.sqlkeys)
    if not fields:
        return {}
    start, count = window(timestamp, hours, interval)
    names = list(fields)
    sql = 'SELECT dateTime, usUnits, %s FROM %s WHERE dateTime > ? AND dateTime <= ? ORDER BY dateTime' % (
        ', '.join(names), manager.table_name)
    columns = ['dateTime', 'usUnits'] + names
    rows = (dict(zip(columns, row)) for row in manager.genSql(sql, (start, int(timestamp))))
    return history_from_rows(rows, fields, start, interval, count, precision)


def _metric(value, us_units, name):
    """Converts a value from a record's unit system to METRICWX, or None if it's missing."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    value = float(value)
    if us_units is None:
        return value
    unit, group = weewx.units.getStandardUnitType(int(us_units), name)
    target = weewx.units.getStandardUnitType(weewx.METRICWX, name)[0]
    # A field WeeWX doesn't know the unit of is taken as it is, as for the observations.
    if not unit or not target or unit == target:
        return value
    return weewx.units.convert(weewx.units.ValueTuple(value, unit, group), target).value


def _summarize(key, values, places):
    if not values:
        return None
    if key in TOTALS:
        value = sum(values)
    elif key in HIGHEST:
        value = max(values)
    else:
        value = sum(values) / len(values)
    return int(round(value)) if places == 0 else round(value, places)
