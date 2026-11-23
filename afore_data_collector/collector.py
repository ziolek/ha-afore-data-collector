#!/usr/bin/env python3
"""Afore data collector: local LSW-3 (Server B) V5 TCP listener -> MQTT Discovery.

Receives pushed binary V5 telemetry frames from an LSW-3 datalogger attached to
an Afore 3-phase inverter (tested on Afore BNT010KTL T4 with LSW3_15_1E03_1.33)
and publishes entities to Home Assistant via MQTT Auto-Discovery.
"""

import asyncio
import json
import logging
import os
import signal
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOG = logging.getLogger("afore_data_collector")


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def build_v5_ack(ctrl_req: int, seq_bytes: bytes, logger_sn: int, payload_req: bytes) -> bytes:
    """Build a V5 server acknowledgment frame."""
    ctrl_ack = (ctrl_req - 0x3000) & 0xFFFF
    frame_type = payload_req[0] if payload_req else 0x00
    ack_payload = struct.pack("<BBII", frame_type, 0x01, int(time.time()), 0x00000078)
    body = (
        struct.pack("<HH", len(ack_payload), ctrl_ack)
        + seq_bytes[:2]
        + struct.pack("<I", logger_sn)
        + ack_payload
    )
    checksum = sum(body) & 0xFF
    return bytes([0xA5]) + body + bytes([checksum, 0x15])


def decode_handshake_0x4110(logger_sn: int, payload: bytes) -> Dict[str, Any]:
    """Extract LSW-3 logger metadata from a 0x4110 handshake frame."""
    info: Dict[str, Any] = {
        "logger_sn": str(logger_sn),
        "online": "ON",
        "last_update": datetime.now(timezone.utc).isoformat(),
    }
    if len(payload) >= 60:
        fw = payload[19:59].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
        if fw:
            info["firmware"] = fw
    if len(payload) >= 82:
        info["mac"] = ":".join(f"{b:02X}" for b in payload[59:65])
        ip = payload[65:81].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
        if ip:
            info["ip"] = ip
    if len(payload) >= 212:
        ssid = payload[172:212].split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if ssid:
            info["wifi_ssid"] = ssid
    return info


