#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Derive a weather condition code for the current conditions file.

WeeWX measures the weather but has no notion of "conditions", such as "rain" or "partly cloudy".
This module derives one from up to four sources, tried in a configurable order; the first that
gives a condition wins:

    sensors_precipitation   Lightning, rain and snow from the station's own sensors, and fog from
                            its humidity and dewpoint.
    metar                   The latest METAR of a nearby airport, from aviationweather.gov.
    sensors_clouds          Daytime cloud cover, from solar radiation compared with WeeWX's
                            clear-sky maximum (maxSolarRad).
    sensors_wind            Windy, from the station's wind speed.
    nws                     The current hour of the National Weather Service forecast, as stored
                            by the weewx-nws extension, if it is installed.

Condition codes are OpenWeatherMap-style codes, as the Simple Location WordPress plugin uses them:
800 clear, 801 few clouds, 802 scattered, 803 broken, 804 overcast, 500/503/504 rain, and so on.

Every function here works on plain values in the file's metric units (degrees C, m/s,
mm, mm/h, W/m^2), so the rules can be tested without WeeWX running.
"""

import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

# Sources, in the default order: measured or observed before forecast.
DEFAULT_SOURCES = ['sensors_precipitation', 'metar', 'sensors_clouds', 'sensors_wind', 'nws']

# Thresholds, overridable in [CurrentJSON] [[Conditions]] [[[Thresholds]]].
DEFAULT_THRESHOLDS = {
    # Rain rate, mm/h, at which rain becomes moderate, then heavy (American Meteorological Society).
    'rain_moderate': 2.5,
    'rain_heavy': 7.6,
    # Temperature, degrees C, at or below which precipitation is snow, and below which it may be mixed.
    'snow_temperature': 0.0,
    'mix_temperature': 2.0,
    # Fog: humidity, percent, at least; dewpoint depression, degrees C, at most; wind, m/s, below.
    'fog_humidity': 97.0,
    'fog_spread': 1.0,
    'fog_wind': 3.0,
    # Mist is the same with a lower humidity.
    'mist_humidity': 93.0,
    # Windy: wind speed, m/s, at least (Beaufort 6).
    'windy_speed': 10.8,
    # Cloud cover: the least clear-sky radiation, W/m^2, the estimate needs, so that it isn't made
    # with the sun near the horizon; and the ratios of measured to clear-sky radiation at or above
    # which the sky counts as clear, few, scattered and broken. Below the last it is overcast.
    'cloud_min_solar': 100.0,
    'cloud_clear': 0.75,
    'cloud_few': 0.55,
    'cloud_scattered': 0.35,
    'cloud_broken': 0.15,
}

# METAR sky cover, worst first, and its condition code.
METAR_COVER = {
    'OVX': 804,
    'OVC': 804,
    'BKN': 803,
    'SCT': 802,
    'FEW': 801,
    'SKC': 800,
    'CLR': 800,
    'CAVOK': 800,
    'NSC': 800,
    'NCD': 800,
}

# NWS forecast icon names, from the icon URL, and their condition code.
# See https://api.weather.gov/icons
NWS_ICONS = {
    'skc': 800,
    'few': 801,
    'sct': 802,
    'bkn': 803,
    'ovc': 804,
    'wind_skc': 400,
    'wind_few': 400,
    'wind_sct': 400,
    'wind_bkn': 400,
    'wind_ovc': 400,
    'snow': 601,
    'rain_snow': 616,
    'rain_sleet': 612,
    'snow_sleet': 611,
    'fzra': 511,
    'rain_fzra': 511,
    'snow_fzra': 511,
    'sleet': 611,
    'rain': 503,
    'rain_showers': 521,
    'rain_showers_hi': 521,
    'tsra': 211,
    'tsra_sct': 211,
    'tsra_hi': 211,
    'tornado': 781,
    'hurricane': 782,
    'tropical_storm': 782,
    'dust': 761,
    'smoke': 711,
    'haze': 721,
    'blizzard': 622,
    'fog': 741,
}


def thresholds_from_config(conditions_dict):
    """Returns the thresholds, with any set in the configuration in place of the defaults."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, value in (conditions_dict or {}).get('Thresholds', {}).items():
        if key in thresholds:
            try:
                thresholds[key] = float(value)
            except (TypeError, ValueError):
                log.error("Ignoring threshold %s = %r: not a number", key, value)
    return thresholds


def sources_from_config(conditions_dict):
    """Returns the sources to try, in order, skipping any that aren't known."""
    sources = (conditions_dict or {}).get('sources', DEFAULT_SOURCES)
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(',')]
    known = []
    for source in sources:
        if source in DEFAULT_SOURCES:
            known.append(source)
        elif source:
            log.error("Ignoring unknown conditions source %r", source)
    return known


