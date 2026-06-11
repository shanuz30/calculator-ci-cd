# calculator-ci-cd
Using Calculator and pytest
Oxocard Program from source

## Files
- `mqtt_sensor_monitor.py` — Oxocard MQTT sensor script (CO2/NOx/temperature → HiveMQ). Formerly misnamed `updated from the source.npy`.

## Security note
MQTT broker credentials were previously committed in this repository and remain
visible in git history. They must be treated as compromised: rotate the password
in the HiveMQ Cloud console. Real credentials are never committed — the script
contains placeholders to be filled in locally on the device.
