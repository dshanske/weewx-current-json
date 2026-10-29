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
