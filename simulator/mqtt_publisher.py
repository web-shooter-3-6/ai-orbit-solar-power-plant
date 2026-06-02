import paho.mqtt.client as mqtt
import pandas as pd
import json, time, argparse, yaml

def publish(csv_path: str, speed: int = 1,
            broker: str = "localhost", plant_id: str = "plant_001"):
    client = mqtt.Client()
    client.connect(broker, 1883)

    df = pd.read_csv(csv_path)
    topic = f"solar/{plant_id}/inverter/inv-01/data"

    print(f"Publishing {len(df)} rows at {speed}x speed...")
    for _, row in df.iterrows():
        payload = row.to_dict()
        payload["timestamp"] = str(payload["timestamp"])

        client.publish(topic, json.dumps(payload))
        print(f"  → power={payload.get('power_kw',0):.2f} kW | "
              f"PR={payload.get('pr',0):.3f} | "
              f"irr={payload.get('irradiance',0):.0f} W/m²")

        # interval 5 menit data, dibagi speed
        time.sleep(5 * 60 / speed)

    client.disconnect()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv",      required=True)
    p.add_argument("--speed",    type=int, default=60)
    p.add_argument("--broker",   default="localhost")
    p.add_argument("--plant-id", default="plant_001")
    args = p.parse_args()
    publish(args.csv, args.speed, args.broker, args.plant_id)