#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Write the station's current conditions as JSON.

Each report cycle, normally every archive interval, this writes a JSON file in the current conditions
format, version 1, into the report's HTML_ROOT, for other software to read, such as the WeeWX
weather provider of the Simple Location WordPress plugin:

    {
      "format": "current-conditions",
      "version": 1,
      "time": 1761231600,
      "units": "metric",
      "station": {"id": "...", "name": "...", "latitude": ..., "longitude": ..., "altitude": ...},
      "observations": {"temperature": 21.5, "humidity": 60, ...},
      "derived": {"code": "sensorsclouds", "cloudiness": "sensorsclouds", "aqi": "us_epa"},
      "today": {"temperature_max": 24.3, "temperature_max_time": 1761228000, ...},
      "trend": {"hours": 3, "pressure": -1.2, "temperature": 2.4},
      "almanac": {"sunrise": 1761218383, "sunset": 1761257375, "moon_phase": 1, ...},
      "history": {"start": 1761145200, "interval": 1800, "temperature": [...], ...},
      "forecast": {"source": "nws", "hourly": [...], "periods": [...], "alerts": [...]}
    }

Values are in metric units, WeeWX's METRICWX system: degrees C, hPa
(mbar), m/s, mm, mm/h, W/m^2, lux, micrograms per cubic meter and ppm. Readings the station doesn't
have are left out. The condition code and cloud cover, which WeeWX doesn't have, are derived as
described in user.current_json_conditions, and "derived" says which source gave each. The air
quality index, with its category and color, is calculated as described in user.current_json_air,
and "derived" names its scale. "today" holds the day's extremes and totals so far, and "trend" the
change over the last few hours. "almanac" holds the day's sun and moon times, as described in
user.current_json_almanac, and "history" each reading over the last day, as described in
user.current_json_history. If weewx-nws is installed, "forecast" holds its forecast and
alerts, as described in user.current_json_forecast; it is optional, and adds to the format without
changing anything else in it.
"""

import datetime
import json
import logging
import os
import tempfile
import time

import weewx
import weewx.manager
import weewx.reportengine
import weewx.units
import weewx.xtypes
from weeutil.weeutil import TimeSpan, archiveDaySpan, to_bool, to_int

import user.current_json_air as air
import user.current_json_almanac as almanacs
import user.current_json_archives as archive_files
import user.current_json_conditions as conditions
import user.current_json_forecast as forecasts
import user.current_json_history as histories
import user.current_json_rain as rains
import user.current_json_records as periods
import user.current_json_sensors as hardware

log = logging.getLogger(__name__)

VERSION = '0.3.0'

FORMAT = 'current-conditions'
FORMAT_VERSION = 1

# WeeWX observation types and the key each one becomes in the file. Rain and snow are the last
# hour's totals, added separately, and lightning only feeds the condition. [CurrentJSON] [[Fields]] can
# read a key from another WeeWX field; see fields_from_config().
OBSERVATIONS = {
    'outTemp': 'temperature',
    'outHumidity': 'humidity',
    'dewpoint': 'dewpoint',
    'heatindex': 'heatindex',
    'windchill': 'windchill',
    # WeeWX's apparent temperature, from temperature, humidity and wind, and its estimate of the
    # height of the cloud base, in meters, from the temperature and dewpoint.
    'appTemp': 'apptemp',
    'cloudbase': 'cloudbase',
    'barometer': 'pressure',
    'windSpeed': 'windspeed',
    'windDir': 'winddegree',
    'windGust': 'windgust',
    'rainRate': 'rainrate',
    # A snow sensor's depth on the ground and rate of snowfall.
    'snowDepth': 'snowdepth',
    'snowRate': 'snowrate',
    'radiation': 'radiation',
    'illuminance': 'illuminance',
    'UV': 'uv',
    'pm1_0': 'pm1_0',
    'pm2_5': 'pm2_5',
    'pm10_0': 'pm10_0',
    'co': 'co',
    'co2': 'co2',
    'nh3': 'nh3',
    'o3': 'o3',
    'pb': 'pb',
    'so2': 'so2',
    # Sensirion SGP40/SGP41 gas indices, 1-500, without a unit. WeeWX has no standard names for
    # these, so they're read from fields named after what they hold.
    'voc_index': 'voc_index',
    'nox_index': 'nox_index',
}

# Decimal places for each key; anything else is rounded to 2.
PRECISION = {
    'humidity': 0,
    'winddegree': 0,
    'radiation': 0,
    'illuminance': 0,
    'voc_index': 0,
    'nox_index': 0,
    'cloudbase': 0,
    'lightning_strikes': 0,
    'apptemp': 1,
    'lightning_distance': 1,
    'temperature': 1,
    'dewpoint': 1,
    'heatindex': 1,
    'windchill': 1,
    'pressure': 1,
    'uv': 1,
}


def fields_from_config(sloc_dict):
    """Returns the WeeWX field each of the file's keys is read from, with [[Fields]] applied.

    [[Fields]] maps a key of the file to the WeeWX field to read it from, such as
    ``voc_index = voc`` for a station that stores the VOC index in a field named voc. An empty
    value, or ``none``, leaves the key out. Only the file's own keys can be mapped.

    Args:
        sloc_dict (dict): The [CurrentJSON] section.

    Returns:
        dict: File keys, keyed by WeeWX field, like OBSERVATIONS.
    """
    fields = dict(OBSERVATIONS)
    known = set(OBSERVATIONS.values())
    for key, weewx_name in ((sloc_dict or {}).get('Fields') or {}).items():
        if key not in known:
            log.error("Ignoring [[Fields]] %s: not a key of the file", key)
            continue
        fields = {name: file_key for name, file_key in fields.items() if file_key != key}
        weewx_name = str(weewx_name or '').strip()
        if weewx_name and weewx_name.lower() != 'none':
            fields[weewx_name] = key
    return fields


def observations_from_record(record, hour_rain_mm=None, fields=None, hour_snow_mm=None):
    """Converts an archive record to the file's observations.

    Args:
        record (dict): A WeeWX archive record, in any unit system.
        hour_rain_mm (float|None): Rain in the hour ending at the record, in mm.
        fields (dict|None): File keys keyed by WeeWX field, from fields_from_config(). Default
            OBSERVATIONS.
        hour_snow_mm (float|None): Snowfall in the hour ending at the record, in mm.

    Returns:
        dict: Observations keyed by the file's names, in its units, without missing readings.
    """
    metric = weewx.units.to_METRICWX(record)
    observations = {}
    for weewx_name, key in (OBSERVATIONS if fields is None else fields).items():
        value = metric.get(weewx_name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            precision = PRECISION.get(key, 2)
            observations[key] = int(round(float(value))) if precision == 0 else round(float(value), precision)
    if isinstance(hour_rain_mm, (int, float)) and not isinstance(hour_rain_mm, bool):
        observations['rain'] = round(float(hour_rain_mm), 2)
    if isinstance(hour_snow_mm, (int, float)) and not isinstance(hour_snow_mm, bool):
        observations['snow'] = round(float(hour_snow_mm), 2)
    return observations


# The extremes of "today", "yesterday" and each period of "records": (key, file key it's of, aggregate).
TODAY = (
    ('temperature_max', 'temperature', 'max'),
    ('temperature_max_time', 'temperature', 'maxtime'),
    ('temperature_min', 'temperature', 'min'),
    ('temperature_min_time', 'temperature', 'mintime'),
    ('windgust_max', 'windgust', 'max'),
    ('windgust_max_time', 'windgust', 'maxtime'),
)

# Their totals: (key, WeeWX field, unit, decimal places).
TOTALS = (
    ('rain', 'rain', 'mm', 2),
    ('snow', 'snow', 'mm', 2),
    ('et', 'ET', 'mm', 2),
    ('windrun', 'windrun', 'km', 1),
    ('lightning_strikes', 'lightning_strike_count', None, 0),
)

# The file keys "trend" gives the change of.
TREND_KEYS = ('pressure', 'temperature')
DEFAULT_TREND_HOURS = 3


def local_timezone():
    """Returns the IANA name of the computer's time zone, such as America/New_York, or None.

    WeeWX works in the computer's local time, so this is the station's time zone. It's read from
    TZ, /etc/timezone or the target of /etc/localtime, whichever first names a known zone.
    """
    candidates = []
    tz = os.environ.get('TZ', '').lstrip(':')
    if tz:
        candidates.append(tz)
    try:
        with open('/etc/timezone', encoding='utf-8') as f:
            candidates.append(f.read().strip())
    except OSError:
        pass
    target = os.path.realpath('/etc/localtime')
    if '/zoneinfo/' in target:
        name = target.split('/zoneinfo/', 1)[1]
        for prefix in ('posix/', 'right/'):
            if name.startswith(prefix):
                name = name[len(prefix):]
        candidates.append(name)
    for name in candidates:
        if _zone(name) is not None:
            return name
    return None


def _zone(name):
    """Returns the zoneinfo time zone of an IANA name, or None if it isn't one."""
    if not name or name.startswith('/') or '..' in name:
        return None
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(name)
    except Exception:  # noqa: BLE001 - no zoneinfo, no tz database, or an unknown name
        return None


