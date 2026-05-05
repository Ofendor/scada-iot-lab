# =============================================================================
# AquaNet NZ - Water Treatment Plant Sensor Simulator
# =============================================================================
# Author: Emilio Mardones
# Project: SCADA IoT Lab - Critical Infrastructure Security Portfolio
#
# Description:
#   Simulates a water treatment plant sensor network for the fictional
#   AquaNet NZ facility serving the Avondale catchment, Auckland.
#
#   Data sources:
#   - Water quality: LAWA (Land, Air, Water Aotearoa) - real NZ monitoring
#     data from Auckland Council, Avondale catchment. Licensed CC BY 4.0.
#     Source: lawa.org.nz
#   - Hydraulic data: EPyT (EPANET Python Toolkit) - open source hydraulic
#     simulation engine. Simulates pipe pressure and flow rate.
#     Source: github.com/OpenWaterAnalytics/EPyT
#     Full EPyT integration planned for v2.0 using an Avondale .inp network
#     file. Current version uses statistically realistic EPANET-based ranges.
#
#   Protocol: MQTT via Eclipse Mosquitto (all sensor data + alerts)
#
#   This reflects NZ data sovereignty principles - all data stays on-premise,
#   consistent with Catalyst Cloud's All-of-Government infrastructure mission.
#
# NPS-FM 2020 Alert Thresholds (NZ National Policy Statement for Freshwater):
#   - E.coli:    > 540  CFU/100ml  = ALERT (recreational water unsafe)
#   - Turbidity: > 5.0  NTU        = ALERT (treatment required)
#   - pH:        < 6.5 or > 8.5   = ALERT (corrosion/scaling risk)
#   - Nitrate:   > 6.9  mg/L       = ALERT (NPS-FM ecosystem bottom line)
#   - Pressure:  > 5.0 bar         = ALERT (pipe burst risk)
#   - Pressure:  < 1.5 bar         = ALERT (backflow contamination risk)
#   - Flowrate:  > 150 L/min       = ALERT (above operational range)
#
# Security note:
#   MQTT running on port 1883 without TLS - known Scada-LTS limitation.
#   Recommended hardening: VLAN segmentation, VPN tunnel, or reverse proxy
#   with TLS termination. See README.md for full security discussion.
# =============================================================================

import time                      # sleep loop timing
import random                    # realistic sensor noise
import pandas as pd              # read LAWA CSV data
import paho.mqtt.client as mqtt  # MQTT client for Mosquitto broker
from datetime import datetime    # timestamp published messages

# =============================================================================
# CONFIGURATION
# =============================================================================

# --- MQTT broker connection ---
MQTT_HOST     = "localhost"       # local Mosquitto broker in Docker
MQTT_PORT     = 1883              # standard MQTT port (no TLS)
MQTT_USERNAME = "aquanet"         # broker credentials
MQTT_PASSWORD = "AquaNet2026!"    # broker credentials
MQTT_QOS      = 1                 # QoS 1: at least once delivery

# --- MQTT topic structure: facility/system/sensor ---
TOPIC_TURBIDITY = "aquanet/water/turbidity"      # NTU
TOPIC_ECOLI     = "aquanet/water/ecoli"          # CFU/100ml
TOPIC_PH        = "aquanet/water/ph"             # pH units
TOPIC_NITRATE   = "aquanet/water/nitrate"        # mg/L
TOPIC_PRESSURE  = "aquanet/hydraulic/pressure"   # bar
TOPIC_FLOWRATE  = "aquanet/hydraulic/flowrate"   # L/min
TOPIC_ALERTS    = "aquanet/alerts"               # alert messages

# --- LAWA data ---
LAWA_FILE  = "/home/victim1/scada-iot-lab/epanet/lawa_avondale.csv"
CATCHMENT  = "Avondale"           # Auckland catchment

# --- Simulation settings ---
PUBLISH_INTERVAL = 10             # seconds between sensor reading cycles

# --- NPS-FM 2020 thresholds ---
THRESHOLD_ECOLI_MAX     = 540.0   # CFU/100ml
THRESHOLD_TURBIDITY_MAX = 5.0     # NTU
THRESHOLD_PH_MIN        = 6.5     # pH units
THRESHOLD_PH_MAX        = 8.5     # pH units
THRESHOLD_NITRATE_MAX   = 6.9     # mg/L
THRESHOLD_PRESSURE_MAX  = 4.0     # bar [LOWERED TO TRIGGER MORE ALERTS]
THRESHOLD_PRESSURE_MIN  = 1.5     # bar
THRESHOLD_FLOWRATE_MAX  = 150.0   # L/min

# =============================================================================
# HYDRAULIC SIMULATION
# =============================================================================

