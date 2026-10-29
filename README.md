# weewx-current-json

A [WeeWX](https://weewx.com) 5 extension that publishes your station's current conditions as JSON,
with a weather condition, such as "light rain" or "partly cloudy", and the cloud cover, derived from your sensors and
other sources.

Each archive interval it writes `current.json` next to your WeeWX web pages: the latest readings in
metric units, the station's details, and the condition, which WeeWX itself doesn't know. Anything
that can read JSON can use it, such as the WeeWX weather provider of the
[Simple Location](https://github.com/dshanske/simple-location) WordPress plugin, which shows your
station's weather on posts.

## Requirements

* WeeWX 5.0 or later, on Python 3.9 or later.
* Your WeeWX web pages reachable by whatever reads the file, as they are for most stations that
  publish a website.

## Installation

1. Download the latest release, `weewx-current-json.zip`.
2. Install it:

   ```
   weectl extension install weewx-current-json.zip
   ```

   On a pip install, activate WeeWX's virtual environment first.
3. Optionally edit the new `[CurrentJSON]` section of `weewx.conf` (see below).
4. Restart WeeWX.

After the next archive interval, the file is at `<HTML_ROOT>/current.json`, for example
`https://weather.example.com/current.json`. To use it with Simple Location, choose its WeeWX
weather provider and enter that URL.

## Configuration

Everything has a default; the installer writes the options into `weewx.conf` commented out.

```
[CurrentJSON]
    filename = current.json    # Written into the report's HTML_ROOT.
    station_id = weewx
    station_name = ""                  # Default: [Station] location.
    station_url = ""                   # Default: [Station] station_url.
    attribution_text = ""              # A credit shown with your weather, such as
    attribution_url = ""               # "Weather from Backyard Weather". Empty for none.
    user_agent = ""                    # Sent to aviationweather.gov; please include a contact.

    [[Conditions]]
        sources = sensors_precipitation, sensors_air, metar, sensors_clouds, sensors_wind, nws
        cloud_sources = sensors_clouds, metar, nws
        metar_station = ""             # ICAO ID of a nearby airport, such as KPHL.
        metar_max_age = 90             # Minutes.
        [[[Thresholds]]]
            ...                        # See below.

    [[AirQuality]]
        aqi_scale = us_epa             # Or none. See Air quality.

    [[Fields]]
        ...                            # See Fields.
```

The extension also adds a `CurrentJSON` report to `[StdReport]`, which you can disable there.

## Conditions

WeeWX measures the weather but doesn't describe it, so the extension derives a condition from up
to six sources. They're tried in the order of `sources`; the first that gives a condition is
used, and the file says which one did. Remove a source from the list to skip it.

| Source | From | Gives |
|---|---|---|
| `sensors_precipitation` | Your lightning sensor, rain gauge, snow sensor, temperature, humidity and dewpoint | Thunderstorm when lightning was detected this interval; snow when a snow sensor measures falling snow (rain and snow if it is also raining above 0 °C); otherwise snow at or below 0 °C, rain and snow below 2 °C, otherwise light, moderate or heavy rain by rain rate; fog or mist when the air is calm and saturated |
| `sensors_air` | Your PM2.5 sensor, and a gas sensor's VOC index if you have one | Smoke when PM2.5 and the VOC index are both raised; haze when PM2.5 is raised in dry air without the VOCs. Before the sunlight, so a smoky sky isn't reported as just cloudy. |
| `metar` | The latest METAR of the airport in `metar_station`, from [aviationweather.gov](https://aviationweather.gov) | The reported weather (rain, snow, thunderstorm, fog…) or sky cover. Used only if no more than `metar_max_age` minutes old. Fetched at most once each time the file is written, and only when a source before it, for the condition or the cloud cover, gave nothing. |
| `sensors_clouds` | Your solar radiation sensor, compared with WeeWX's clear-sky maximum (`maxSolarRad`); without one, your illuminance (lux) sensor, at about 120 lux per W/m² | Clear, few, scattered, broken or overcast, in daytime only |
| `sensors_wind` | Your anemometer | Windy |
| `nws` | The current hour of the National Weather Service hourly forecast, if [weewx-nws](https://github.com/chaunceygardiner/weewx-nws) is installed | The forecast condition. A forecast, not an observation, so it is last; it's most useful at night, when cloud cover can't be measured. |

If no source gives a condition, the file has none, rather than a guess.

### Cloud cover

The cloud cover, in percent, comes from three of the same sources, in the order of `cloud_sources`.
By default your own sunlight comes first, because it's measured at the station, then the airport,
then the forecast:

| Source | Cloud cover |
|---|---|
| `sensors_clouds` | From the same sunlight ratio and thresholds as the condition, by day only |
| `metar` | The airport's reported sky cover, or its most covered cloud layer. A sky hidden by fog counts as overcast. Works at night. |
| `nws` | The sky part of the forecast for the current hour (clear, few, scattered, broken or overcast) |

Each sky condition is given the middle of its range in eighths of the sky (oktas): clear 0%, few 19%,
scattered 44%, broken 75%, overcast 100%. Simple Location uses the same values for the cloud layers
of National Weather Service observations, so values from different sources line up. If no source
gives a cloud cover, the file has none.

A station with a solar or lux sensor gets the cloud cover from it by day and from the airport at
night; a station without one gets it from the airport all the time.

### Thresholds

In metric units, under `[[[Thresholds]]]`:

| Threshold | Default | Meaning |
|---|---|---|
| `rain_moderate` | 2.5 | Rain rate, mm/h, from which rain is moderate |
| `rain_heavy` | 7.6 | Rain rate, mm/h, from which rain is heavy |
| `snow_temperature` | 0.0 | °C at or below which precipitation is snow |
| `mix_temperature` | 2.0 | °C below which precipitation is rain and snow |
| `fog_humidity` | 97 | Humidity, %, for fog |
| `mist_humidity` | 93 | Humidity, %, for mist |
| `fog_spread` | 1.0 | Largest difference between temperature and dewpoint, °C, for fog or mist |
| `fog_wind` | 3.0 | Wind speed, m/s, below which fog or mist can form |
| `windy_speed` | 10.8 | Wind speed, m/s, from which it is windy (Beaufort 6) |
| `cloud_min_solar` | 100 | Least clear-sky radiation, W/m², for a cloud estimate, so the sun isn't near the horizon |
| `cloud_clear` | 0.75 | Ratio of measured to clear-sky radiation from which the sky is clear |
| `cloud_few` | 0.55 | … few clouds |
| `cloud_scattered` | 0.35 | … scattered clouds |
| `cloud_broken` | 0.15 | … broken clouds; below this, overcast |
| `smoke_pm2_5` | 35.5 | PM2.5, µg/m³, from which raised VOCs mean smoke (the US EPA's Unhealthy for Sensitive Groups) |
| `smoke_voc` | 150 | VOC index from which, with that PM2.5, it is smoke |
| `haze_pm2_5` | 35.5 | PM2.5, µg/m³, from which dry air without raised VOCs is haze |

Tipping-bucket rain gauges badly undercount snow, and a dirty or shaded radiation sensor reads as
cloud, so adjust these to your station.

A gas sensor's VOC index adapts to its recent baseline (12 hours in the AirGradient packages), so
smoke that lasts for days can stop counting as raised VOCs. A longer learning time on the sensor
helps.

## Air quality

The air quality index is calculated from your station's PM2.5, and written to the file with its
category and color. It isn't stored in WeeWX. The PM2.5 should already be corrected for the sensor:
the AirGradient ESPHome packages, for example, apply the EPA's correction for Plantower sensors
before sending it.

`aqi_scale` chooses the index:

* `us_epa` (the default): the US EPA's AQI for PM2.5, as the hourly NowCast that AirNow shows. It's
  calculated from the last 12 hourly means of the archive's `pm2_5`, weighted towards the most
  recent, with the breakpoints that took effect on 2024-05-06:

  | Category | AQI | PM2.5, µg/m³ | Color |
  |---|---|---|---|
  | Good | 0–50 | 0.0–9.0 | `#00e400` |
  | Moderate | 51–100 | 9.1–35.4 | `#ffff00` |
  | Unhealthy for Sensitive Groups | 101–150 | 35.5–55.4 | `#ff7e00` |
  | Unhealthy | 151–200 | 55.5–125.4 | `#ff0000` |
  | Very Unhealthy | 201–300 | 125.5–225.4 | `#8f3f97` |
  | Hazardous | 301–500, and above | 225.5–325.4, and above | `#7e0023` |

* `none`: no index.

If there isn't enough PM2.5, the file has no index, rather than a stale one. That happens when the
current record has no PM2.5, such as during a sensor outage, or when fewer than 2 of the last 3
hours have any.

## The file

The file uses version 1 of the current conditions format:

```json
{
  "format": "current-conditions",
  "version": 1,
  "time": 1761231600,
  "units": "metric",
  "station": {
    "id": "weewx",
    "name": "Backyard Weather",
    "latitude": 39.9524,
    "longitude": -75.1636,
    "altitude": 12,
    "url": "https://weather.example.com/",
    "attribution": { "text": "Weather from Backyard Weather", "url": "https://weather.example.com/" }
  },
  "observations": {
    "temperature": 21.5,
    "humidity": 61,
    "dewpoint": 13.7,
    "pressure": 1015.2,
    "windspeed": 3.58,
    "winddegree": 230,
    "windgust": 6.26,
    "rain": 1.27,
    "rainrate": 0.0,
    "radiation": 412,
    "uv": 3.1,
    "code": 802,
    "cloudiness": 44,
    "pm2_5": 8.2,
    "aqi": 46,
    "aqi_category": "Good",
    "aqi_color": "#00e400"
  },
  "derived": { "code": "sensors_clouds", "cloudiness": "sensors_clouds", "aqi": "us_epa" },
  "generator": "weewx-current-json 0.1.0; WeeWX 5.5.2"
}
```

* `time` is the archive record's time, in Unix seconds.
* `units` is always `metric`: °C, hPa, m/s, mm, mm/h, W/m², lux, µg/m³ and ppm, which is WeeWX's
  `METRICWX` system.
* `observations` holds only what your station measures, renamed from WeeWX:

  | WeeWX | File | WeeWX | File |
  |---|---|---|---|
  | `outTemp` | `temperature` | `rainRate` | `rainrate` |
  | `outHumidity` | `humidity` | rain in the last hour | `rain` |
  | `snowRate` | `snowrate` | snow in the last hour | `snow` |
  | `snowDepth` | `snowdepth` | | |
  | `dewpoint` | `dewpoint` | `radiation` | `radiation` |
  | `heatindex` | `heatindex` | `illuminance` | `illuminance` |
  | `windchill` | `windchill` | `UV` | `uv` |
  | `barometer` | `pressure` | `pm1_0`, `pm2_5`, `pm10_0` | the same |
  | `windSpeed` | `windspeed` | `co`, `co2`, `nh3`, `o3`, `pb`, `so2` | the same |
  | `windDir` | `winddegree` | `voc_index` | `voc_index` |
  | `windGust` | `windgust` | `nox_index` | `nox_index` |

  To read a key from a field with another name, see [Fields](#fields).
* `cloudiness` is the cloud cover in percent, and `derived.cloudiness` names the source it came from.
* `aqi` is the air quality index, `aqi_category` its category's name in English, and `aqi_color`
  the category's color as `#rrggbb`; `derived.aqi` names the scale. See [Air quality](#air-quality).
* `voc_index` and `nox_index` are the VOC and NOx indices of a Sensirion SGP40 or SGP41 gas sensor,
  from 1 to 500 and without a unit: for VOC, 100 is the sensor's recent average; for NOx, 1 is the
  baseline. WeeWX has no standard fields for them, so add `voc_index` and `nox_index` columns, and
  store the indices there, not a concentration.
* `code` is an OpenWeatherMap-style condition code (800 clear, 801–804 increasing cloud, 500–504
  rain, 600–602 snow, 701 mist, 741 fog, 200–233 thunderstorm, 400 windy), and `derived.code` names
  the source it came from.

## Fields

Each key of the file is read from the WeeWX field in the table above. If your station stores a
reading under another name, map it in `[[Fields]]`, as `key = WeeWX field`:

```
[CurrentJSON]
    [[Fields]]
        voc_index = voc        # Read voc_index from the voc field.
        nox_index = nox
        uv = none              # Leave uv out of the file.
```

Only the file's own keys can be mapped. The field must be in the archive record, but it doesn't
have to be stored in the database. A field that WeeWX doesn't know the unit of is written as it is,
so it must already be in the file's units.

To rename columns instead, so the defaults apply, stop WeeWX, back up the database, and run, for
example:

```
weectl database rename-column voc voc_index
weectl database rename-column nox nox_index
```

Then change whatever writes those fields, such as an MQTT Subscribe mapping, to the new names, and
start WeeWX again. If you added the columns through a custom schema rather than `weectl database
add-column`, rename them in the schema too.

## Development

The tests use Python's `unittest` and need WeeWX importable, either from a WeeWX 5 environment or
by pointing `WEEWX_LIB` at an unpacked WeeWX wheel:

```
WEEWX_LIB=/path/to/weewx/lib python3 -m unittest discover -s . -p 'test_*.py'
```

To build the release zip:

```
git archive --format=zip --prefix=weewx-current-json/ -o weewx-current-json.zip HEAD
```

## License

GPL v3. See [LICENSE](LICENSE).
