# Changes

## 0.1.0 (unreleased)

* First version: writes the current conditions format, version 1, each archive interval,
  with conditions derived from the station's sensors, a nearby airport's METAR, or weewx-nws's
  forecast.
* Includes the VOC and NOx indices of a Sensirion SGP40/SGP41 gas sensor, from WeeWX's `voc` and
  `nox`, as `voc_index` and `nox_index` (#3).
