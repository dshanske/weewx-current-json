#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""The National Weather Service forecast and alerts, for the file's optional "forecast" section.

If the weewx-nws extension is installed, its database holds the NWS one-hour forecast, the
twelve-hour forecast periods (such as "Tonight" and "Thursday") and the active alerts for the
station. This reads the latest of each and returns them in the file's metric units:

    "forecast": {
      "source": "nws",
      "generated": 1761228000,
      "hourly": [{"time": ..., "end": ..., "temperature": 18.3, "code": 802, "summary": "Partly Cloudy", ...}],
      "periods": [{"name": "Tonight", "time": ..., "end": ..., "temperature": 12.2, ...}],
      "alerts": [{"event": "Heat Advisory", "headline": "...", "severity": "Moderate", ...}]
    }

The rows are chosen as weewx-nws chooses them for its own reports: the forecast generated most
recently, without the periods that have already ended, and the alerts of its last poll that
haven't ended. Anything weewx-nws doesn't have is left out, and so is the whole section without
weewx-nws.
"""

import logging

import weewx.units
from weeutil.weeutil import to_bool, to_int

import user.current_json_conditions as conditions

log = logging.getLogger(__name__)

# weewx-nws's interval column, which says what each row is.
HOURLY_INTERVAL = 60
PERIOD_INTERVAL = 720
ALERT_INTERVAL = 0

DEFAULT_HOURS = 24
DEFAULT_PERIODS = 14

# weewx-nws shows an alert for up to a day after it expires, because NWS is slow to reissue them.
ALERT_GRACE = 24 * 3600

FORECAST_COLUMNS = (
    'generatedTime', 'startTime', 'endTime', 'usUnits', 'name', 'isDaytime', 'outTemp', 'pop',
    'dewpoint', 'outHumidity', 'windSpeed', 'windSpeed2', 'windDir', 'iconUrl', 'shortForecast',
    'detailedForecast',
)

ALERT_COLUMNS = (
    'generatedTime', 'startTime', 'endTime', 'expirationTime', 'id', 'name', 'shortForecast',
    'detailedForecast', 'instruction', 'severity', 'certainty', 'urgency', 'senderName', 'areaDesc',
)


def options_from_config(forecast_dict):
    """Returns the read_forecast() options from [CurrentJSON] [[Forecast]], or None if it's disabled."""
    forecast_dict = forecast_dict or {}
    if not to_bool(forecast_dict.get('enable', True)):
        return None
    return {
        'hours': max(0, to_int(forecast_dict.get('hours', DEFAULT_HOURS))),
        'periods': max(0, to_int(forecast_dict.get('periods', DEFAULT_PERIODS))),
        'alerts': to_bool(forecast_dict.get('alerts', True)),
    }


def read_forecast(db_manager, now, hours=DEFAULT_HOURS, periods=DEFAULT_PERIODS, alerts=True):
    """Returns the forecast section, or an empty dict if weewx-nws has nothing current.

    Args:
        db_manager: A WeeWX database manager for weewx-nws's data binding.
        now (float): The time to read the forecast at, Unix seconds.
        hours (int): Most one-hour forecasts to include.
        periods (int): Most twelve-hour forecast periods to include.
        alerts (bool): Whether to include the active alerts.
    """
    section = {}
    generated = []
    if hours:
        rows = _forecast_rows(db_manager, HOURLY_INTERVAL, now, hours)
        if rows:
            section['hourly'] = [_hour(row) for row in rows]
            generated.append(rows[0]['generatedTime'])
    if periods:
        rows = _forecast_rows(db_manager, PERIOD_INTERVAL, now, periods)
        if rows:
            section['periods'] = [_period(row) for row in rows]
            generated.append(rows[0]['generatedTime'])
    if alerts:
        rows = _alert_rows(db_manager, now)
        if rows:
            section['alerts'] = [_alert(row) for row in rows]
    if not section:
        return {}
    forecast = {'source': 'nws'}
    if generated:
        forecast['generated'] = int(max(generated))
    forecast.update(section)
    return forecast


def _forecast_rows(db_manager, interval, now, limit):
    """Returns the latest forecast's rows of one interval that haven't ended, soonest first."""
    sql = ('SELECT %s FROM %s WHERE interval = ? AND endTime > ? AND generatedTime = '
           '(SELECT MAX(generatedTime) FROM %s WHERE interval = ?) ORDER BY startTime LIMIT ?'
           % (', '.join(FORECAST_COLUMNS), db_manager.table_name, db_manager.table_name))
    return [dict(zip(FORECAST_COLUMNS, row)) for row in db_manager.genSql(sql, (interval, now, interval, limit))]


