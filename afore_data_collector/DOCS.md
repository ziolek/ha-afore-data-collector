# Afore data collector

Local Home Assistant add-on receiving pushed binary V5 telemetry frames (**Remote Server B**) from an **LSW-3** datalogger attached to an **Afore** PV inverter and exposing all metrics via **MQTT Auto-Discovery**.

## Tested Hardware

- **Inverter:** Afore **BNT010KTL** (3-phase, 2 MPPT, T4 generation, firmware `12.41 / 1.18`)
- **Datalogger:** **LSW-3** Wi-Fi stick logger (firmware `LSW3_15_1E03_1.33`)

## Setup

1. Install and start the add-on. If you run the official **Mosquitto broker** add-on, leave `mqtt_host`, `mqtt_port`, `mqtt_username`, and `mqtt_password` unset — credentials are automatically retrieved from Home Assistant Supervisor.
2. Open the LSW-3 hidden settings page:
   ```text
   http://<LOGGER_IP>/config_hide.html
   ```
3. Under **Secondary Server Setting (Server B)** set:
   - **IP address:** `<HOME_ASSISTANT_IP>` *(use the HA IP on the same VLAN/subnet as the logger if Home Assistant is multi-homed)*
   - **Domain name:** *(leave empty)*
   - **Port:** `10000`
   - **Connection:** `TCP`
4. Click **Save** under Server B and then **Restart** the logger.

Once the inverter is operating (during daylight), the logger connects within ~30–60 seconds and both **Afore Inverter** and **Afore LSW-3** devices appear automatically under **Settings → Devices & Services → MQTT**.

## Configuration Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `listen_port` | `10000` | TCP port the add-on listens on for LSW-3 Server B connections |
| `mqtt_topic_prefix` | `afore` | Base MQTT topic prefix (`<prefix>/inverter/<sn>/state`, `<prefix>/logger/<sn>/state`) |
| `mqtt_discovery_prefix` | `homeassistant` | Home Assistant MQTT Discovery prefix |
| `inverter_name` | `Afore Inverter` | Display name of the inverter device in Home Assistant |
| `inverter_model` | `BNTxxxKTL (T4)` | Model string shown on the Home Assistant device page |
| `offline_timeout_seconds` | `600` | Seconds without live frames before marking the inverter offline and zeroing power |
| `mqtt_host` | *(auto)* | Optional manual MQTT broker host (overrides Supervisor Mosquitto auto-discovery) |
| `mqtt_port` | `1883` | Optional manual MQTT broker port |
| `mqtt_username` | *(auto)* | Optional manual MQTT username |
| `mqtt_password` | *(auto)* | Optional manual MQTT password |
| `log_raw_frames` | `false` | Log raw hex V5 payloads for debugging or adapting to other firmware versions |