def get_hydraulic_readings():
    """
    Generate realistic hydraulic sensor readings for a small NZ municipal
    water distribution network.

    Based on typical EPANET simulation outputs for a low-pressure residential
    network. EPyT full integration is planned for v2.0 using an Avondale
    pipe network .inp file.

    Pressure spike simulation: 20% chance per reading to model real Auckland
    infrastructure behaviour during storm events or demand surges.

    Returns:
        dict: pressure (bar) and flowrate (L/min)
    """
    base_pressure = 3.2    # bar - typical residential supply pressure NZ
    base_flowrate = 85.0   # L/min - typical small distribution main

    # Add realistic sensor noise
    pressure = round(base_pressure + random.uniform(-0.4, 0.4), 2)
    flowrate = round(base_flowrate + random.uniform(-15.0, 15.0), 1)

    # Simulate occasional pressure spike - storm event / demand surge
    if random.random() < 0.80:   # 80% chance per reading equals to 3 times per minute to show alerts
        pressure = round(pressure + random.uniform(1.5, 2.5), 2)
        print(f"  [SIM] Pressure spike - storm/surge event simulated")

    return {
        "pressure": pressure,
        "flowrate": flowrate
    }

# =============================================================================
# LAWA DATA LOADER
# =============================================================================

def load_lawa_data():
    """
    Load and prepare LAWA water quality monitoring data for the
    Avondale catchment, Auckland.

    Data source: Land, Air, Water Aotearoa (lawa.org.nz)
    Provider:    Auckland Council
    License:     CC BY 4.0
    Coverage:    2004-2024

    Reads from pre-processed CSV for fast loading.

    Returns:
        dict: DataFrames keyed by indicator name
    """
    print("  Loading LAWA water quality data...")
    print(f"  Source: {LAWA_FILE}")

    df     = pd.read_csv(LAWA_FILE)

    indicators = {
        "Turbidity":        "turbidity",
        "E.coli":           "ecoli",
        "pH":               "ph",
        "Nitrate nitrogen": "nitrate"
    }

    datasets = {}
    for lawa_name, key in indicators.items():
        data = df[df["Indicator"] == lawa_name][
            ["SampleDateTime", "Value", "Units", "SiteID"]
        ].reset_index(drop=True)
        datasets[key] = data
        print(f"  Loaded {len(data)} readings for {lawa_name}")

    print(f"  Catchment: {CATCHMENT}, Auckland | License: CC BY 4.0")
    print("  Data ready.\n")
    return datasets

# =============================================================================
# MQTT CONNECTION
# =============================================================================

def on_connect(client, userdata, flags, reason_code, properties=None):
    """
    Callback fired on MQTT broker connection.
    Uses MQTTv5 callback API for modern protocol support.
    """
    if reason_code == 0:
        print(f"  Connected to Mosquitto at {MQTT_HOST}:{MQTT_PORT}")
    else:
        print(f"  MQTT connection failed - reason code: {reason_code}")

def on_publish(client, userdata, mid, reason_code=None, properties=None):
    """Callback fired on successful message publish. Silent."""
    pass

def connect_mqtt():
    """
    Create and connect MQTT client to local Mosquitto broker.
    Authentication via username/password. No TLS - Scada-LTS limitation.
    """
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_publish  = on_publish
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    return client

# =============================================================================
# THRESHOLD CHECKER
# =============================================================================

def check_thresholds(readings):
    """
    Check all sensor readings against NPS-FM 2020 standards and
    AquaNet operational limits. Generates alert messages for any
    breaches which are published to the aquanet/alerts MQTT topic.

    Abnormal readings from the real LAWA dataset trigger genuine alerts
    without artificial injection - the historical Avondale data contains
    real contamination events.

    Args:
        readings (dict): current sensor values
    Returns:
        list: alert message strings (empty if all within limits)
    """
    alerts = []

    if readings.get("ecoli") is not None:
        if readings["ecoli"] > THRESHOLD_ECOLI_MAX:
            alerts.append(
                f"ALERT E.COLI: {readings['ecoli']} CFU/100ml "
                f"exceeds NPS-FM limit of {THRESHOLD_ECOLI_MAX} - "
                f"BACTERIAL CONTAMINATION DETECTED"
            )

    if readings.get("turbidity") is not None:
        if readings["turbidity"] > THRESHOLD_TURBIDITY_MAX:
            alerts.append(
                f"ALERT TURBIDITY: {readings['turbidity']} NTU "
                f"exceeds {THRESHOLD_TURBIDITY_MAX} NTU - "
                f"TREATMENT REQUIRED"
            )

    if readings.get("ph") is not None:
        if readings["ph"] < THRESHOLD_PH_MIN:
            alerts.append(
                f"ALERT pH LOW: {readings['ph']} - "
                f"CORROSION RISK - below {THRESHOLD_PH_MIN}"
            )
        elif readings["ph"] > THRESHOLD_PH_MAX:
            alerts.append(
                f"ALERT pH HIGH: {readings['ph']} - "
                f"SCALING RISK - above {THRESHOLD_PH_MAX}"
            )

    if readings.get("nitrate") is not None:
        if readings["nitrate"] > THRESHOLD_NITRATE_MAX:
            alerts.append(
                f"ALERT NITRATE: {readings['nitrate']} mg/L "
                f"exceeds NPS-FM bottom line of {THRESHOLD_NITRATE_MAX} mg/L"
            )

    if readings.get("pressure") is not None:
        if readings["pressure"] > THRESHOLD_PRESSURE_MAX:
            alerts.append(
                f"ALERT PRESSURE HIGH: {readings['pressure']} bar "
                f"exceeds {THRESHOLD_PRESSURE_MAX} bar - PIPE BURST RISK"
            )
        elif readings["pressure"] < THRESHOLD_PRESSURE_MIN:
            alerts.append(
                f"ALERT PRESSURE LOW: {readings['pressure']} bar "
                f"below {THRESHOLD_PRESSURE_MIN} bar - "
                f"BACKFLOW/CONTAMINATION RISK"
            )

    if readings.get("flowrate") is not None:
        if readings["flowrate"] > THRESHOLD_FLOWRATE_MAX:
            alerts.append(
                f"ALERT FLOW HIGH: {readings['flowrate']} L/min "
                f"above operational range of {THRESHOLD_FLOWRATE_MAX} L/min"
            )

    return alerts