def decode_afore_t4_0x4210(payload: bytes) -> Optional[Dict[str, Any]]:
    """Decode a 159-byte Afore BNTxxxKTL (T4) 0x4210 data payload.

    Returns None for cached/historical frames (frame_type bit 7 set, e.g. 0x81)
    or truncated payloads.
    """
    if len(payload) < 80:
        LOG.warning("Ignoring truncated 0x4210 frame (%d bytes)", len(payload))
        return None

    frame_type = payload[0]
    if frame_type & 0x80:
        LOG.info("Skipping cached historical 0x4210 frame (frame_type=0x%02x)", frame_type)
        return None

    inv_sn = payload[21:37].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
    ac_power = struct.unpack("<H", payload[37:39])[0]
    pv1_voltage = round(struct.unpack("<H", payload[39:41])[0] / 10.0, 1)
    pv2_voltage = round(struct.unpack("<H", payload[41:43])[0] / 10.0, 1)
    pv1_current = round(struct.unpack("<H", payload[43:45])[0] / 10.0, 1)
    pv2_current = round(struct.unpack("<H", payload[45:47])[0] / 10.0, 1)
    ac_current_l1 = round(struct.unpack("<H", payload[47:49])[0] / 10.0, 1)
    ac_current_l2 = round(struct.unpack("<H", payload[49:51])[0] / 10.0, 1)
    ac_current_l3 = round(struct.unpack("<H", payload[51:53])[0] / 10.0, 1)
    ac_voltage_l1 = round(struct.unpack("<H", payload[53:55])[0] / 10.0, 1)
    ac_voltage_l2 = round(struct.unpack("<H", payload[55:57])[0] / 10.0, 1)
    ac_voltage_l3 = round(struct.unpack("<H", payload[57:59])[0] / 10.0, 1)
    ac_frequency = round(struct.unpack("<H", payload[59:61])[0] / 100.0, 2)
    inverter_temp = round(struct.unpack("<h", payload[61:63])[0] / 10.0, 1)
    energy_daily = round(struct.unpack("<I", payload[65:69])[0] / 100.0, 2)
    energy_total = round(struct.unpack("<I", payload[69:73])[0] / 10.0, 1)
    module_temp = round(struct.unpack("<h", payload[77:79])[0] / 10.0, 1)

    pv1_power = round(pv1_voltage * pv1_current, 1)
    pv2_power = round(pv2_voltage * pv2_current, 1)

    data: Dict[str, Any] = {
        "inverter_sn": inv_sn,
        "online": "ON",
        "ac_power": ac_power,
        "energy_daily": energy_daily,
        "energy_total": energy_total,
        "pv1_voltage": pv1_voltage,
        "pv1_current": pv1_current,
        "pv1_power": pv1_power,
        "pv2_voltage": pv2_voltage,
        "pv2_current": pv2_current,
        "pv2_power": pv2_power,
        "ac_voltage_l1": ac_voltage_l1,
        "ac_current_l1": ac_current_l1,
        "ac_voltage_l2": ac_voltage_l2,
        "ac_current_l2": ac_current_l2,
        "ac_voltage_l3": ac_voltage_l3,
        "ac_current_l3": ac_current_l3,
        "ac_frequency": ac_frequency,
        "inverter_temperature": inverter_temp,
        "module_temperature": module_temp,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }

    if len(payload) >= 138:
        fw1 = payload[96:116].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
        fw2 = payload[116:136].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
        if fw1 or fw2:
            data["firmware"] = " / ".join(p for p in (fw1, fw2) if p)

    if len(payload) >= 153:
        yy, mo, dd, hh, mi, ss = payload[145:151]
        if 20 <= yy <= 99 and 1 <= mo <= 12 and 1 <= dd <= 31:
            data["inverter_time"] = f"20{yy:02d}-{mo:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}"
        pf_raw = struct.unpack(">H", payload[151:153])[0]
        if 0 <= pf_raw <= 1000:
            data["power_factor"] = round(pf_raw / 1000.0, 3)

    return data


INVERTER_SENSORS: List[Dict[str, Any]] = [
    {
        "key": "ac_power",
        "name": "AC Power",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
        "icon": "mdi:solar-power",
    },
    {
        "key": "energy_daily",
        "name": "Daily Energy",
        "device_class": "energy",
        "state_class": "total_increasing",
        "unit_of_measurement": "kWh",
        "icon": "mdi:solar-power-variant",
    },
    {
        "key": "energy_total",
        "name": "Total Energy",
        "device_class": "energy",
        "state_class": "total_increasing",
        "unit_of_measurement": "kWh",
        "icon": "mdi:counter",
    },
    {
        "key": "pv1_voltage",
        "name": "PV1 Voltage",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
    },
    {
        "key": "pv1_current",
        "name": "PV1 Current",
        "device_class": "current",
        "state_class": "measurement",
        "unit_of_measurement": "A",
    },
    {
        "key": "pv1_power",
        "name": "PV1 Power",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
    },
    {
        "key": "pv2_voltage",
        "name": "PV2 Voltage",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
    },
    {
        "key": "pv2_current",
        "name": "PV2 Current",
        "device_class": "current",
        "state_class": "measurement",
        "unit_of_measurement": "A",
    },
    {
        "key": "pv2_power",
        "name": "PV2 Power",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
    },
    {
        "key": "ac_voltage_l1",
        "name": "AC Voltage L1",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
    },
    {
        "key": "ac_current_l1",
        "name": "AC Current L1",
        "device_class": "current",
        "state_class": "measurement",
        "unit_of_measurement": "A",
    },
    {
        "key": "ac_voltage_l2",
        "name": "AC Voltage L2",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
    },
    {
        "key": "ac_current_l2",
        "name": "AC Current L2",
        "device_class": "current",
        "state_class": "measurement",
        "unit_of_measurement": "A",
    },
    {
        "key": "ac_voltage_l3",
        "name": "AC Voltage L3",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
    },
    {
        "key": "ac_current_l3",
        "name": "AC Current L3",
        "device_class": "current",
        "state_class": "measurement",
        "unit_of_measurement": "A",
    },
    {
        "key": "ac_frequency",
        "name": "AC Frequency",
        "device_class": "frequency",
        "state_class": "measurement",
        "unit_of_measurement": "Hz",
    },
    {
        "key": "inverter_temperature",
        "name": "Inverter Temperature",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": "°C",
    },
    {
        "key": "module_temperature",
        "name": "Module Temperature",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": "°C",
    },
    {
        "key": "power_factor",
        "name": "Power Factor",
        "device_class": "power_factor",
        "state_class": "measurement",
    },
    {
        "key": "last_update",
        "name": "Last Update",
        "device_class": "timestamp",
        "entity_category": "diagnostic",
    },
]