def utc_offset(timestamp, timezone=None):
    """Returns the offset from UTC, in seconds, at a time, in the named zone or the computer's local time."""
    zone = _zone(timezone)
    if zone is not None:
        return int(datetime.datetime.fromtimestamp(timestamp, zone).utcoffset().total_seconds())
    return int(time.localtime(timestamp).tm_gmtoff)


def station_from_config(config_dict, stn_info=None, timestamp=None):
    """Returns the station description from weewx.conf's [Station] and [CurrentJSON] sections.

    With a timestamp, it includes the time zone, and its offset from UTC at that time.
    """
    station_dict = config_dict.get('Station', {})
    sloc_dict = config_dict.get('CurrentJSON', {})

    station = {}
    location = station_dict.get('location', '')
    if isinstance(location, list):
        location = ', '.join(location)
    station['id'] = str(sloc_dict.get('station_id') or 'weewx')
    name = sloc_dict.get('station_name') or location
    if name:
        station['name'] = str(name)
    try:
        station['latitude'] = round(float(station_dict['latitude']), 6)
        station['longitude'] = round(float(station_dict['longitude']), 6)
    except (KeyError, TypeError, ValueError):
        pass
    if stn_info is not None and getattr(stn_info, 'altitude_vt', None) is not None:
        altitude = weewx.units.convert(stn_info.altitude_vt, 'meter')
        if altitude.value is not None:
            station['altitude'] = round(altitude.value)
    url = sloc_dict.get('station_url') or station_dict.get('station_url')
    if url:
        station['url'] = str(url)
    webcam = sloc_dict.get('webcam_url')
    if webcam:
        station['webcam'] = str(webcam)
    text = sloc_dict.get('attribution_text')
    if text:
        attribution = {'text': str(text)}
        attribution_url = sloc_dict.get('attribution_url') or url
        if attribution_url:
            attribution['url'] = str(attribution_url)
        station['attribution'] = attribution
    if timestamp is not None:
        timezone = str(sloc_dict.get('timezone') or '') or local_timezone()
        if timezone:
            station['timezone'] = timezone
        station['utc_offset'] = utc_offset(timestamp, timezone)
    return station


