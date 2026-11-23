# Afore data collector — Home Assistant Add-on

A lightweight, 100% local Home Assistant add-on that receives binary V5 telemetry frames pushed by an **LSW-3** Wi-Fi stick logger (**Remote Server B**) connected to an **Afore** PV inverter and publishes all inverter and logger metrics to Home Assistant via **MQTT Auto-Discovery**.

---

## Background & Motivation

This add-on was created to move away from cloud-based monitoring to fully local telemetry in Home Assistant:

1. **Cloud API limits:** Fetching inverter data remotely via the Solarman cloud OpenAPI has a low free-tier quota (**100,000 API calls**), which is easily exhausted (`appId insufficient allowance`), introduces cloud latency, and depends on external internet access.
2. **Local Modbus polling did not work:** Attempting standard local Modbus RTU-over-TCP polling on port `8899` failed on this hardware combination — the LSW-3 logger accepted the V5 handshake but consistently returned `05 00` (no valid Modbus RTU reply from the inverter under its factory RS485 protocol).
3. **Why Remote Server B works:** The LSW-3 logger natively supports a secondary telemetry destination (**Server B**) configurable via its built-in hidden web page (`http://<LOGGER_IP>/config_hide.html`). By running a small local TCP listener inside Home Assistant OS, the logger pushes full telemetry frames every ~5 minutes directly over your LAN — **without modifying inverter settings, without HACS, and without disrupting Server A (cloud) if you still want to keep it**.

---

## Tested Hardware & Environment

| Component | Tested Model / Version |
| :--- | :--- |
| **Inverter** | **Afore BNT010KTL** (3-phase, 2 MPPT, T4 generation, firmware `12.41 / 1.18`) |
| **Datalogger** | **LSW-3** Wi-Fi Stick Logger (firmware `LSW3_15_1E03_1.33`) |
| **Home Assistant** | Home Assistant OS 18.5 (`aarch64` / Raspberry Pi), Core `2026.11`, Supervisor `2026.11` |
| **MQTT Broker** | Official Home Assistant **Mosquitto broker** add-on |

Other 3-phase Afore `BNTxxxKTL` (T4) inverters using an LSW-3 logger with `1E03` firmware are expected to use the same frame layout, though register offsets have only been verified on the hardware listed above.

---

## Features

- **100% local push telemetry** over TCP (default port `10000`) — no cloud API, no rate limits, no HACS required.
- **Automatic MQTT Discovery** — registers two linked devices in Home Assistant (**Afore Inverter** and **Afore LSW-3**) with 26 entities out of the box.
- **Automatic Mosquitto discovery** via Home Assistant Supervisor (`services: mqtt:want`), with optional manual MQTT broker overrides.
- **Energy Dashboard safe** — cumulative (`Total Energy`) and daily (`Daily Energy`) counters use `state_class: total_increasing` and are never reset to `0` at night or on transient glitches.
- **Clean night/offline handling** — after `offline_timeout_seconds` without frames (e.g. after sunset), power and current sensors drop to `0`, temperatures/grid metrics clear cleanly, and connectivity status switches to `OFF`.
- **Historical buffer filtering** — acknowledges cached historical frames (`frame_type` bit 7 set, e.g. `0x81`) so the logger clears its buffer, while only publishing live frames (`0x01`) to MQTT.

---

## Installation

### Option A: Add as a Home Assistant Add-on Repository (Recommended)

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fziolek%2Fha-afore-data-collector)

Or manually:

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Click the three-dots menu (**⋮**) in the top-right corner and select **Repositories**.
3. Add this repository URL:
   ```text
   https://github.com/ziolek/ha-afore-data-collector
   ```
4. Reload the store, locate **Afore data collector**, and click **Install**.

### Option B: Install as a Local Add-on

1. Copy the `afore_data_collector` folder to `/addons/afore_data_collector` on your Home Assistant host (e.g. via the Samba share add-on).
2. Go to **Settings → Add-ons → Add-on Store → (⋮) Check for updates**.
3. Under **Local add-ons**, open **Afore data collector** and click **Install**.

---

## Configuration

### 1. Start the Add-on

1. Open the **Configuration** tab of **Afore data collector** and review defaults (if you use the official Mosquitto broker add-on, leave the optional `mqtt_*` fields unset so credentials are fetched automatically from Supervisor).
2. Enable **Start on boot** and **Watchdog**, then click **Start**.
3. Check the **Log** tab to confirm it connected to MQTT and is listening on port `10000`.

### 2. Configure Remote Server B on the LSW-3 Logger

1. Open the logger's hidden configuration page in your browser:
   ```text
   http://<LOGGER_IP>/config_hide.html
   ```
2. Scroll to **Secondary Server Setting (Server B)** and set:
   - **IP address:** `<HOME_ASSISTANT_IP>`
   - **Domain name:** *(leave completely empty — clear any existing domain)*
   - **Port:** `10000`
   - **Connection:** `TCP`
3. Click **Save** under Server B, then click **Restart** when prompted.

> **Networking note (VLANs / dual-homed hosts):** Ensure the LSW-3 logger can reach `<HOME_ASSISTANT_IP>` on TCP port `10000`. If Home Assistant has multiple network interfaces across VLANs, point Server B to the Home Assistant IP in the **same subnet/VLAN** as the LSW-3 logger to avoid asymmetric routing issues.

Within ~30–60 seconds (while the inverter is awake during daylight), the logger connects, completes the V5 handshake, and publishes its first telemetry frame. Both devices will appear automatically under **Settings → Devices & Services → MQTT**.

---

## Exposed Entities

### Inverter Device (21 entities)
- **Power & Energy:** `AC Power` (`W`), `Daily Energy` (`kWh`), `Total Energy` (`kWh`)
- **DC Strings:** `PV1 Voltage` (`V`), `PV1 Current` (`A`), `PV1 Power` (`W`), `PV2 Voltage` (`V`), `PV2 Current` (`A`), `PV2 Power` (`W`)
- **3-Phase AC Grid:** `AC Voltage L1/L2/L3` (`V`), `AC Current L1/L2/L3` (`A`), `AC Frequency` (`Hz`), `Power Factor`
- **Temperatures:** `Inverter Temperature` (`°C`), `Module Temperature` (`°C`)
- **Diagnostics:** `Operating Status` (`binary_sensor`), `Last Update` (`timestamp`)

### Logger Device — `Afore LSW-3` (5 diagnostic entities)
- `Connectivity` (`binary_sensor`), `IP Address`, `Wi-Fi SSID`, `Firmware`, `Last Update` (`timestamp`)

---

## Troubleshooting

- **No connection from LSW-3 in add-on logs:**
  - Verify the inverter is powered on (string inverters power down at night along with the LSW-3 stick).
  - Re-open `http://<LOGGER_IP>/config_hide.html` and confirm **Domain name** under Server B is empty and **IP address** + **Port** were saved, then restart the logger.
  - Check `http://<LOGGER_IP>/status.html` — **Remote server B** should show **Connected**.
- **Debugging raw frames:** Enable `log_raw_frames: true` in the add-on configuration to inspect hex payloads in the add-on log (useful when adapting offsets for other Afore firmware versions).

---

## License

MIT — see [LICENSE](LICENSE).
