# weewx-current-json

A [WeeWX](https://weewx.com) 5 extension that publishes your station's current conditions as JSON,
with a weather condition, such as "light rain" or "partly cloudy", derived from your sensors and
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
        sources = sensors_precipitation, metar, sensors_clouds, sensors_wind, nws
        metar_station = ""             # ICAO ID of a nearby airport, such as KPHL.
        metar_max_age = 90             # Minutes.
        [[[Thresholds]]]
            ...                        # See below.
```

The extension also adds a `CurrentJSON` report to `[StdReport]`, which you can disable there.

## Conditions

WeeWX measures the weather but doesn't describe it, so the extension derives a condition from up
to five sources. They're tried in the order of `sources`; the first that gives a condition is
used, and the file says which one did. Remove a source from the list to skip it.

| Source | From | Gives |
|---|---|---|
| `sensors_precipitation` | Your lightning sensor, rain gauge, temperature, humidity and dewpoint | Thunderstorm when lightning was detected this interval; snow at or below 0 °C, rain and snow below 2 °C, otherwise light, moderate or heavy rain by rain rate; fog or mist when the air is calm and saturated |
| `metar` | The latest METAR of the airport in `metar_station`, from [aviationweather.gov](https://aviationweather.gov) | The reported weather (rain, snow, thunderstorm, fog…) or sky cover. Used only if no more than `metar_max_age` minutes old. Fetched only when the sources before it gave nothing. |
| `sensors_clouds` | Your solar radiation sensor, compared with WeeWX's clear-sky maximum (`maxSolarRad`) | Clear, few, scattered, broken or overcast, in daytime only |
| `sensors_wind` | Your anemometer | Windy |
| `nws` | The current hour of the National Weather Service hourly forecast, if [weewx-nws](https://github.com/chaunceygardiner/weewx-nws) is installed | The forecast condition. A forecast, not an observation, so it is last; it's most useful at night, when cloud cover can't be measured. |

If no source gives a condition, the file has none, rather than a guess.

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

Tipping-bucket rain gauges badly undercount snow, and a dirty or shaded radiation sensor reads as
cloud, so adjust these to your station.

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
    "code": 802
  },
  "derived": { "code": "sensors_clouds" },
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
  | `dewpoint` | `dewpoint` | `radiation` | `radiation` |
  | `heatindex` | `heatindex` | `illuminance` | `illuminance` |
  | `windchill` | `windchill` | `UV` | `uv` |
  | `barometer` | `pressure` | `pm1_0`, `pm2_5`, `pm10_0` | the same |
  | `windSpeed` | `windspeed` | `co`, `co2`, `nh3`, `o3`, `pb`, `so2` | the same |
  | `windDir` | `winddegree` | `voc` | `voc_index` |
  | `windGust` | `windgust` | `nox` | `nox_index` |

* `voc_index` and `nox_index` are the VOC and NOx indices of a Sensirion SGP40 or SGP41 gas sensor,
  from 1 to 500 and without a unit: for VOC, 100 is the sensor's recent average; for NOx, 1 is the
  baseline. Store the indices in WeeWX's `voc` and `nox`, not a concentration.
* `code` is an OpenWeatherMap-style condition code (800 clear, 801–804 increasing cloud, 500–504
  rain, 600–602 snow, 701 mist, 741 fog, 200–233 thunderstorm, 400 windy), and `derived.code` names
  the source it came from.

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
