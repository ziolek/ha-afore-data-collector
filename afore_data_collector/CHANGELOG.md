# Changelog

## 1.0.0

- Initial release of **Afore data collector**.
- Local TCP V5 listener (`Server B`) with handshake (`0x4110`), live telemetry (`0x4210`), heartbeat (`0x4710`), and cached historical frame (`0x81`) filtering.
- Automatic Home Assistant MQTT Discovery for inverter (21 entities) and LSW-3 datalogger (5 diagnostic entities).
- Automatic Supervisor Mosquitto broker credential lookup with optional manual override.
- Safe night/offline handling preserving cumulative and daily energy counters.