def _alert_rows(db_manager, now):
    """Returns the alerts of weewx-nws's last poll that haven't ended, the most recently issued first.

    An alert ends at its end time, or, if NWS gave none, when it expires. Like weewx-nws, this
    keeps an alert for up to ALERT_GRACE after it expires, until NWS reissues it.
    """
    table = db_manager.table_name
    sql = ('SELECT %s FROM %s WHERE interval = ? AND dateTime = '
           '(SELECT MAX(dateTime) FROM %s WHERE interval = ?) ORDER BY generatedTime DESC'
           % (', '.join(ALERT_COLUMNS), table, table))
    rows = []
    for values in db_manager.genSql(sql, (ALERT_INTERVAL, ALERT_INTERVAL)):
        row = dict(zip(ALERT_COLUMNS, values))
        finish = row['endTime'] if row['endTime'] is not None else row['expirationTime']
        expires = row['expirationTime']
        if finish is not None and now < finish and (expires is None or expires > now - ALERT_GRACE):
            rows.append(row)
    return rows


def _hour(row):
    hour = _common(row)
    dewpoint = _convert(row['dewpoint'], row['usUnits'], 'dewpoint', 'degree_C', 1)
    if dewpoint is not None:
        hour['dewpoint'] = dewpoint
    if row['outHumidity'] is not None:
        hour['humidity'] = int(round(row['outHumidity']))
    return hour


def _period(row):
    period = {}
    if row['name']:
        period['name'] = str(row['name'])
    period.update(_common(row))
    if row['detailedForecast']:
        period['details'] = str(row['detailedForecast'])
    return period


def _common(row):
    """The keys the one-hour forecasts and the forecast periods share."""
    item = {'time': int(row['startTime']), 'end': int(row['endTime'])}
    if row['isDaytime'] is not None:
        item['daytime'] = bool(row['isDaytime'])
    units = row['usUnits']
    temperature = _convert(row['outTemp'], units, 'outTemp', 'degree_C', 1)
    if temperature is not None:
        item['temperature'] = temperature
    # NWS gives the wind as "9 mph" or "2 to 9 mph"; weewx-nws keeps the upper end of a range apart.
    speed = _convert(row['windSpeed'], units, 'windSpeed', 'meter_per_second', 2)
    if speed is not None:
        item['windspeed'] = speed
    speed_max = _convert(row['windSpeed2'], units, 'windSpeed', 'meter_per_second', 2)
    if speed_max is not None:
        item['windspeed_max'] = speed_max
    if row['windDir'] is not None:
        item['winddegree'] = int(round(row['windDir']))
    if row['pop'] is not None:
        item['pop'] = int(round(row['pop']))
    code = conditions.nws_icon_code(row['iconUrl'])
    if code is not None:
        item['code'] = code
    if row['shortForecast']:
        item['summary'] = str(row['shortForecast'])
    return item


def _alert(row):
    alert = {}
    for key, column in (('id', 'id'), ('event', 'name'), ('headline', 'shortForecast'),
                        ('description', 'detailedForecast'), ('instruction', 'instruction'),
                        ('severity', 'severity'), ('urgency', 'urgency'), ('certainty', 'certainty'),
                        ('sender', 'senderName'), ('area', 'areaDesc')):
        if row[column]:
            alert[key] = str(row[column])
    # weewx-nws stores an alert's effective time as its generatedTime, and its onset as startTime.
    for key, column in (('issued', 'generatedTime'), ('onset', 'startTime'), ('ends', 'endTime'),
                        ('expires', 'expirationTime')):
        if row[column] is not None:
            alert[key] = int(row[column])
    return alert


def _convert(value, us_units, obs_type, target, precision):
    """Converts a value stored in weewx-nws's unit system to a target unit, or None if it's missing."""
    if value is None:
        return None
    try:
        unit, group = weewx.units.getStandardUnitType(int(us_units), obs_type)
        converted = weewx.units.convert(weewx.units.ValueTuple(float(value), unit, group), target).value
    except (KeyError, TypeError, ValueError) as e:
        log.debug("Could not convert the forecast's %s: %s", obs_type, e)
        return None
    return round(converted, precision)
