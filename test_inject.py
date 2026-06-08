# test_inject.py di root repo
import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("localhost", 1883)

# Inject Battery Overheating
payload = {
    "timestamp": "2026-06-08 10:00:00",
    "pv_voltage": 437, "pv_current": 18,
    "pv_power_output": 7.5, "pv_panel_temperature": 38,
    "solar_irradiance": 700, "pv_efficiency": 93,
    "pv_ac_power": 7.2, "pv_inverter_temperature": 45,
    "pv_frequency": 50, "battery_soc": 10,
    "battery_soh": 85, "battery_voltage": 380,
    "battery_current": 45, "battery_temperature": 85,
    "battery_charge_rate": 95, "battery_discharge_rate": 0,
    "battery_internal_resistance": 0.04,
    "battery_cycle_count": 2500,
    "ev_charging_load": 40, "ev_charging_current": 60,
    "ev_charging_voltage": 410,
    "charging_station_temperature": 34,
    "active_ev_count": 12, "charging_duration": 45,
    "fast_charging_status": 1, "grid_voltage": 220,
    "grid_current": 85, "grid_frequency": 50,
    "power_demand": 120, "reactive_power": 40,
    "load_factor": 78, "energy_export": 35,
    "energy_import": 50, "power_factor": 0.94,
    "sensor_latency": 20, "packet_loss_rate": 1.5,
    "signal_strength": -60, "data_transmission_rate": 55,
    "edge_node_cpu_usage": 45, "cloud_response_time": 120,
    "dwt_coeff_a1": 0.5, "dwt_coeff_d1": 0.3,
    "dwt_coeff_d2": 0.15, "signal_energy": 80,
    "signal_entropy": 0.7, "rms_value": 45,
    "crest_factor": 3.5,
    "system_condition_label": "Battery_Overheating"
}

client.publish("solar/plant_001/inverter/inv-01/data", json.dumps(payload))
print("Injected Battery_Overheating anomaly!")
client.disconnect()