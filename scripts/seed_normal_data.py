from simulator.generate_normal import generate_normal
from ingestion.db_writer import batch_write

print("Generating 90 days normal data...")
df = generate_normal(days=90)
batch_write(df)
print(f"Seeded {len(df):,} rows to TimescaleDB")