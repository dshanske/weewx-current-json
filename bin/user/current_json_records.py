#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Records, totals and degree days over longer periods, for the file's "records" and "yesterday".

    "yesterday": {"temperature_max": 19.4, "temperature_max_time": ..., "rain": 0.0, ...},
    "records": {
      "week": {"temperature_max": 23.1, "temperature_max_time": ..., "rain": 12.4, ...},
      "month": {...}, "year": {...}, "rain_year": {...}, "all_time": {...}
    }

Each period has the same keys as "today": the highest and lowest temperature and highest gust,
with when each was, and the totals, from the start of the period to the end of the station's day.
All of it comes from WeeWX's daily summaries, so it costs a query or two per reading whatever the
period's length. The week starts on [Station] week_start, and the rain year in [Station]
rain_year_start; the rain year is left out when it starts in January, being the same as the year.
"""

import logging

import weewx
import weewx.units
from weeutil.weeutil import (TimeSpan, archiveDaySpan, archiveMonthSpan, archiveRainYearSpan, archiveWeekSpan,
                             archiveYearSpan, to_bool, to_int)

log = logging.getLogger(__name__)

PERIODS = ('week', 'month', 'year', 'rain_year', 'all_time')

# WeeWX's default bases for degree days, which its reports' [[DegreeDays]] can change.
DEFAULT_BASES = {
    'heatdeg': (65.0, 'degree_F'),
    'cooldeg': (65.0, 'degree_F'),
    'growdeg': (50.0, 'degree_F'),
}
BASE_OPTIONS = {'heatdeg': 'heating_base', 'cooldeg': 'cooling_base', 'growdeg': 'growing_base'}


def options_from_config(records_dict):
    """Returns the periods [CurrentJSON] [[Records]] asks for, or None if it's off."""
    records_dict = records_dict or {}
    if not to_bool(records_dict.get('enable', True)):
        return None
    periods = records_dict.get('periods', list(PERIODS))
    if isinstance(periods, str):
        periods = [p.strip() for p in periods.split(',')]
    unknown = [p for p in periods if p and p not in PERIODS]
    if unknown:
        log.error("Ignoring unknown [[Records]] periods: %s", ', '.join(unknown))
    return [p for p in PERIODS if p in periods]


def period_spans(timestamp, periods, first_timestamp=None, week_start=6, rain_year_start=1):
    """Returns {period: TimeSpan}, each from its start to the end of timestamp's day.

    The spans end at midnight so that WeeWX answers them from the daily summaries.
    """
    end = archiveDaySpan(timestamp).stop
    starts = {
        'week': archiveWeekSpan(timestamp, startOfWeek=week_start).start,
        'month': archiveMonthSpan(timestamp).start,
        'year': archiveYearSpan(timestamp).start,
    }
    if rain_year_start != 1:
        starts['rain_year'] = archiveRainYearSpan(timestamp, rain_year_start).start
    if first_timestamp is not None:
        starts['all_time'] = archiveDaySpan(first_timestamp).start
    return {p: TimeSpan(starts[p], end) for p in periods if p in starts}


def degree_day_bases(config_dict):
    """Returns {type: base in degree_C}, from [StdReport] [[Defaults]] [[[Units]]] [[[[DegreeDays]]]]."""
    units = config_dict.get('StdReport', {}).get('Defaults', {}).get('Units', {})
    dd_dict = units.get('DegreeDays', {}) if hasattr(units, 'get') else {}
    bases = {}
    for kind, default in DEFAULT_BASES.items():
        value = dd_dict.get(BASE_OPTIONS[kind], default)
        try:
            base = weewx.units.ValueTuple(float(value[0]), value[1], 'group_temperature')
            bases[kind] = weewx.units.convert(base, 'degree_C').value
        except (IndexError, KeyError, TypeError, ValueError):
            log.error("Ignoring [[DegreeDays]] %s = %r", BASE_OPTIONS[kind], value)
            bases[kind] = weewx.units.convert(weewx.units.ValueTuple(default[0], default[1], 'group_temperature'),
                                              'degree_C').value
    return bases


def degree_days(manager, span, bases):
    """Returns the heating, cooling and growing degree days over a span, in degree_C_day, or {}.

    Like WeeWX, each day counts by how far its mean temperature is from the base. The means come
    from the daily summary of outTemp in one query, rather than one per day.
    """
    if 'outTemp' not in (getattr(manager, 'daykeys', None) or ()):
        return {}
    sql = ('SELECT wsum, sumtime FROM %s_day_outTemp WHERE dateTime >= ? AND dateTime < ? AND sumtime > 0'
           % manager.table_name)
    unit, group = weewx.units.getStandardUnitType(manager.std_unit_system, 'outTemp')
    means = []
    for wsum, sumtime in manager.genSql(sql, (span.start, span.stop)):
        if wsum is None or not sumtime:
            continue
        mean = wsum / sumtime
        if unit and unit != 'degree_C':
            mean = weewx.units.convert(weewx.units.ValueTuple(mean, unit, group), 'degree_C').value
        means.append(mean)
    if not means:
        return {}
    return {
        'heatdeg': round(sum(max(0.0, bases['heatdeg'] - mean) for mean in means), 1),
        'cooldeg': round(sum(max(0.0, mean - bases['cooldeg']) for mean in means), 1),
        'growdeg': round(sum(max(0.0, mean - bases['growdeg']) for mean in means), 1),
    }


def read_records(summarize, spans, manager=None, bases=None):
    """Returns the records section: summarize(span) for each period, with its degree days but
    for all_time, or an empty dict.

    Args:
        summarize (callable): Called with a TimeSpan, returns its summary, like "today".
        spans (dict): TimeSpans keyed by period, from period_spans().
        manager: The archive's database manager, for the degree days; None leaves them out.
        bases (dict|None): Degree day bases, from degree_day_bases().
    """
    records = {}
    for period, span in spans.items():
        summary = summarize(span)
        if manager is not None and bases and period != 'all_time':
            summary.update(degree_days(manager, span, bases))
        if summary:
            records[period] = summary
    return records


def station_options(config_dict):
    """Returns (week_start, rain_year_start) from [Station], with WeeWX's defaults."""
    station_dict = config_dict.get('Station', {})
    return to_int(station_dict.get('week_start', 6)), to_int(station_dict.get('rain_year_start', 1))
