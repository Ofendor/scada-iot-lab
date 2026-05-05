# =============================================================================
# AquaNet NZ - Water Treatment Plant Monitor
# =============================================================================
# Author: Emilio Mardones
# Project: SCADA IoT Lab - Critical Infrastructure Security Portfolio
# Description:
#   Subscribes to all AquaNet sensor topics via local Mosquitto broker.
#   Checks readings against NPS-FM 2020 freshwater quality standards and
#   AquaNet operational limits. Logs all readings and alerts to CSV.
#   Publishes alert status back to Scada-LTS via MQTT.
#
#   Inspired by university IoT lab work (NZSE 2025)
#   Original Raspberry Pi + HiveMQ implementation twisted for local
#   infrastructure. CSV logging pattern modified.
#
# Protocol: MQTT (paho-mqtt) subscribing from local Eclipse Mosquitto broker
# =============================================================================

import csv                           # for logging readings to CSV file
import paho.mqtt.client as mqtt      # MQTT client for broker communication
from datetime import datetime        # for timestamping log entries
from time import sleep               # for keeping the script alive

# =============================================================================
# CONFIGURATION
# =============================================================================

# --- MQTT broker connection settings ---
MQTT_HOST     = "localhost"          # local Mosquitto broker in Docker
MQTT_PORT     = 1883                 # standard MQTT port (no TLS)
MQTT_USERNAME = "aquanet"            # broker credentials (lab running locally
				     # no risk of exposure. Do not expose 
                                     # credential in real environments)
MQTT_PASSWORD = "AquaNet2026!"       # broker credentials
MQTT_QOS      = 1                    # QoS 1: at least once delivery because 
                                     # there is not data loss within local 
                                     # environment. Consider QoS 2 if cloud broker

# --- Topics to subscribe to ---
TOPICS = [
    "aquanet/water/turbidity",       # NTU
    "aquanet/water/ecoli",           # CFU/100ml
    "aquanet/water/ph",              # pH units
    "aquanet/water/nitrate",         # mg/L
    "aquanet/hydraulic/pressure",    # bar
    "aquanet/hydraulic/flowrate",    # L/min
    "aquanet/alerts",                # alert messages from simulator
]

# --- CSV log file ---
LOG_FILE = "/home/victim1/scada-iot-lab/docs/aquanet_monitor_log.csv"

# --- NPS-FM 2020 alert thresholds ---
THRESHOLD_ECOLI_MAX     = 540.0     # CFU/100ml
THRESHOLD_TURBIDITY_MAX = 5.0       # NTU
THRESHOLD_PH_MIN        = 6.5       # pH units
THRESHOLD_PH_MAX        = 8.5       # pH units
THRESHOLD_NITRATE_MAX   = 6.9       # mg/L
THRESHOLD_PRESSURE_MAX  = 5.0       # bar
THRESHOLD_PRESSURE_MIN  = 1.5       # bar
THRESHOLD_FLOWRATE_MAX  = 150.0     # L/min

# =============================================================================
# CSV LOGGER
# =============================================================================

def log_to_csv(timestamp, topic, value, status):
    """
    Append a sensor reading to the CSV log file.
    Same logging pattern as DNCT702 TASK3 write_to_csv function,
    extended with status column for alert tracking.

    Args:
        timestamp (str): when the reading was received
        topic (str): MQTT topic the reading came from
        value (str): sensor reading value
        status (str): OK or ALERT
    """
    with open(LOG_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, topic, value, status])

# =============================================================================
# THRESHOLD CHECKER
# =============================================================================