def today_from_aggregates(aggregate, fields):
    """Returns the "today" section: the day's extremes and totals so far, in the file's units.

    The same summary, over other spans, makes "yesterday" and each period of "records".

    Args:
        aggregate (callable): Called with a WeeWX field and an aggregate, such as 'max' or 'sum',
            returns the aggregate over the day so far as a ValueTuple, or None.
        fields (dict): File keys keyed by WeeWX field, from fields_from_config().
    """
    field_of = {key: name for name, key in fields.items()}
    today = {}
    for key, file_key, aggregate_type in TODAY:
        name = field_of.get(file_key)
        value = aggregate(name, aggregate_type) if name else None
        if value is None or value.value is None:
            continue
        if aggregate_type.endswith('time'):
            today[key] = int(value.value)
        else:
            # A field WeeWX doesn't know the unit of is taken as it is, as for the observations.
            unit = weewx.units.getStandardUnitType(weewx.METRICWX, name)[0]
            if unit and value.unit:
                value = weewx.units.convert(value, unit)
            today[key] = round(float(value.value), PRECISION.get(file_key, 2))
    for key, name, unit, places in TOTALS:
        # WeeWX's daily summaries sum to 0 without any readings, which would claim a sensor the
        # station doesn't have.
        count = aggregate(name, 'count')
        if count is None or not count.value:
            continue
        value = aggregate(name, 'sum')
        if value is None or value.value is None:
            continue
        if unit and value.unit:
            value = weewx.units.convert(value, unit)
        today[key] = int(round(value.value)) if places == 0 else round(float(value.value), places)
    return today


