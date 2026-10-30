# weewx-current-json

A [WeeWX](https://weewx.com) 5 extension that publishes your station's current conditions as JSON,
with a weather condition, such as "light rain" or "partly cloudy", and the cloud cover, derived from your sensors and
other sources. With [weewx-nws](https://github.com/chaunceygardiner/weewx-nws) installed, it adds the National
Weather Service forecast and alerts.

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
    timezone = ""                      # Default: the computer's, such as America/New_York.
    webcam_url = ""                    # An image from the station's webcam. Empty for none.

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

    [[Today]]
        enable = true                  # The day's highs, lows and totals so far.
        yesterday = true               # And yesterday's.

    [[Records]]
        enable = true
        periods = week, month, year, rain_year, all_time

    [[Rain]]
        enable = true
        storm_gap = 24                 # Hours without rain that end a storm.

    [[Trend]]
        hours = 3                      # 0 for no trend.

    [[History]]
        hours = 24                     # 0 for no history.
        interval = 30                  # Minutes summarized in each value.

    [[Almanac]]
        enable = true                  # Sun and moon times.

    [[Sensors]]
        indoor = false                 # Indoor temperature and humidity.
        extra = false                  # Extra, soil and leaf sensors.
        [[[Names]]]
            ...                        # Such as extraTemp1 = Greenhouse.

    [[Health]]
        enable = true                  # Batteries, voltages and signal, with warnings.
        weak_signal = 50               # Percent received below which the signal is weak.
        [[[Batteries]]]
            ...                        # See Health.
        [[[Names]]]
            ...

    [[Archives]]
        enable = false                 # Longer history in files of their own.
        week = history-week.json
        year = history-year.json

    [[Forecast]]
        enable = true                  # Only does anything with weewx-nws installed.
        hours = 24                     # Most one-hour forecasts.
        periods = 14                   # Most twelve-hour forecast periods.
        alerts = true
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

## Today and trend

The file has the day's extremes and totals so far in `today`: the high and low temperature and when
they were, the highest gust and when it was, and the rain and snow since midnight. The day is the
station's, in WeeWX's local time. Set `enable = false` in `[[Today]]` to leave it out.

`trend` is how much the pressure and temperature have changed over the last `hours` (3 by
default), from the archive record nearest that time. It's left out when there's no such record,
such as in the first hours after a station starts, and with `hours = 0` in `[[Trend]]`.

## Yesterday and records

`yesterday` has the same highs, lows and totals as `today`, for the whole of yesterday. Set
`yesterday = false` in `[[Today]]` to leave it out.

`records` has them for longer periods, each from its start to the end of today: `week`, `month`,
`year`, `rain_year` and `all_time`. The week starts on `[Station] week_start`, and the rain year in
`[Station] rain_year_start`; the rain year is left out when it starts in January, being the same as
the year. All of it comes from WeeWX's daily summaries, so even `all_time` takes only a few queries.
Choose the periods with `periods` in `[[Records]]`, or set `enable = false`.

`today`, `yesterday` and each period but `all_time` also have heating, cooling and growing degree
days, from each day's mean temperature and the bases in `[StdReport] [[Defaults]] [[[Units]]]
[[[[DegreeDays]]]]`, as WeeWX's reports use (65 °F, 65 °F and 50 °F by default).

## Rain

`rain` has the rain in the last 24 hours, the time of the last archive record with rain, and the
current storm: the rain since it started raining without a dry spell longer than `storm_gap` hours
(24 by default). The storm is left out when it hasn't rained within `storm_gap` hours.

## Sensors and health

Indoor readings and extra sensors say something about your home and garden, so they're only in the
file when you turn them on in `[[Sensors]]`: `indoor = true` adds `indoor`, from `inTemp`,
`inHumidity` and `inDewpoint`, and `extra = true` adds `sensors`, from WeeWX's `extraTemp1`–`8`,
`extraHumid1`–`8`, `soilTemp1`–`4`, `soilMoist1`–`4`, `leafTemp1`–`2` and `leafWet1`–`2`. Name
them in `[[[Names]]]`, such as `extraTemp1 = Greenhouse`; otherwise they're called "Temperature 1"
and so on.

`health` has what the hardware says about itself: battery status, voltages, and signal (such as
`rxCheckPercent`, the share of packets received), with a warning for each low battery and for a
weak signal. Drivers report battery status differently: by default 0 is OK and anything else is
low, as most drivers report it. In `[[[Batteries]]]`, set a field to `level` if it's a level from 0
to 5 (low at 1 or less), or `none` to never warn about it, and name it for the warnings in
`[[[Names]]]`. Set `enable = false` in `[[Health]]` to leave it out.

## Archives

The file only holds the last day, since it's fetched often. With `enable = true` in
`[[Archives]]`, two more files are written beside it, and the file names them in `archives`, so
apps can fetch them when they want a longer chart:

* `history-week.json`: the last 7 days in hourly intervals, in the same shape as `history`,
  rewritten at most once an hour.
* `history-year.json`: the last 365 days, one value per day from the daily summaries, rewritten at
  most every 3 hours.

Set `week` or `year` to an empty name to leave that file out. They're described under
[The archive files](#the-archive-files).

## History

`history` has each reading over the last `hours` (24 by default), summarized over intervals of
`interval` minutes (30), so that apps can chart the day: the total rain and snow of each interval,
the highest gust, rain rate and snow rate, and the mean of everything else. It's read from the
archive in one query. Set `hours = 0` in `[[History]]` to leave it out.

## Almanac

`almanac` has the day's sunrise and sunset and the moon's phase, from WeeWX's almanac, at the
station's location. If [PyEphem](https://rhodesmill.org/pyephem/) is installed with WeeWX
(`pip install ephem` in WeeWX's environment), it also has civil dawn and dusk, moonrise and
moonset, and the next full and new moon. Set `enable = false` in `[[Almanac]]` to leave it out. It
needs the station's latitude and longitude in `[Station]`.

## Webcam

If the station has a webcam that saves an image to a web address, set `webcam_url` to it, and the
file gives it as `station.webcam`, for apps to show and reload. It can be relative to where
`current.json` is published, such as `webcam.jpg`. The extension only passes the address on; it
doesn't fetch or check the image.

## Time zone

The station's time zone is in `station.timezone`, as an IANA name such as `America/New_York`, so
that whatever reads the file can show times in the station's time, wherever it is. WeeWX works in
the computer's local time, so the extension finds the computer's zone, from `TZ`, `/etc/timezone`
or `/etc/localtime`. If it can't, the name is left out; set `timezone` in `[CurrentJSON]` to give
it, which should be the computer's zone. `station.utc_offset` is the offset from UTC, in seconds, at
the time of the reading, for readers without a time zone database.

## Forecast

If [weewx-nws](https://github.com/chaunceygardiner/weewx-nws) is installed, the file also has a
`forecast` section with its National Weather Service forecast and alerts. Nothing else in the file
changes, and without weewx-nws, or with `enable = false` in `[[Forecast]]`, the section is left out.

It's read from weewx-nws's database the way weewx-nws reads it for its own reports: the most
recently generated forecast, without the hours and periods that have already ended, and the alerts
from its last poll that haven't ended. An alert ends at its end time, or when it expires if NWS gave
no end, and, as in weewx-nws, it's kept for up to a day after it expires, until NWS reissues it.

`hours` and `periods` limit how many one-hour forecasts and twelve-hour periods are included, and
`alerts = false` leaves out the alerts. Set `hours` or `periods` to 0 to leave out that part.

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
    "attribution": { "text": "Weather from Backyard Weather", "url": "https://weather.example.com/" },
    "timezone": "America/New_York",
    "utc_offset": -14400,
    "webcam": "https://weather.example.com/webcam.jpg"
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
  "today": {
    "temperature_max": 23.1,
    "temperature_max_time": 1761229800,
    "temperature_min": 11.4,
    "temperature_min_time": 1761206400,
    "windgust_max": 8.94,
    "windgust_max_time": 1761224100,
    "rain": 3.05
  },
  "yesterday": {
    "temperature_max": 19.4,
    "temperature_max_time": 1761148200,
    "temperature_min": 9.8,
    "temperature_min_time": 1761121800,
    "windgust_max": 7.6,
    "windgust_max_time": 1761139800,
    "rain": 0.0,
    "heatdeg": 3.9,
    "cooldeg": 0.0,
    "growdeg": 4.4
  },
  "records": {
    "week": { "temperature_max": 23.1, "temperature_max_time": 1761229800, "rain": 12.7, "...": "..." },
    "month": { "...": "..." },
    "year": { "...": "..." },
    "all_time": { "...": "..." }
  },
  "trend": { "hours": 3, "pressure": -1.2, "temperature": 4.6 },
  "rain": { "last_24h": 3.05, "last": 1761228000, "storm": 3.05, "storm_start": 1761213600 },
  "almanac": {
    "sunrise": 1761218383,
    "sunset": 1761257375,
    "civil_dawn": 1761216697,
    "civil_dusk": 1761259060,
    "moonrise": 1761226268,
    "moonset": 1761260206,
    "moon_phase": 1,
    "moon_fullness": 4,
    "next_full_moon": 1762348755,
    "next_new_moon": 1763621233
  },
  "history": {
    "start": 1761145200,
    "interval": 1800,
    "temperature": [12.1, 11.8, 11.6, "...", 21.3, 21.5],
    "rain": [0.0, 0.0, 0.0, "...", 0.25, 1.02]
  },
  "health": {
    "batteries": { "outTempBatteryStatus": 0, "windBatteryStatus": 1 },
    "voltages": { "consBatteryVoltage": 4.62 },
    "signal": { "rxCheckPercent": 97 },
    "warnings": [{ "field": "windBatteryStatus", "message": "Wind sensor battery low" }]
  },
  "archives": { "week": "history-week.json", "year": "history-year.json" },
  "generator": "weewx-current-json 0.3.0; WeeWX 5.5.2"
}
```

With `[[Sensors]]` turned on, it also has:

```json
"indoor": { "temperature": 21.2, "humidity": 45, "dewpoint": 8.9 },
"sensors": [
  { "field": "extraTemp1", "name": "Greenhouse", "kind": "temperature", "value": 24.1 },
  { "field": "soilMoist1", "name": "Soil moisture 1", "kind": "soil_moisture", "value": 18 }
]
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
  | `appTemp` | `apptemp` | `cloudbase` | `cloudbase` |

  To read a key from a field with another name, see [Fields](#fields).
* `cloudiness` is the cloud cover in percent, and `derived.cloudiness` names the source it came from.
* `aqi` is the air quality index, `aqi_category` its category's name in English, and `aqi_color`
  the category's color as `#rrggbb`; `derived.aqi` names the scale. See [Air quality](#air-quality).
* `voc_index` and `nox_index` are the VOC and NOx indices of a Sensirion SGP40 or SGP41 gas sensor,
  from 1 to 500 and without a unit: for VOC, 100 is the sensor's recent average; for NOx, 1 is the
  baseline. WeeWX has no standard fields for them, so add `voc_index` and `nox_index` columns, and
  store the indices there, not a concentration.
* `station.timezone` and `station.utc_offset` are described in [Time zone](#time-zone).
* `today` holds the day's extremes so far, in the units of the observations they're of, with the
  Unix time of each, and `rain` and `snow`, the totals since midnight in mm. Anything the station
  doesn't measure is left out.
* `today` also has the day's evapotranspiration, `et`, in mm; wind run, `windrun`, in km;
  lightning strikes, `lightning_strikes`; and heating, cooling and growing degree days, `heatdeg`,
  `cooldeg` and `growdeg`, in °C-days. Totals of sensors the station doesn't have are left out.
* `yesterday` and each period of `records` have the same keys as `today`; see
  [Yesterday and records](#yesterday-and-records).
* `trend` gives the change of `pressure` and `temperature`, in hPa and °C, over the last `hours`.
* `rain` times are Unix seconds and amounts mm; see [Rain](#rain).
* `apptemp` is WeeWX's apparent temperature, in °C, and `cloudbase` its estimate of the height of
  the cloud base, in meters. `lightning_strikes` is the number of strikes in the last hour, and
  `lightning_distance` the distance of the latest, in km, when there were any.
* `indoor` is in °C and percent. In `sensors`, temperatures are °C, humidity percent,
  `soil_moisture` centibars and `leaf_wetness` from 0 (dry) to 15 (wet).
* `health` gives the readings as the driver reports them; see [Sensors and health](#sensors-and-health).
* `archives` names the archive files, relative to this one.
* `almanac` times are Unix seconds. `moon_phase` is 0 to 7: new, waxing crescent, first quarter,
  waxing gibbous, full, waning gibbous, last quarter and waning crescent. `moon_fullness` is the
  percentage of the moon that's lit. A sunrise or sunset that doesn't happen that day, near the
  poles, is left out, and so is anything that needs PyEphem without it.
* `history` has a list for each reading, one value per interval, oldest first, in the units of the
  observations, with `null` for an interval without data. `start` is when the first interval
  begins, in Unix seconds, and `interval` the length of each in seconds; the last is the interval
  `time` is in, so it may not have ended. The wind direction isn't included.
* `station.webcam` is the address of the station's webcam image, as `webcam_url` gives it.
* `forecast`, only with weewx-nws, is described [below](#the-forecast-section).
* `code` is an OpenWeatherMap-style condition code (800 clear, 801–804 increasing cloud, 500–504
  rain, 600–602 snow, 701 mist, 741 fog, 200–233 thunderstorm, 400 windy), and `derived.code` names
  the source it came from. When it's `metar`, or `derived.cloudiness` is, `derived.metar_station`
  is the airport's ICAO ID, such as `KPHL`.

### The forecast section

```json
"forecast": {
  "source": "nws",
  "generated": 1761228000,
  "hourly": [
    { "time": 1761231600, "end": 1761235200, "daytime": true, "temperature": 20.0, "dewpoint": 10.0,
      "humidity": 53, "windspeed": 4.02, "winddegree": 225, "pop": 20, "code": 521,
      "summary": "Chance Rain Showers" }
  ],
  "periods": [
    { "name": "Tonight", "time": 1761231600, "end": 1761274800, "daytime": false, "temperature": 12.8,
      "windspeed": 2.24, "windspeed_max": 4.47, "winddegree": 180, "pop": 60, "code": 211,
      "summary": "Chance Showers And Thunderstorms", "details": "Showers likely after 2am. ..." }
  ],
  "alerts": [
    { "id": "urn:oid:2.49.0.1.840.0....", "event": "Heat Advisory", "headline": "Heat Advisory until 9 PM",
      "description": "...", "instruction": "...", "severity": "Moderate", "urgency": "Expected",
      "certainty": "Likely", "sender": "NWS Philadelphia PA", "area": "Philadelphia",
      "issued": 1761228000, "onset": 1761228000, "ends": 1761264000, "expires": 1761253200 }
  ]
}
```

* The units are the file's: °C, m/s and percent.
* `generated` is when NWS generated the newer of the two forecasts, in Unix seconds.
* `hourly` holds the one-hour forecasts and `periods` the twelve-hour ones, soonest first. `time`
  and `end` are when each starts and ends. A period's `temperature` is its high by day and low at
  night. `pop` is the chance of precipitation. `windspeed_max` is the upper end when NWS gives the
  wind as a range, such as "5 to 10 mph". `code` is a condition code from the NWS icon, as for the
  `nws` conditions source. `summary` is NWS's short forecast, and a period's `details` its
  detailed forecast.
* `alerts` holds the active alerts, the most recently issued first, with NWS's event name, headline,
  description, instruction, severity, urgency, certainty, sender and area. `onset` and `ends` are
  when NWS expects the event to start and end, and `issued` and `expires` when the alert takes effect and
  expires. NWS doesn't always give an onset or end.
* Anything weewx-nws doesn't have is left out: `hourly`, `periods` or `alerts` when there are
  none, and any key of an hour, period or alert.

### The archive files

```json
{
  "format": "current-conditions-history",
  "version": 1,
  "time": 1761231600,
  "units": "metric",
  "station": { "id": "weewx" },
  "history": { "start": 1760630400, "interval": 3600, "temperature": [12.1, "..."], "rain": [0.0, "..."] }
}
```

`history-week.json` has a `history` like the one in `current.json`, with hourly intervals over 7
days. `history-year.json` has a `daily` section instead:

```json
"daily": {
  "time": [1729656000, 1729742400, "..."],
  "temperature": [14.2, 15.1, "..."],
  "temperature_min": [8.3, 9.0, "..."],
  "temperature_max": [19.9, 21.4, "..."],
  "rain": [0.0, 3.3, "..."],
  "windgust": [8.9, 12.1, "..."]
}
```

`time` is the start of each day, in Unix seconds, since days aren't all the same length. Each list
has one value per day, oldest first, with `null` for a day without data. A total, such as rain, is
the day's sum, and the gust and rates its highest. Everything else has its mean under its own key,
and its lowest and highest under `_min` and `_max`.

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