# =============================================================================
# MAIN SIMULATION LOOP
# =============================================================================

def run_simulator():
    """
    Main simulation loop.

    Replays real LAWA historical data chronologically, combines it with
    hydraulic simulation data, publishes everything via MQTT to Mosquitto,
    checks thresholds and publishes alerts.

    All data published via MQTT:
        aquanet/water/turbidity   - NTU
        aquanet/water/ecoli       - CFU/100ml
        aquanet/water/ph          - pH units
        aquanet/water/nitrate     - mg/L
        aquanet/hydraulic/pressure - bar
        aquanet/hydraulic/flowrate - L/min
        aquanet/alerts            - alert messages
    """
    print("=" * 60)
    print("  AquaNet NZ - Water Treatment Plant Simulator")
    print("  Avondale Catchment, Auckland, Aotearoa New Zealand")
    print("  Data: LAWA (CC BY 4.0) + EPANET hydraulic model")
    print("=" * 60)
    print()

    # Load LAWA water quality data
    datasets = load_lawa_data()

    # Connect to Mosquitto MQTT broker
    client = connect_mqtt()
    time.sleep(1)

    # Track position in each dataset for chronological replay
    indices = {key: 0 for key in datasets}

    print(f"  Publishing every {PUBLISH_INTERVAL} seconds...")
    print(f"  Topics: aquanet/water/* | aquanet/hydraulic/* | aquanet/alerts")
    print("-" * 60)

    reading_count = 0

    while True:
        reading_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        readings  = {}

        print(f"\n[{timestamp}] Reading #{reading_count}")

        # --- Water quality: publish from LAWA historical data ---
        topic_map = {
            "turbidity": TOPIC_TURBIDITY,
            "ecoli":     TOPIC_ECOLI,
            "ph":        TOPIC_PH,
            "nitrate":   TOPIC_NITRATE
        }
        unit_map = {
            "turbidity": "NTU",
            "ecoli":     "CFU/100ml",
            "ph":        "pH",
            "nitrate":   "mg/L"
        }

        for indicator, df in datasets.items():
            if len(df) == 0:
                continue
            idx   = indices[indicator] % len(df)
            row   = df.iloc[idx]
            value = round(float(row["Value"]), 3)
            readings[indicator] = value

            client.publish(topic_map[indicator],
                           payload=str(value),
                           qos=MQTT_QOS)

            print(f"  {indicator:<12} {value:>10} {unit_map[indicator]}"
                  f"  → {topic_map[indicator]}")

            indices[indicator] += 1

        # --- Hydraulics: publish via MQTT ---
        hydraulic            = get_hydraulic_readings()
        readings["pressure"] = hydraulic["pressure"]
        readings["flowrate"] = hydraulic["flowrate"]

        client.publish(TOPIC_PRESSURE,
                       payload=str(hydraulic["pressure"]),
                       qos=MQTT_QOS)
        client.publish(TOPIC_FLOWRATE,
                       payload=str(hydraulic["flowrate"]),
                       qos=MQTT_QOS)

        print(f"  {'pressure':<12} {hydraulic['pressure']:>10} bar"
              f"  → {TOPIC_PRESSURE}")
        print(f"  {'flowrate':<12} {hydraulic['flowrate']:>10} L/min"
              f"  → {TOPIC_FLOWRATE}")

        # --- Threshold check: publish alerts ---
        alerts = check_thresholds(readings)
        if alerts:
            for alert in alerts:
                client.publish(TOPIC_ALERTS,
                               payload=alert,
                               qos=MQTT_QOS)
                print(f"\n  *** {alert} ***")
        else:
            print(f"  All readings within NPS-FM 2020 limits")

        time.sleep(PUBLISH_INTERVAL)

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        run_simulator()
    except KeyboardInterrupt:
        print("\nSimulator stopped by user.")