def trend(observations, earlier, hours):
    """Returns the "trend" section: the change of pressure and temperature since an earlier record.

    Args:
        observations (dict): The current observations, from observations_from_record().
        earlier (dict): The observations of the record from `hours` before.
        hours (int): How many hours before.
    """
    changes = {}
    for key in TREND_KEYS:
        if key in observations and key in earlier:
            changes[key] = round(observations[key] - earlier[key], PRECISION.get(key, 2))
    return dict(hours=hours, **changes) if changes else {}


def build_document(record, station, observations, code=None, source=None, cloudiness=None, cloud_source=None,
                   air_quality=None, aqi_scale=None, forecast=None, today=None, trend=None,
                   almanac=None, history=None, metar_station=None, *, yesterday=None, records=None,
                   rain=None, indoor=None, sensors=None, health=None, archives=None):
    """Returns the JSON document, as a dict.

    Args:
        record (dict): The archive record the observations are from.
        station (dict): The station description.
        observations (dict): Observations, from observations_from_record().
        code (int|None): Derived condition code.
        source (str|None): The source that gave the condition code.
        cloudiness (int|None): Derived cloud cover, in percent.
        cloud_source (str|None): The source that gave the cloud cover.
        air_quality (dict|None): 'aqi', 'aqi_category' and 'aqi_color', from
            user.current_json_air.air_quality(), or empty without an index.
        aqi_scale (str|None): The scale of the index.
        forecast (dict|None): The forecast section, from user.current_json_forecast.read_forecast(),
            or empty to leave it out.
        today (dict|None): The today section, from today_from_aggregates(), or empty to leave it out.
        trend (dict|None): The trend section, from trend(), or empty to leave it out.
        almanac (dict|None): The almanac section, from user.current_json_almanac.read_almanac(),
            or empty to leave it out.
        history (dict|None): The history section, from user.current_json_history.read_history(),
            or empty to leave it out.
        metar_station (str|None): The airport whose METAR gave the condition or the cloud cover,
            if one did.
        yesterday, records, rain, indoor, sensors, health (dict|list|None): The sections of the
            same names, from user.current_json_records, user.current_json_rain and
            user.current_json_sensors, or empty to leave them out.
        archives (dict|None): The archive files' names, from user.current_json_archives.
    """
    document = {
        'format': FORMAT,
        'version': FORMAT_VERSION,
        'time': int(record['dateTime']),
        'units': 'metric',
        'station': station,
        'observations': dict(observations),
    }
    derived = {}
    if code is not None:
        document['observations']['code'] = int(code)
        derived['code'] = source
    if cloudiness is not None:
        document['observations']['cloudiness'] = int(cloudiness)
        derived['cloudiness'] = cloud_source
    if air_quality and air_quality.get('aqi') is not None:
        document['observations'].update(air_quality)
        derived['aqi'] = aqi_scale
    if metar_station and 'metar' in derived.values():
        derived['metar_station'] = metar_station
    if derived:
        document['derived'] = derived
    for key, section in (('today', today), ('yesterday', yesterday), ('records', records), ('trend', trend),
                         ('rain', rain), ('almanac', almanac), ('indoor', indoor), ('sensors', sensors),
                         ('health', health), ('history', history), ('archives', archives)):
        if section:
            document[key] = section
    if forecast:
        document['forecast'] = forecast
    document['generator'] = 'weewx-current-json %s; WeeWX %s' % (VERSION, weewx.__version__)
    return document


