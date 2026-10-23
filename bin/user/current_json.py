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
      "derived": {"code": "sensors_clouds"}
    }

Values are in metric units, WeeWX's METRICWX system: degrees C, hPa
(mbar), m/s, mm, mm/h, W/m^2, lux, micrograms per cubic meter and ppm. Readings the station doesn't
have are left out. The condition code, which WeeWX doesn't have, is derived as described in
user.current_json_conditions, and "derived" says which source gave it.
"""

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
from weeutil.weeutil import TimeSpan, to_bool

import user.current_json_conditions as conditions

log = logging.getLogger(__name__)

VERSION = '0.1.0'

FORMAT = 'current-conditions'
FORMAT_VERSION = 1

# WeeWX observation types and the key each one becomes in the file. Rain is the last hour's
# total, added separately, and lightning only feeds the condition.
OBSERVATIONS = {
    'outTemp': 'temperature',
    'outHumidity': 'humidity',
    'dewpoint': 'dewpoint',
    'heatindex': 'heatindex',
    'windchill': 'windchill',
    'barometer': 'pressure',
    'windSpeed': 'windspeed',
    'windDir': 'winddegree',
    'windGust': 'windgust',
    'rainRate': 'rainrate',
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
}

# Decimal places for each key; anything else is rounded to 2.
PRECISION = {
    'humidity': 0,
    'winddegree': 0,
    'radiation': 0,
    'illuminance': 0,
    'temperature': 1,
    'dewpoint': 1,
    'heatindex': 1,
    'windchill': 1,
    'pressure': 1,
    'uv': 1,
}


def observations_from_record(record, hour_rain_mm=None):
    """Converts an archive record to the file's observations.

    Args:
        record (dict): A WeeWX archive record, in any unit system.
        hour_rain_mm (float|None): Rain in the hour ending at the record, in mm.

    Returns:
        dict: Observations keyed by the file's names, in its units, without missing readings.
    """
    metric = weewx.units.to_METRICWX(record)
    observations = {}
    for weewx_name, key in OBSERVATIONS.items():
        value = metric.get(weewx_name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            precision = PRECISION.get(key, 2)
            observations[key] = int(round(float(value))) if precision == 0 else round(float(value), precision)
    if isinstance(hour_rain_mm, (int, float)) and not isinstance(hour_rain_mm, bool):
        observations['rain'] = round(float(hour_rain_mm), 2)
    return observations


def station_from_config(config_dict, stn_info=None):
    """Returns the station description from weewx.conf's [Station] and [CurrentJSON] sections."""
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
    text = sloc_dict.get('attribution_text')
    if text:
        attribution = {'text': str(text)}
        attribution_url = sloc_dict.get('attribution_url') or url
        if attribution_url:
            attribution['url'] = str(attribution_url)
        station['attribution'] = attribution
    return station


def build_document(record, station, observations, code=None, source=None):
    """Returns the JSON document, as a dict.

    Args:
        record (dict): The archive record the observations are from.
        station (dict): The station description.
        observations (dict): Observations, from observations_from_record().
        code (int|None): Derived condition code.
        source (str|None): The source that gave the condition code.
    """
    document = {
        'format': FORMAT,
        'version': FORMAT_VERSION,
        'time': int(record['dateTime']),
        'units': 'metric',
        'station': station,
        'observations': dict(observations),
    }
    if code is not None:
        document['observations']['code'] = int(code)
        document['derived'] = {'code': source}
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
        observations = observations_from_record(record, self.hour_rain(manager, timestamp))

        user_agent = sloc_dict.get('user_agent') or ('weewx-current-json/%s' % VERSION)
        sources = conditions.ConditionSources(
            sloc_dict.get('Conditions', {}),
            user_agent,
            nws_manager_opener=self.nws_manager_opener(),
        )
        metric = weewx.units.to_METRICWX(record)
        code, source = sources.condition(
            observations,
            timestamp,
            radiation=metric.get('radiation'),
            max_solar_radiation=metric.get('maxSolarRad'),
            lightning_count=metric.get('lightning_strike_count'),
        )

        document = build_document(record, station_from_config(self.config_dict, self.stn_info), observations, code, source)
        path = os.path.join(self.html_root(), sloc_dict.get('filename', 'current.json'))
        write_atomically(path, document)
        log.info("Wrote %s in %.2f seconds", path, time.time() - start)

    def html_root(self):
        """Returns the report's HTML_ROOT, as an absolute path."""
        root = self.skin_dict.get('HTML_ROOT') or self.config_dict.get('StdReport', {}).get('HTML_ROOT', 'public_html')
        return os.path.join(self.config_dict.get('WEEWX_ROOT', ''), root)

    @staticmethod
    def hour_rain(manager, timestamp):
        """Returns the rain in the hour ending at timestamp, in mm, or None without a rain gauge."""
        try:
            total = weewx.xtypes.get_aggregate('rain', TimeSpan(timestamp - 3600, timestamp), 'sum', manager)
        except (weewx.UnknownType, weewx.UnknownAggregation):
            return None
        if total is None or total.value is None:
            return None
        return weewx.units.convert(total, 'mm').value

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
