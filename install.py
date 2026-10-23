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

VERSION = '0.1.0'

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

    [[Conditions]]
        # WeeWX doesn't know the conditions, such as "rain" or "partly cloudy", so they are
        # derived from these sources, tried in order; the first that gives one is used.
        # Remove a source to skip it.
        #   sensors_precipitation  lightning, rain, snow and fog from this station's sensors
        #   metar                  a nearby airport's METAR (set metar_station)
        #   sensors_clouds         daytime cloud cover, from solar radiation
        #   sensors_wind           windy, from wind speed
        #   nws                    the NWS hourly forecast, if weewx-nws is installed
        #sources = sensors_precipitation, metar, sensors_clouds, sensors_wind, nws

        # ICAO ID of a nearby airport, such as KPHL, for the metar source. Empty skips it.
        #metar_station = ""

        # Oldest METAR to use, in minutes.
        #metar_max_age = 90

        [[[Thresholds]]]
            # Overrides for the thresholds of the sensor sources, in metric units. See the README.
            #rain_moderate = 2.5
            #rain_heavy = 7.6
            #cloud_clear = 0.75

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
                ('bin/user', ['bin/user/current_json.py', 'bin/user/current_json_conditions.py']),
                ('skins/CurrentJSON', ['skins/CurrentJSON/skin.conf']),
            ],
        )