def write_atomically(path, document):
    """Writes the document as JSON, replacing the file in one step so readers never see half of it."""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix='.current-json-', suffix='.json')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as f:
            json.dump(document, f, ensure_ascii=False, separators=(',', ':'))
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


class CurrentJSONGenerator(weewx.reportengine.ReportGenerator):
    """Report generator that writes the current conditions JSON file."""

    def run(self):
        sloc_dict = self.config_dict.get('CurrentJSON', {})
        if not to_bool(sloc_dict.get('enable', True)):
            log.debug("Disabled in [CurrentJSON]")
            return
        start = time.time()

        binding = self.skin_dict.get('data_binding', 'wx_binding')
        manager = self.db_binder.get_manager(binding)
        record = self.record if self.record else manager.getRecord(self.gen_ts or manager.lastGoodStamp())
        if not record:
            log.info("No archive record to report")
            return

        timestamp = record['dateTime']
        fields = fields_from_config(sloc_dict)
        observations = observations_from_record(
            record,
            self.hour_rain(manager, timestamp),
            fields,
            self.hour_total(manager, 'snow', timestamp),
        )
        observations.update(self.lightning(manager, timestamp))

        user_agent = sloc_dict.get('user_agent') or ('weewx-current-json/%s' % VERSION)
        nws_manager_opener = self.nws_manager_opener()
        sources = conditions.ConditionSources(
            sloc_dict.get('Conditions', {}),
            user_agent,
            nws_manager_opener=nws_manager_opener,
        )
        metric = weewx.units.to_METRICWX(record)
        code, source = sources.condition(
            observations,
            timestamp,
            radiation=metric.get('radiation'),
            max_solar_radiation=metric.get('maxSolarRad'),
            lightning_count=metric.get('lightning_strike_count'),
            illuminance=metric.get('illuminance'),
        )
        cloudiness, cloud_source = sources.cloud_cover(
            timestamp,
            radiation=metric.get('radiation'),
            max_solar_radiation=metric.get('maxSolarRad'),
            illuminance=metric.get('illuminance'),
        )

        aqi_scale = air.scale_from_config(sloc_dict.get('AirQuality', {}))
        air_quality = {}
        if aqi_scale:
            pm2_5_field = next((name for name, key in fields.items() if key == 'pm2_5'), None)
            air_quality = air.air_quality(aqi_scale, observations.get('pm2_5'), self.hourly_means(manager, pm2_5_field, timestamp))

        station = station_from_config(self.config_dict, self.stn_info, timestamp)
        root = self.html_root()
        indoor_on, extra_on, sensor_names = hardware.sensor_options(sloc_dict.get('Sensors', {}))
        archive_names = archive_files.options_from_config(sloc_dict.get('Archives', {}))
        written = archive_files.write_archives(manager, timestamp, fields, station['id'], archive_names, root,
                                          PRECISION, write_atomically) if archive_names else None
        document = build_document(
            record,
            station,
            observations,
            code,
            source,
            cloudiness,
            cloud_source,
            air_quality,
            aqi_scale,
            self.forecast(nws_manager_opener, sloc_dict.get('Forecast', {}), timestamp),
            self.today(manager, sloc_dict.get('Today', {}), timestamp, fields),
            self.trend(manager, sloc_dict.get('Trend', {}), record, observations, fields),
            self.almanac(sloc_dict.get('Almanac', {}), timestamp),
            self.history(manager, sloc_dict.get('History', {}), timestamp, fields),
            sources.metar_station,
            yesterday=self.yesterday(manager, sloc_dict.get('Today', {}), timestamp, fields),
            records=self.records(manager, sloc_dict.get('Records', {}), timestamp, fields),
            rain=self.rain(manager, sloc_dict.get('Rain', {}), timestamp),
            indoor=hardware.indoor(record) if indoor_on else None,
            sensors=hardware.extra(record, sensor_names) if extra_on else None,
            health=hardware.health(record, sloc_dict.get('Health', {})),
            archives=written,
        )
        path = os.path.join(root, sloc_dict.get('filename', 'current.json'))
        write_atomically(path, document)
        log.info("Wrote %s in %.2f seconds", path, time.time() - start)

    def html_root(self):
        """Returns the report's HTML_ROOT, as an absolute path."""
        root = self.skin_dict.get('HTML_ROOT') or self.config_dict.get('StdReport', {}).get('HTML_ROOT', 'public_html')
        return os.path.join(self.config_dict.get('WEEWX_ROOT', ''), root)

    @staticmethod
    def hour_rain(manager, timestamp):
        """Returns the rain in the hour ending at timestamp, in mm, or None without a rain gauge."""
        return CurrentJSONGenerator.hour_total(manager, 'rain', timestamp)

    @staticmethod
    def hour_total(manager, field, timestamp):
        """Returns the total of a field, such as rain or snow, in the hour ending at timestamp, in mm.

        Returns None without the sensor: the field isn't in the archive, or has no values that hour.
        """
        try:
            total = weewx.xtypes.get_aggregate(field, TimeSpan(timestamp - 3600, timestamp), 'sum', manager)
        except (weewx.UnknownType, weewx.UnknownAggregation):
            return None
        if total is None or total.value is None:
            return None
        return weewx.units.convert(total, 'mm').value

    @staticmethod
    def hourly_means(manager, field, timestamp, hours=air.NOWCAST_HOURS):
        """Returns the hourly means of a PM field, in micrograms per cubic meter, for the NowCast.

        Args:
            manager: The archive's database manager.
            field (str|None): The WeeWX field, such as pm2_5.
            timestamp (int): The end of the most recent hour.
            hours (int): How many hours.

        Returns:
            list: Means, the most recent first, with None for an hour without data; empty if the
            field isn't in the archive.
        """
        if not field:
            return []
        means = []
        for age in range(hours):
            span = TimeSpan(timestamp - (age + 1) * 3600, timestamp - age * 3600)
            try:
                mean = weewx.xtypes.get_aggregate(field, span, 'avg', manager)
            except (weewx.UnknownType, weewx.UnknownAggregation):
                return []
            if mean is None or mean.value is None:
                means.append(None)
                continue
            if mean.unit is not None:
                mean = weewx.units.convert(mean, 'microgram_per_meter_cubed')
            means.append(float(mean.value))
        return means

    @staticmethod
    def summarize(manager, span, fields):
        """Returns the extremes and totals over a span, like "today"."""
        def aggregate(field, aggregate_type):
            try:
                return weewx.xtypes.get_aggregate(field, span, aggregate_type, manager)
            except (weewx.UnknownType, weewx.UnknownAggregation, weewx.CannotCalculate):
                return None

        return today_from_aggregates(aggregate, fields)

    def degree_day_bases(self):
        return periods.degree_day_bases(self.config_dict)

    def today(self, manager, today_dict, timestamp, fields):
        """Returns the today section, or None if [[Today]] disables it."""
        if not to_bool((today_dict or {}).get('enable', True)):
            return None
        span = archiveDaySpan(timestamp)
        today = self.summarize(manager, TimeSpan(span.start, timestamp), fields)
        today.update(periods.degree_days(manager, span, self.degree_day_bases()))
        return today

    def yesterday(self, manager, today_dict, timestamp, fields):
        """Returns the yesterday section, or None if [[Today]] disables it, or its yesterday option does."""
        today_dict = today_dict or {}
        if not to_bool(today_dict.get('enable', True)) or not to_bool(today_dict.get('yesterday', True)):
            return None
        span = archiveDaySpan(timestamp, days_ago=1)
        summary = self.summarize(manager, span, fields)
        summary.update(periods.degree_days(manager, span, self.degree_day_bases()))
        return summary

    def records(self, manager, records_dict, timestamp, fields):
        """Returns the records section, or None if [[Records]] disables it."""
        chosen = periods.options_from_config(records_dict)
        if not chosen:
            return None
        week_start, rain_year_start = periods.station_options(self.config_dict)
        spans = periods.period_spans(timestamp, chosen, manager.firstGoodStamp(), week_start, rain_year_start)
        return periods.read_records(lambda span: self.summarize(manager, span, fields), spans, manager,
                                    self.degree_day_bases())

    @staticmethod
    def rain(manager, rain_dict, timestamp):
        """Returns the rain section, or None if [[Rain]] disables it."""
        options = rains.options_from_config(rain_dict)
        if options is None:
            return None
        return rains.read_rain(manager, timestamp, **options)

    @staticmethod
    def lightning(manager, timestamp):
        """Returns the strikes in the last hour and, if there were any, the distance of the latest, in km."""
        if 'lightning_strike_count' not in manager.sqlkeys:
            return {}
        try:
            total = weewx.xtypes.get_aggregate('lightning_strike_count', TimeSpan(timestamp - 3600, timestamp), 'sum',
                                               manager)
        except (weewx.UnknownType, weewx.UnknownAggregation):
            return {}
        if total is None or total.value is None:
            return {}
        lightning = {'lightning_strikes': int(round(total.value))}
        if lightning['lightning_strikes'] and 'lightning_distance' in manager.sqlkeys:
            row = manager.getSql(
                'SELECT lightning_distance, usUnits FROM %s WHERE dateTime > ? AND dateTime <= ? '
                'AND lightning_distance IS NOT NULL ORDER BY dateTime DESC LIMIT 1' % manager.table_name,
                (timestamp - 3600, timestamp))
            if row:
                unit, group = weewx.units.getStandardUnitType(row[1], 'lightning_distance')
                km = weewx.units.convert(weewx.units.ValueTuple(row[0], unit, group), 'km').value
                lightning['lightning_distance'] = round(km, 1)
        return lightning

    @staticmethod
    def trend(manager, trend_dict, record, observations, fields):
        """Returns the trend section, or None if [[Trend]] sets hours to 0 or there's no earlier record."""
        hours = to_int((trend_dict or {}).get('hours', DEFAULT_TREND_HOURS))
        if not hours or hours <= 0:
            return None
        # The record nearest the time, within an archive interval or so either side.
        interval = (record.get('interval') or 5) * 60
        earlier = manager.getRecord(record['dateTime'] - hours * 3600, max_delta=max(interval, 300))
        if not earlier:
            return None
        return trend(observations, observations_from_record(earlier, fields=fields), hours)

    def almanac(self, almanac_dict, timestamp):
        """Returns the almanac section, or None if [[Almanac]] disables it or the station has no location."""
        if not almanacs.enabled(almanac_dict):
            return None
        station_dict = self.config_dict.get('Station', {})
        try:
            latitude = float(station_dict['latitude'])
            longitude = float(station_dict['longitude'])
        except (KeyError, TypeError, ValueError):
            return None
        altitude = None
        if self.stn_info is not None and getattr(self.stn_info, 'altitude_vt', None) is not None:
            altitude = weewx.units.convert(self.stn_info.altitude_vt, 'meter').value
        return almanacs.read_almanac(timestamp, latitude, longitude, altitude)

    @staticmethod
    def history(manager, history_dict, timestamp, fields):
        """Returns the history section, or None if [[History]] sets hours to 0."""
        options = histories.options_from_config(history_dict)
        if options is None:
            return None
        return histories.read_history(manager, timestamp, fields, precision=PRECISION, **options)

    @staticmethod
    def forecast(nws_manager_opener, forecast_dict, timestamp):
        """Returns the forecast section from weewx-nws, or None without weewx-nws or with [[Forecast]] disabled."""
        options = forecasts.options_from_config(forecast_dict)
        if options is None or nws_manager_opener is None:
            return None
        try:
            with nws_manager_opener() as manager:
                return forecasts.read_forecast(manager, timestamp, **options)
        except Exception as e:  # noqa: BLE001 - weewx-nws's database unavailable or not as expected
            log.info("Could not read the weewx-nws forecast: %s", e)
            return None

    def nws_manager_opener(self):
        """Returns a function opening weewx-nws's database, or None if weewx-nws isn't configured."""
        nws_dict = self.config_dict.get('NWS')
        if not nws_dict:
            return None
        binding = nws_dict.get('data_binding', 'nws_binding')
        if binding not in self.config_dict.get('DataBindings', {}):
            return None
        config_dict = self.config_dict

        def opener():
            return weewx.manager.open_manager_with_config(config_dict, binding)

        return opener
