# Changes

## 0.1.0 (unreleased)

* First version: writes the current conditions format, version 1, each archive interval,
  with conditions derived from the station's sensors, a nearby airport's METAR, or weewx-nws's
  forecast.
* Adds the cloud cover, `cloudiness` in percent, from the station's sunlight by day, a nearby
  airport's METAR, or weewx-nws's forecast, in the order of `cloud_sources` (#1).
* The sunlight estimate uses an illuminance (lux) sensor when there's no solar radiation sensor.
* The METAR and forecast are read at most once each time the file is written.
* Includes the VOC and NOx indices of a Sensirion SGP40/SGP41 gas sensor, from WeeWX fields
  `voc_index` and `nox_index` (#3).
* Adds `[[Fields]]`, to read any of the file's keys from a WeeWX field with another name, or to
  leave a key out.
* Adds the air quality index, `aqi`, with `aqi_category` and `aqi_color`: the US EPA's hourly
  NowCast for PM2.5 with the 2024 breakpoints, or none, set by `aqi_scale` in `[[AirQuality]]`. No
  index without enough PM2.5, such as during a sensor outage (#5).
* Adds the `sensors_air` conditions source: smoke from raised PM2.5 and VOC index, haze from raised
  PM2.5 in dry air (#5).
* The installer's settings include `cloud_sources`, `[[AirQuality]]` and `[[Fields]]`.
* Includes a snow sensor's readings: `snow`, the snowfall in the last hour, summed like rain; `snowdepth`,
  from `snowDepth`; and `snowrate`, from `snowRate`. Falling snow it measures is the snow condition (#7).
* Adds the National Weather Service forecast and alerts from weewx-nws, if it's installed, as an optional
  `forecast` section: the one-hour forecasts, the twelve-hour periods and the active alerts, set by
  `[[Forecast]]`. The rest of the file doesn't change.
* Adds `today`, the day's high and low temperature, highest gust, and rain and snow so far, and
  `trend`, the change of pressure and temperature over the last 3 hours, set by `[[Today]]` and
  `[[Trend]]`.
* Adds the station's time zone, `station.timezone`, and its offset from UTC, `station.utc_offset`.
