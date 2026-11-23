#!/usr/bin/with-contenv bashio
set -euo pipefail

export LISTEN_PORT="$(bashio::config 'listen_port')"
export MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"
export MQTT_DISCOVERY_PREFIX="$(bashio::config 'mqtt_discovery_prefix')"
export INVERTER_NAME="$(bashio::config 'inverter_name')"
export INVERTER_MODEL="$(bashio::config 'inverter_model')"
export OFFLINE_TIMEOUT_SECONDS="$(bashio::config 'offline_timeout_seconds')"
export LOG_RAW_FRAMES="$(bashio::config 'log_raw_frames')"

MQTT_HOST="$(bashio::config 'mqtt_host')"
MQTT_PORT="$(bashio::config 'mqtt_port')"
MQTT_USERNAME="$(bashio::config 'mqtt_username')"
MQTT_PASSWORD="$(bashio::config 'mqtt_password')"

if [[ -z "${MQTT_HOST}" || "${MQTT_HOST}" == "null" ]]; then
    if bashio::services.available "mqtt"; then
        MQTT_HOST="$(bashio::services 'mqtt' 'host')"
        MQTT_PORT="$(bashio::services 'mqtt' 'port')"
        MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"
        MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
        bashio::log.info "Using automatic MQTT configuration from Supervisor (${MQTT_HOST}:${MQTT_PORT})"
    else
        bashio::log.fatal "No Supervisor MQTT service available and mqtt_host is not configured!"
        exit 1
    fi
else
    bashio::log.info "Using manual MQTT configuration (${MQTT_HOST}:${MQTT_PORT})"
fi

export MQTT_HOST
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_USERNAME="${MQTT_USERNAME:-}"
export MQTT_PASSWORD="${MQTT_PASSWORD:-}"

bashio::log.info "Starting Afore data collector on TCP port ${LISTEN_PORT} (prefix: ${MQTT_TOPIC_PREFIX}, discovery: ${MQTT_DISCOVERY_PREFIX})..."
exec python3 -u /app/collector.py