LOGGER_SENSORS: List[Dict[str, Any]] = [
    {"key": "ip", "name": "IP Address", "icon": "mdi:ip-network", "entity_category": "diagnostic"},
    {"key": "wifi_ssid", "name": "Wi-Fi SSID", "icon": "mdi:wifi", "entity_category": "diagnostic"},
    {"key": "firmware", "name": "Firmware", "icon": "mdi:chip", "entity_category": "diagnostic"},
    {
        "key": "last_update",
        "name": "Last Update",
        "device_class": "timestamp",
        "entity_category": "diagnostic",
    },
]


class AforeCollector:
    def __init__(self) -> None:
        self.listen_port = int(os.getenv("LISTEN_PORT", "10000"))
        self.prefix = os.getenv("MQTT_TOPIC_PREFIX", "afore").strip("/")
        self.discovery_prefix = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant").strip("/")
        self.inverter_name = os.getenv("INVERTER_NAME", "Afore Inverter").strip() or "Afore Inverter"
        self.inverter_model = os.getenv("INVERTER_MODEL", "BNTxxxKTL (T4)").strip() or "BNTxxxKTL (T4)"
        self.offline_timeout = int(os.getenv("OFFLINE_TIMEOUT_SECONDS", "600"))
        self.log_raw = env_bool("LOG_RAW_FRAMES", False)

        self.mqtt_host = os.environ["MQTT_HOST"]
        self.mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        self.mqtt_user = os.getenv("MQTT_USERNAME", "")
        self.mqtt_pass = os.getenv("MQTT_PASSWORD", "")

        self.bridge_status_topic = f"{self.prefix}/bridge/status"

        self.last_inverter_seen: float = 0.0
        self.is_offline_published: bool = False
        self.logger_sn: Optional[str] = None
        self.inverter_sn: Optional[str] = None
        self.logger_state: Dict[str, Any] = {}
        self.inverter_state: Dict[str, Any] = {}
        self.discovery_published_logger: bool = False
        self.discovery_published_inverter: bool = False

        if hasattr(mqtt, "CallbackAPIVersion"):
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="afore_data_collector")
        else:
            self.mqtt_client = mqtt.Client(client_id="afore_data_collector")

        if self.mqtt_user:
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        self.mqtt_client.will_set(self.bridge_status_topic, "offline", qos=1, retain=True)
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.reconnect_delay_set(min_delay=2, max_delay=30)

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        LOG.info("Connected to MQTT broker %s:%d (code: %s)", self.mqtt_host, self.mqtt_port, reason_code)
        client.publish(self.bridge_status_topic, "online", qos=1, retain=True)
        client.subscribe(f"{self.discovery_prefix}/status", qos=1)
        self._republish_all_discovery()

    def _on_mqtt_disconnect(self, client, userdata, *args):
        LOG.warning("Disconnected from MQTT broker, reconnecting automatically...")

    def _on_mqtt_message(self, client, userdata, msg):
        if msg.topic == f"{self.discovery_prefix}/status":
            payload = msg.payload.decode("utf-8", errors="ignore").strip().lower()
            if payload == "online":
                LOG.info("Home Assistant reported online — republishing MQTT Discovery configs")
                self._republish_all_discovery()

    def pub_raw(self, topic: str, payload: Any, retain: bool = True) -> None:
        msg = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
        res = self.mqtt_client.publish(topic, msg, qos=1, retain=retain)
        if res.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("Failed to publish MQTT message to %s (rc=%s)", topic, res.rc)

    def _logger_state_topic(self, sn: str) -> str:
        return f"{self.prefix}/logger/{sn}/state"

    def _inverter_state_topic(self, sn: str) -> str:
        return f"{self.prefix}/inverter/{sn}/state"

    def _origin_block(self) -> Dict[str, str]:
        return {
            "name": "Afore data collector",
            "sw_version": "1.0.0",
        }

    def _logger_device_block(self, sn: str) -> Dict[str, Any]:
        dev: Dict[str, Any] = {
            "identifiers": [f"afore_logger_{sn}"],
            "name": "Afore LSW-3",
            "manufacturer": "Afore",
            "model": "LSW-3",
            "serial_number": sn,
        }
        if self.logger_state.get("firmware"):
            dev["sw_version"] = self.logger_state["firmware"]
        if self.logger_state.get("mac"):
            dev["connections"] = [["mac", self.logger_state["mac"]]]
        return dev

    def _inverter_device_block(self, sn: str) -> Dict[str, Any]:
        dev: Dict[str, Any] = {
            "identifiers": [f"afore_inverter_{sn}"],
            "name": self.inverter_name,
            "manufacturer": "Afore",
            "model": self.inverter_model,
            "serial_number": sn,
        }
        if self.inverter_state.get("firmware"):
            dev["sw_version"] = self.inverter_state["firmware"]
        if self.logger_sn:
            dev["via_device"] = f"afore_logger_{self.logger_sn}"
        return dev

    def publish_logger_discovery(self, sn: str) -> None:
        device = self._logger_device_block(sn)
        state_topic = self._logger_state_topic(sn)
        origin = self._origin_block()
        availability = [{"topic": self.bridge_status_topic}]

        self.pub_raw(
            f"{self.discovery_prefix}/binary_sensor/afore_logger_{sn}/connectivity/config",
            {
                "name": "Connectivity",
                "unique_id": f"afore_logger_{sn}_connectivity",
                "state_topic": state_topic,
                "value_template": "{{ value_json.online }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "connectivity",
                "entity_category": "diagnostic",
                "availability": availability,
                "device": device,
                "origin": origin,
            },
            retain=True,
        )

        for spec in LOGGER_SENSORS:
            key = spec["key"]
            cfg: Dict[str, Any] = {
                "name": spec["name"],
                "unique_id": f"afore_logger_{sn}_{key}",
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{key} if value_json.{key} is defined else None }}}}",
                "availability": availability,
                "device": device,
                "origin": origin,
            }
            for opt in ("device_class", "icon", "entity_category"):
                if opt in spec:
                    cfg[opt] = spec[opt]
            self.pub_raw(
                f"{self.discovery_prefix}/sensor/afore_logger_{sn}/{key}/config",
                cfg,
                retain=True,
            )

        self.discovery_published_logger = True
        LOG.info("Published MQTT Discovery config for logger Afore LSW-3 (SN=%s)", sn)

    def publish_inverter_discovery(self, sn: str) -> None:
        device = self._inverter_device_block(sn)
        state_topic = self._inverter_state_topic(sn)
        origin = self._origin_block()
        availability = [{"topic": self.bridge_status_topic}]

        self.pub_raw(
            f"{self.discovery_prefix}/binary_sensor/afore_inverter_{sn}/connectivity/config",
            {
                "name": "Operating Status",
                "unique_id": f"afore_inverter_{sn}_connectivity",
                "state_topic": state_topic,
                "value_template": "{{ value_json.online }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "connectivity",
                "availability": availability,
                "device": device,
                "origin": origin,
            },
            retain=True,
        )

        for spec in INVERTER_SENSORS:
            key = spec["key"]
            cfg: Dict[str, Any] = {
                "name": spec["name"],
                "unique_id": f"afore_inverter_{sn}_{key}",
                "state_topic": state_topic,
                "value_template": (
                    f"{{{{ value_json.{key} if value_json.{key} is defined "
                    f"and value_json.{key} is not none else None }}}}"
                ),
                "availability": availability,
                "device": device,
                "origin": origin,
            }
            for opt in ("device_class", "state_class", "unit_of_measurement", "icon", "entity_category"):
                if opt in spec:
                    cfg[opt] = spec[opt]
            self.pub_raw(
                f"{self.discovery_prefix}/sensor/afore_inverter_{sn}/{key}/config",
                cfg,
                retain=True,
            )

        self.discovery_published_inverter = True
        LOG.info("Published MQTT Discovery config for inverter %s (SN=%s)", self.inverter_name, sn)

    def _republish_all_discovery(self) -> None:
        if self.logger_sn:
            self.publish_logger_discovery(self.logger_sn)
            if self.logger_state:
                self.pub_raw(self._logger_state_topic(self.logger_sn), self.logger_state, retain=True)
        if self.inverter_sn:
            self.publish_inverter_discovery(self.inverter_sn)
            if self.inverter_state:
                self.pub_raw(self._inverter_state_topic(self.inverter_sn), self.inverter_state, retain=True)

    def handle_logger_handshake(self, logger_sn: int, payload: bytes) -> None:
        sn = str(logger_sn)
        self.logger_sn = sn
        self.logger_state.update(decode_handshake_0x4110(logger_sn, payload))
        self.publish_logger_discovery(sn)
        self.pub_raw(self._logger_state_topic(sn), self.logger_state, retain=True)
        LOG.info("LSW-3 handshake SN=%s (FW=%s)", sn, self.logger_state.get("firmware"))

    def handle_inverter_data(self, logger_sn: int, parsed: Dict[str, Any]) -> None:
        self.last_inverter_seen = time.monotonic()
        self.is_offline_published = False

        lsn = str(logger_sn)
        if self.logger_sn != lsn or not self.discovery_published_logger:
            self.logger_sn = lsn
            self.logger_state.setdefault("logger_sn", lsn)
            self.logger_state["online"] = "ON"
            self.logger_state["last_update"] = datetime.now(timezone.utc).isoformat()
            self.publish_logger_discovery(lsn)
            self.pub_raw(self._logger_state_topic(lsn), self.logger_state, retain=True)

        inv_sn = parsed.get("inverter_sn") or f"LSW3_{lsn}"
        need_disc = (self.inverter_sn != inv_sn) or (not self.discovery_published_inverter)
        if parsed.get("firmware") and parsed.get("firmware") != self.inverter_state.get("firmware"):
            need_disc = True

        self.inverter_sn = inv_sn
        if parsed.get("energy_total", 0) <= 0 and self.inverter_state.get("energy_total"):
            parsed["energy_total"] = self.inverter_state["energy_total"]

        self.inverter_state.update(parsed)

        if need_disc:
            self.publish_inverter_discovery(inv_sn)

        self.pub_raw(self._inverter_state_topic(inv_sn), self.inverter_state, retain=True)
        LOG.info(
            "Inverter data [%s]: power=%s W, daily=%s kWh, total=%s kWh, PV1=%sV/%sA, PV2=%sV/%sA, temp=%s°C",
            inv_sn,
            parsed["ac_power"],
            parsed["energy_daily"],
            parsed["energy_total"],
            parsed["pv1_voltage"],
            parsed["pv1_current"],
            parsed["pv2_voltage"],
            parsed["pv2_current"],
            parsed["inverter_temperature"],
        )

    def publish_offline(self) -> None:
        if self.is_offline_published:
            return
        self.is_offline_published = True
        now_iso = datetime.now(timezone.utc).isoformat()

        if self.logger_sn and self.logger_state:
            self.logger_state["online"] = "OFF"
            self.pub_raw(self._logger_state_topic(self.logger_sn), self.logger_state, retain=True)

        if self.inverter_sn and self.inverter_state:
            offline_state = dict(self.inverter_state)
            offline_state.update(
                {
                    "online": "OFF",
                    "ac_power": 0,
                    "pv1_voltage": 0.0,
                    "pv1_current": 0.0,
                    "pv1_power": 0.0,
                    "pv2_voltage": 0.0,
                    "pv2_current": 0.0,
                    "pv2_power": 0.0,
                    "ac_current_l1": 0.0,
                    "ac_current_l2": 0.0,
                    "ac_current_l3": 0.0,
                    "ac_voltage_l1": None,
                    "ac_voltage_l2": None,
                    "ac_voltage_l3": None,
                    "ac_frequency": None,
                    "inverter_temperature": None,
                    "module_temperature": None,
                    "power_factor": None,
                    "last_update": now_iso,
                }
            )
            self.inverter_state = offline_state
            self.pub_raw(self._inverter_state_topic(self.inverter_sn), self.inverter_state, retain=True)

        LOG.info(
            "No frames from LSW-3 for %ds -> marked Offline (power=0 W, energy counters preserved)",
            self.offline_timeout,
        )

    async def watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            if self.last_inverter_seen > 0 and (now - self.last_inverter_seen) > self.offline_timeout:
                self.publish_offline()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        LOG.info("TCP connection from %s", peer)
        buf = bytearray()
        try:
            while True:
                data = await asyncio.wait_for(reader.read(4096), timeout=360.0)
                if not data:
                    LOG.info("TCP connection closed by %s", peer)
                    break
                buf.extend(data)
                while len(buf) >= 13:
                    idx = buf.find(b"\xA5")
                    if idx == -1:
                        buf.clear()
                        break
                    if idx > 0:
                        del buf[:idx]
                    if len(buf) < 13:
                        break
                    plen, ctrl = struct.unpack("<HH", buf[1:5])
                    total_len = 1 + 10 + plen + 2
                    if len(buf) < total_len:
                        break
                    frame = bytes(buf[:total_len])
                    del buf[:total_len]

                    if frame[-1] != 0x15:
                        LOG.warning("Invalid V5 frame trailer (0x%02x), skipping", frame[-1])
                        continue

                    seq_bytes = frame[5:7]
                    logger_sn = struct.unpack("<I", frame[7:11])[0]
                    payload = frame[11:-2]

                    if self.log_raw:
                        LOG.info(
                            "RAW ctrl=0x%04x seq=%s sn=%d plen=%d payload=%s",
                            ctrl,
                            seq_bytes.hex(),
                            logger_sn,
                            plen,
                            payload.hex(),
                        )

                    if (ctrl & 0xF000) == 0x4000:
                        ack = build_v5_ack(ctrl, seq_bytes, logger_sn, payload)
                        writer.write(ack)
                        await writer.drain()

                    if ctrl == 0x4110:
                        self.handle_logger_handshake(logger_sn, payload)
                    elif ctrl == 0x4210:
                        parsed = decode_afore_t4_0x4210(payload)
                        if parsed is not None:
                            self.handle_inverter_data(logger_sn, parsed)
                    elif ctrl == 0x4710:
                        if self.logger_sn:
                            self.logger_state["online"] = "ON"
                            self.logger_state["last_update"] = datetime.now(timezone.utc).isoformat()
                            self.pub_raw(self._logger_state_topic(self.logger_sn), self.logger_state, retain=True)
        except asyncio.TimeoutError:
            LOG.info("Idle timeout for %s (closing socket)", peer)
        except Exception as exc:
            LOG.exception("Connection error for %s: %s", peer, exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def run(self) -> None:
        self.mqtt_client.connect_async(self.mqtt_host, self.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()

        server = await asyncio.start_server(self.handle_client, "0.0.0.0", self.listen_port)
        LOG.info("Listening for LSW-3 (Server B) V5 frames on 0.0.0.0:%d", self.listen_port)

        watchdog = asyncio.create_task(self.watchdog_loop())
        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        await stop_event.wait()
        LOG.info("Stopping Afore data collector...")
        watchdog.cancel()
        server.close()
        await server.wait_closed()
        self.mqtt_client.publish(self.bridge_status_topic, "offline", qos=1, retain=True)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(AforeCollector().run())