def _number(observations, key):
    value = observations.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def from_sensors_precipitation(observations, thresholds, lightning_count=None):
    """Thunderstorms, rain, snow and fog from the station's sensors.

    Args:
        observations (dict): Observations in the file's units, keyed by its names.
        thresholds (dict): Thresholds, as in DEFAULT_THRESHOLDS.
        lightning_count (float|None): Lightning strikes in the archive interval, if the station
            has a lightning sensor.

    Returns:
        int|None: Condition code, or None if the sensors show none of these.
    """
    rate = _number(observations, 'rainrate')
    rain = _number(observations, 'rain')
    temperature = _number(observations, 'temperature')
    raining = (rate is not None and rate > 0) or (rain is not None and rain > 0)

    if lightning_count is not None and lightning_count > 0:
        return 201 if raining else 211

    if raining:
        if temperature is not None and temperature <= thresholds['snow_temperature']:
            return 601
        if temperature is not None and temperature < thresholds['mix_temperature']:
            return 616
        # Without a rate, the last hour's rain is the rate.
        intensity = rate if rate is not None else rain
        if intensity >= thresholds['rain_heavy']:
            return 504
        if intensity >= thresholds['rain_moderate']:
            return 503
        return 500

    humidity = _number(observations, 'humidity')
    dewpoint = _number(observations, 'dewpoint')
    wind = _number(observations, 'windspeed')
    if humidity is not None and temperature is not None and dewpoint is not None:
        calm = wind is None or wind < thresholds['fog_wind']
        close = (temperature - dewpoint) <= thresholds['fog_spread']
        if calm and close and humidity >= thresholds['fog_humidity']:
            return 741
        if calm and close and humidity >= thresholds['mist_humidity']:
            return 701
    return None


def from_sensors_clouds(radiation, max_solar_radiation, thresholds):
    """Daytime cloud cover from solar radiation compared with the clear-sky maximum.

    Args:
        radiation (float|None): Measured solar radiation, W/m^2, averaged over the archive interval.
        max_solar_radiation (float|None): WeeWX's theoretical clear-sky radiation (maxSolarRad).
        thresholds (dict): Thresholds, as in DEFAULT_THRESHOLDS.

    Returns:
        int|None: 800 to 804, or None at night, with the sun low, or without the readings.
    """
    if radiation is None or max_solar_radiation is None or max_solar_radiation < thresholds['cloud_min_solar']:
        return None
    ratio = radiation / max_solar_radiation
    if ratio >= thresholds['cloud_clear']:
        return 800
    if ratio >= thresholds['cloud_few']:
        return 801
    if ratio >= thresholds['cloud_scattered']:
        return 802
    if ratio >= thresholds['cloud_broken']:
        return 803
    return 804


def from_sensors_wind(observations, thresholds):
    """Windy, from the station's wind speed. Returns 400, or None."""
    wind = _number(observations, 'windspeed')
    return 400 if wind is not None and wind >= thresholds['windy_speed'] else None


def metar_weather_code(wx_string):
    """Returns the condition code for a METAR's present weather, such as "-RA BR", or None."""
    if not wx_string:
        return None
    tokens = wx_string.upper().split()
    best = None
    for token in tokens:
        light = token.startswith('-')
        heavy = token.startswith('+')
        body = token.lstrip('+-')
        if body.startswith('VC'):
            # In the vicinity, not at the airport.
            continue
        code = None
        if 'TS' in body:
            code = 201 if ('RA' in body or 'SH' in body) else 211
        elif 'FZRA' in body or 'FZDZ' in body:
            code = 511
        elif 'GR' in body or 'GS' in body:
            code = 624
        elif 'SN' in body and 'RA' in body:
            code = 616
        elif 'PL' in body:
            code = 611
        elif 'SN' in body or 'SG' in body:
            code = 600 if light else (602 if heavy else 601)
        elif 'SHRA' in body:
            code = 520 if light else (522 if heavy else 521)
        elif 'RA' in body:
            code = 500 if light else (504 if heavy else 503)
        elif 'DZ' in body:
            code = 300 if light else (302 if heavy else 301)
        elif 'FC' in body:
            code = 781
        elif 'SQ' in body:
            code = 771
        elif 'FG' in body:
            code = 741
        elif 'BR' in body:
            code = 701
        elif 'HZ' in body:
            code = 721
        elif 'FU' in body:
            code = 711
        elif 'VA' in body:
            code = 762
        elif 'DU' in body or 'SA' in body or 'SS' in body or 'DS' in body:
            code = 761
        # The first precipitation reported is the main one; obscurations only count alone.
        if code is not None and (best is None or (best in (701, 711, 721, 741, 761) and code not in (701, 711, 721, 741, 761))):
            best = code
    return best