def check_threshold(topic, value):
    """
    Check a single sensor reading against its threshold.
    Returns a status string: OK or ALERT with description.

    Args:
        topic (str): MQTT topic identifying the sensor
        value (float): sensor reading

    Returns:
        str: OK or ALERT message
    """
    if "ecoli" in topic:
        if value > THRESHOLD_ECOLI_MAX:
            return f"ALERT - E.coli {value} CFU/100ml exceeds {THRESHOLD_ECOLI_MAX}"
    elif "turbidity" in topic:
        if value > THRESHOLD_TURBIDITY_MAX:
            return f"ALERT - Turbidity {value} NTU exceeds {THRESHOLD_TURBIDITY_MAX}"
    elif "ph" in topic:
        if value < THRESHOLD_PH_MIN:
            return f"ALERT - pH {value} below minimum {THRESHOLD_PH_MIN}"
        elif value > THRESHOLD_PH_MAX:
            return f"ALERT - pH {value} above maximum {THRESHOLD_PH_MAX}"
    elif "nitrate" in topic:
        if value > THRESHOLD_NITRATE_MAX:
            return f"ALERT - Nitrate {value} mg/L exceeds {THRESHOLD_NITRATE_MAX}"
    elif "pressure" in topic:
        if value > THRESHOLD_PRESSURE_MAX:
            return f"ALERT - Pressure {value} bar exceeds {THRESHOLD_PRESSURE_MAX}"
        elif value < THRESHOLD_PRESSURE_MIN:
            return f"ALERT - Pressure {value} bar below minimum {THRESHOLD_PRESSURE_MIN}"
    elif "flowrate" in topic:
        if value > THRESHOLD_FLOWRATE_MAX:
            return f"ALERT - Flow {value} L/min exceeds {THRESHOLD_FLOWRATE_MAX}"
    return "OK"

# =============================================================================
# MQTT CALLBACKS
# =============================================================================

def on_connect(client, userdata, flags, reason_code, properties=None):
    """
    Callback fired when monitor connects to Mosquitto.
    Subscribes to all AquaNet sensor topics on connection.
    MQTTv5 pattern.
    """
    if reason_code == 0:
        print(f"Monitor connected to Mosquitto at {MQTT_HOST}:{MQTT_PORT}")
        for topic in TOPICS:
            client.subscribe(topic, qos=MQTT_QOS)
            print(f"  Subscribed to: {topic}")
        print("-" * 60)
    else:
        print(f"Connection failed - reason code: {reason_code}")

def on_message(client, userdata, msg):
    """
    Callback fired when a message arrives on any subscribed topic.
    Logs to CSV and prints colour-coded output to terminal.
    Mirrors on_message pattern with threshold checking added.

    Args:
        msg: MQTT message object containing topic and payload
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    topic     = msg.topic
    payload   = msg.payload.decode()

    # Handle alert messages separately - just log and display
    if topic == "aquanet/alerts":
        print(f"[{timestamp}] *** {payload} ***")
        log_to_csv(timestamp, topic, payload, "ALERT")
        return

    # Try to convert payload to float for threshold checking
    try:
        value  = float(payload)
        status = check_threshold(topic, value)
    except ValueError:
        # Non-numeric payload - log as is
        status = "INFO"
        log_to_csv(timestamp, topic, payload, status)
        return

    # Log to CSV
    log_to_csv(timestamp, topic, payload, status)

    # Print to terminal with status indicator
    if "ALERT" in status:
        print(f"[{timestamp}] {topic}: {value} | *** {status} ***")
    else:
        print(f"[{timestamp}] {topic}: {value} | {status}")

# =============================================================================
# MQTT CONNECTION
# =============================================================================

def connect_monitor():
    """
    Create and connect MQTT client for monitoring.
    Subscribes to all AquaNet topics via on_connect callback.
    """
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    return client

# =============================================================================
# MAIN
# =============================================================================

def run_monitor():
    """
    Main monitor loop. Connects to Mosquitto and listens indefinitely
    for sensor data published by simulator.py.
    All readings logged to CSV at:
    ~/scada-iot-lab/docs/aquanet_monitor_log.csv
    """
    print("=" * 60)
    print("  AquaNet NZ - Water Quality Monitor")
    print("  Subscribing to all aquanet/* topics")
    print(f"  Logging to: {LOG_FILE}")
    print("=" * 60)

    # Write CSV header if file is new
    try:
        with open(LOG_FILE, "x", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["timestamp", "topic", "value", "status"])
        print("  Created new log file with headers.")
    except FileExistsError:
        print("  Appending to existing log file.")

    print()

    # Connect and start listening
    client = connect_monitor()
    client.loop_forever()   # blocks here, handles reconnection automatically

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        run_monitor()
    except KeyboardInterrupt:
        print("\nMonitor stopped by user.")
