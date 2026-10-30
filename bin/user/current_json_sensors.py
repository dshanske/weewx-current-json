#
#    Copyright (c) 2026 David Shanske
#
#    See the file LICENSE for your full rights.
#
"""Indoor and extra sensors, and the station's health, for the file's optional sections.

Indoor readings and extra sensors say something about the home and garden, so they're only
written when [CurrentJSON] [[Sensors]] turns them on:

    "indoor": {"temperature": 21.2, "humidity": 45, "dewpoint": 8.9},
    "sensors": [
      {"field": "extraTemp1", "name": "Greenhouse", "kind": "temperature", "value": 24.1},
      {"field": "soilMoist1", "name": "Soil moisture 1", "kind": "soil_moisture", "value": 18}
    ]

Kinds and units: temperature, soil_temperature and leaf_temperature in °C, humidity in percent,
soil_moisture in centibars and leaf_wetness from 0 (dry) to 15 (wet).

"health" is on by default: the hardware's battery and signal readings, as the driver gives them,
and warnings for the ones that need attention:

    "health": {
      "batteries": {"windBatteryStatus": 1, "outTempBatteryStatus": 0},
      "voltages": {"consBatteryVoltage": 4.62},
      "signal": {"rxCheckPercent": 97},
      "warnings": [{"field": "windBatteryStatus", "message": "Wind sensor battery low"}]
    }

Drivers report battery status differently. By default a status other than 0 is low, which is how
most drivers report it; [[Health]] [[[Batteries]]] can say a field is a "level" from 0 to 5, low
at 1 or less, or "none" to never warn about it.
"""

import logging

import weewx.units
from weeutil.weeutil import to_bool, to_float

log = logging.getLogger(__name__)

INDOOR = {'inTemp': 'temperature', 'inHumidity': 'humidity', 'inDewpoint': 'dewpoint'}

# Extra sensor fields of WeeWX's extended schema: (field, kind, default name).
EXTRA = (
    [('extraTemp%d' % n, 'temperature', 'Temperature %d' % n) for n in range(1, 9)]
    + [('extraHumid%d' % n, 'humidity', 'Humidity %d' % n) for n in range(1, 9)]
    + [('soilTemp%d' % n, 'soil_temperature', 'Soil temperature %d' % n) for n in range(1, 5)]
    + [('soilMoist%d' % n, 'soil_moisture', 'Soil moisture %d' % n) for n in range(1, 5)]
    + [('leafTemp%d' % n, 'leaf_temperature', 'Leaf temperature %d' % n) for n in range(1, 3)]
    + [('leafWet%d' % n, 'leaf_wetness', 'Leaf wetness %d' % n) for n in range(1, 3)]
)
PRECISION = {'temperature': 1, 'soil_temperature': 1, 'leaf_temperature': 1, 'humidity': 0,
             'soil_moisture': 0, 'leaf_wetness': 0, 'dewpoint': 1}

BATTERIES = dict(
    [('outTempBatteryStatus', 'Outdoor sensor'), ('inTempBatteryStatus', 'Indoor sensor'),
     ('windBatteryStatus', 'Wind sensor'), ('rainBatteryStatus', 'Rain gauge'),
     ('txBatteryStatus', 'Transmitter'), ('uvBatteryStatus', 'UV sensor'),
     ('hailBatteryStatus', 'Hail sensor'), ('snowBatteryStatus', 'Snow sensor')]
    + [('batteryStatus%d' % n, 'Sensor %d' % n) for n in range(1, 9)]
)
VOLTAGES = ('consBatteryVoltage', 'supplyVoltage', 'referenceVoltage', 'heatingVoltage')
SIGNALS = ('rxCheckPercent',) + tuple('signal%d' % n for n in range(1, 9))
BATTERY_KINDS = ('flag', 'level', 'none')
DEFAULT_WEAK_SIGNAL = 50


def sensor_options(sensors_dict):
    """Returns (indoor, extra, names) from [CurrentJSON] [[Sensors]]; both are off by default."""
    sensors_dict = sensors_dict or {}
    names = {str(field): str(name) for field, name in (sensors_dict.get('Names') or {}).items() if name}
    return to_bool(sensors_dict.get('indoor', False)), to_bool(sensors_dict.get('extra', False)), names


def indoor(record):
    """Returns the indoor section from an archive record, in the file's units, or an empty dict."""
    metric = weewx.units.to_METRICWX(record)
    section = {}
    for field, key in INDOOR.items():
        value = _number(metric.get(field))
        if value is not None:
            section[key] = _round(value, PRECISION[key])
    return section


def extra(record, names=None):
    """Returns the sensors section: each extra sensor in the record, in the file's units."""
    names = names or {}
    metric = weewx.units.to_METRICWX(record)
    sensors = []
    for field, kind, default_name in EXTRA:
        value = _number(metric.get(field))
        if value is not None:
            sensors.append({'field': field, 'name': names.get(field, default_name), 'kind': kind,
                            'value': _round(value, PRECISION[kind])})
    return sensors


def health(record, health_dict=None):
    """Returns the health section from an archive record, or an empty dict if it has none of it."""
    health_dict = health_dict or {}
    if not to_bool(health_dict.get('enable', True)):
        return {}
    kinds = {str(k): str(v).lower() for k, v in (health_dict.get('Batteries') or {}).items()}
    names = dict(BATTERIES)
    names.update({str(k): str(v) for k, v in (health_dict.get('Names') or {}).items()})
    weak = to_float(health_dict.get('weak_signal', DEFAULT_WEAK_SIGNAL))

    batteries = {f: _number(record.get(f)) for f in BATTERIES if _number(record.get(f)) is not None}
    voltages = {f: round(_number(record.get(f)), 2) for f in VOLTAGES if _number(record.get(f)) is not None}
    signal = {f: _round(_number(record.get(f)), 0) for f in SIGNALS if _number(record.get(f)) is not None}
    batteries = {f: _round(v, 0) for f, v in batteries.items()}

    warnings = []
    for field, value in batteries.items():
        kind = kinds.get(field, 'flag')
        if kind not in BATTERY_KINDS:
            log.error("Ignoring [[Health]] [[[Batteries]]] %s = %s: not one of %s", field, kind, ', '.join(BATTERY_KINDS))
            kind = 'flag'
        low = (kind == 'flag' and value != 0) or (kind == 'level' and value <= 1)
        if low:
            warnings.append({'field': field, 'message': '%s battery low' % names.get(field, field)})
    rx = signal.get('rxCheckPercent')
    if rx is not None and rx < weak:
        warnings.append({'field': 'rxCheckPercent', 'message': 'Weak signal from the sensors (%d%% received)' % rx})

    section = {}
    for key, values in (('batteries', batteries), ('voltages', voltages), ('signal', signal)):
        if values:
            section[key] = values
    if warnings:
        section['warnings'] = warnings
    return section


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _round(value, places):
    return int(round(value)) if places == 0 else round(value, places)
