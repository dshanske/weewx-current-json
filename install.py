#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Installer for weewx-current-json.

Install with:

    weectl extension install weewx-current-json.zip
"""

from io import StringIO

import configobj

from setup import ExtensionInstaller

VERSION = '0.2.0'

# Written into weewx.conf as text, so its comments are kept. Options that only repeat a default
# are written commented out, so a later release's better default still applies.
CONFIG = """
[CurrentJSON]
    # This section configures weewx-current-json, which writes this station's current
    # conditions as JSON, for other software such as the Simple Location WordPress plugin.
    # See https://github.com/dshanske/weewx-current-json

    # Name of the file, written into the report's HTML_ROOT each archive interval.
    #filename = current.json

    # The station's ID, name and page. The name defaults to [Station] location, and the page to
    # [Station] station_url.
    #station_id = weewx
    #station_name = ""
    #station_url = ""

    # Credit shown with this station's weather on sites that use it, with a link. Leave the text
    # empty for no credit.
    #attribution_text = ""
    #attribution_url = ""

    # User-Agent sent to aviationweather.gov when a METAR is used. Please include a contact.
    #user_agent = "weewx-current-json (my-weather-site.com, me@my-weather-site.com)"

    # The station's time zone, as an IANA name such as America/New_York. The default is the
    # computer's, which WeeWX works in; set it only if the file doesn't have one.
    #timezone = ""

    # Address of an image from a webcam at the station, which apps can show and reload. A
    # relative address is taken from where this file is published.
    #webcam_url = ""

    [[Conditions]]
        # WeeWX doesn't know the conditions, such as "rain" or "partly cloudy", so they are
        # derived from these sources, tried in order; the first that gives one is used.
        # Remove a source to skip it.
        #   sensors_precipitation  lightning, rain, snow and fog from this station's sensors
        #   sensors_air            smoke or haze, from PM2.5 and a gas sensor's VOC index
        #   metar                  a nearby airport's METAR (set metar_station)
        #   sensors_clouds         daytime cloud cover, from solar radiation or illuminance
        #   sensors_wind           windy, from wind speed
        #   nws                    the NWS hourly forecast, if weewx-nws is installed
        #sources = sensors_precipitation, sensors_air, metar, sensors_clouds, sensors_wind, nws

        # Sources of the cloud cover, in percent, tried in order: sensors_clouds, metar, nws.
        #cloud_sources = sensors_clouds, metar, nws

        # ICAO ID of a nearby airport, such as KPHL, for the metar source. Empty skips it.
        #metar_station = ""

        # Oldest METAR to use, in minutes.
        #metar_max_age = 90

        [[[Thresholds]]]
            # Overrides for the thresholds of the sensor sources, in metric units. See the README.
            #rain_moderate = 2.5
            #rain_heavy = 7.6
            #cloud_clear = 0.75
            #smoke_pm2_5 = 35.5
            #smoke_voc = 150

    [[AirQuality]]
        # Air quality index, calculated from this station's PM2.5, which should already be
        # corrected for the sensor. Only written to the file. us_epa (the hourly NowCast, 2024
        # breakpoints) or none.
        #aqi_scale = us_epa

    [[Fields]]
        # Read a key of the file from a WeeWX field with another name, or leave it out with none.
        #voc_index = voc
        #uv = none

    [[Today]]
        # The day's high and low temperature, highest gust, totals and degree days so far.
        #enable = true

        # The same for yesterday.
        #yesterday = true

    [[Records]]
        # The highs, lows and totals of longer periods: week, month, year, rain_year (if
        # [Station] rain_year_start isn't January) and all_time.
        #enable = true
        #periods = week, month, year, rain_year, all_time

    [[Rain]]
        # Rain in the last 24 hours, when it last rained, and the current storm: the rain since
        # it started without a dry spell longer than storm_gap hours.
        #enable = true
        #storm_gap = 24

    [[Trend]]
        # Hours over which to give the change of pressure and temperature. 0 for none.
        #hours = 3

    [[History]]
        # Each reading over the last hours, summarized each interval minutes, for charts.
        # 0 hours for none.
        #hours = 24
        #interval = 30

    [[Almanac]]
        # Sunrise, sunset and the moon phase; with PyEphem installed, also twilight,
        # moonrise, moonset and the next full and new moon.
        #enable = true

    [[Sensors]]
        # Indoor readings and extra sensors (extraTemp1-8, extraHumid1-8, soilTemp1-4,
        # soilMoist1-4, leafTemp1-2, leafWet1-2). Off, since they say something about your home.
        #indoor = false
        #extra = false
        [[[Names]]]
            # Names for the extra sensors, such as:
            #extraTemp1 = Greenhouse

    [[Health]]
        # The hardware's battery, voltage and signal readings, with warnings for low batteries
        # and a weak signal.
        #enable = true
        # Percent of packets received below which the signal is weak.
        #weak_signal = 50
        [[[Batteries]]]
            # How each battery status is reported, if not 0 for OK and anything else for low:
            # level (0 to 5, low at 1 or less) or none (never warn).
            #batteryStatus1 = level
        [[[Names]]]
            # Names to use in warnings, such as:
            #batteryStatus1 = Pool sensor

    [[Archives]]
        # Longer history in files of their own beside this one, which apps fetch only when
        # they want them: the last week hourly, rewritten hourly, and the last year daily,
        # rewritten every 3 hours. Empty a name to leave that file out.
        #enable = false
        #week = history-week.json
        #year = history-year.json

    [[Forecast]]
        # If weewx-nws is installed, its NWS forecast and alerts are added to the file. Set
        # enable to false to leave them out.
        #enable = true

        # Most one-hour forecasts, and twelve-hour forecast periods, to include. 0 for none.
        #hours = 24
        #periods = 14

        # Whether to include the active NWS alerts.
        #alerts = true

[StdReport]
    [[CurrentJSON]]
        skin = CurrentJSON
        enable = true
"""


def loader():
    return CurrentJSONInstaller()


class CurrentJSONInstaller(ExtensionInstaller):
    def __init__(self):
        super().__init__(
            version=VERSION,
            name='current-json',
            description='Writes the station\'s current conditions as JSON, with a derived condition code.',
            author='David Shanske',
            author_email='david@shanske.com',
            config=configobj.ConfigObj(StringIO(CONFIG)),
            files=[
                ('bin/user', ['bin/user/current_json.py', 'bin/user/current_json_air.py', 'bin/user/current_json_conditions.py',
                              'bin/user/current_json_forecast.py', 'bin/user/current_json_history.py',
                              'bin/user/current_json_almanac.py', 'bin/user/current_json_records.py',
                              'bin/user/current_json_rain.py', 'bin/user/current_json_sensors.py',
                              'bin/user/current_json_archives.py']),
                ('skins/CurrentJSON', ['skins/CurrentJSON/skin.conf']),
            ],
        )