def from_metar_report(report, now, max_age_minutes):
    """Returns the condition code of a METAR report from aviationweather.gov's JSON API, or None.

    Args:
        report (dict): One report, with obsTime (Unix seconds), wxString and cover.
        now (float): Current time, Unix seconds.
        max_age_minutes (float): Oldest report to use.
    """
    if not isinstance(report, dict):
        return None
    observed = report.get('obsTime')
    if not isinstance(observed, (int, float)) or now - observed > max_age_minutes * 60:
        return None
    code = metar_weather_code(report.get('wxString'))
    if code is not None:
        return code
    cover = report.get('cover')
    if isinstance(cover, str) and cover.upper() in METAR_COVER:
        return METAR_COVER[cover.upper()]
    # Without an overall cover, the worst layer.
    worst = None
    for layer in report.get('clouds') or []:
        layer_code = METAR_COVER.get(str(layer.get('cover', '')).upper()) if isinstance(layer, dict) else None
        if layer_code is not None and (worst is None or layer_code > worst):
            worst = layer_code
    return worst


def fetch_metar(station, user_agent, timeout=10):
    """Fetches the latest METAR of an airport from aviationweather.gov.

    Returns:
        dict|None: The report, or None if it couldn't be fetched.
    """
    url = 'https://aviationweather.gov/api/data/metar?' + urllib.parse.urlencode({'ids': station, 'format': 'json'})
    request = urllib.request.Request(url, headers={'User-Agent': user_agent, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reports = json.loads(response.read().decode('utf-8'))
    except Exception as e:  # noqa: BLE001 - any failure just means no METAR this time
        log.info("Could not fetch the METAR for %s: %s", station, e)
        return None
    return reports[0] if isinstance(reports, list) and reports else None


def nws_icon_code(icon_url):
    """Returns the condition code for an NWS forecast icon URL, or None.

    Icon URLs look like https://api.weather.gov/icons/land/day/sct,20?size=small, or with two
    conditions, .../land/night/tsra_sct,40/rain,60. The first condition is used.
    """
    if not isinstance(icon_url, str) or '/icons/' not in icon_url:
        return None
    path = urllib.parse.urlparse(icon_url).path
    parts = path.split('/')
    try:
        index = parts.index('icons')
        first = parts[index + 3]
    except (ValueError, IndexError):
        return None
    return NWS_ICONS.get(first.split(',')[0])


def nws_current_icon(db_manager, now):
    """Returns the icon URL of weewx-nws's one-hour forecast for the current hour, or None.

    Args:
        db_manager: A WeeWX database manager for weewx-nws's data binding.
        now (float): Current time, Unix seconds.
    """
    sql = ('SELECT iconUrl FROM %s WHERE interval = 60 AND startTime <= ? AND endTime > ? '
           'ORDER BY generatedTime DESC LIMIT 1' % db_manager.table_name)
    try:
        row = db_manager.getSql(sql, (now, now))
    except Exception as e:  # noqa: BLE001 - a missing or different table just means no forecast
        log.info("Could not read the weewx-nws forecast: %s", e)
        return None
    return row[0] if row else None


class ConditionSources:
    """Looks up the condition from the configured sources, in order."""

    def __init__(self, conditions_dict, user_agent, metar_fetcher=fetch_metar, nws_manager_opener=None):
        """
        Args:
            conditions_dict (dict): The [CurrentJSON] [[Conditions]] section.
            user_agent (str): User-Agent for requests to aviationweather.gov.
            metar_fetcher (callable): Fetches a METAR report; replaceable for testing.
            nws_manager_opener (callable|None): Returns a context manager giving a database manager
                for weewx-nws's binding, or None if weewx-nws isn't set up.
        """
        conditions_dict = conditions_dict or {}
        self.sources = sources_from_config(conditions_dict)
        self.thresholds = thresholds_from_config(conditions_dict)
        self.metar_station = str(conditions_dict.get('metar_station', '')).strip().upper()
        self.metar_max_age = float(conditions_dict.get('metar_max_age', 90))
        self.user_agent = user_agent
        self.metar_fetcher = metar_fetcher
        self.nws_manager_opener = nws_manager_opener

    def condition(self, observations, now, radiation=None, max_solar_radiation=None, lightning_count=None):
        """Returns (code, source), or (None, None) if no source gives a condition."""
        for source in self.sources:
            code = None
            if source == 'sensors_precipitation':
                code = from_sensors_precipitation(observations, self.thresholds, lightning_count)
            elif source == 'metar' and self.metar_station:
                code = from_metar_report(self.metar_fetcher(self.metar_station, self.user_agent), now, self.metar_max_age)
            elif source == 'sensors_clouds':
                code = from_sensors_clouds(radiation, max_solar_radiation, self.thresholds)
            elif source == 'sensors_wind':
                code = from_sensors_wind(observations, self.thresholds)
            elif source == 'nws' and self.nws_manager_opener is not None:
                code = self._nws(now)
            if code is not None:
                return code, source
        return None, None

    def _nws(self, now):
        try:
            with self.nws_manager_opener() as manager:
                return nws_icon_code(nws_current_icon(manager, now))
        except Exception as e:  # noqa: BLE001 - weewx-nws not installed or its database unavailable
            log.debug("weewx-nws forecast unavailable: %s", e)
            return None


def now():
    """Current time; a function so tests can replace it."""
    return time.time()
