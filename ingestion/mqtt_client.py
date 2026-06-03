import paho.mqtt.client as mqtt
import json
from ingestion.db_writer import batch_write
from agent.guardrails import validate_input
import pandas as pd

BUFFER = []
BUFFER_SIZE = 10

def on_message(client, userdata, msg):
    global BUFFER
    try:
        data = json.loads(msg.payload)
        BUFFER.append(data)
        if len(BUFFER) >= BUFFER_SIZE:
            df = pd.DataFrame(BUFFER)
            df_clean, issues = validate_input(df)  # Guardrail 1
            if df_clean is not None and not df_clean.empty:
                batch_write(df_clean)
            BUFFER = []
    except Exception as e:
        print(f"[ingestion] error: {e}")

client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883)
client.subscribe("solar/+/+/+/data")
client.loop_forever()