import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def irradiance_curve(hour: float) -> float:
    # bell curve dari jam 6 pagi sampai 6 sore.
    if hour < 6 or hour > 18:
        return 0.0
    peak = 1000  # W/m² maksimum
    return peak * np.sin(np.pi * (hour - 6) / 12) ** 2

def generate_normal(
    days: int = 90,
    interval_min: int = 5,
    n_strings: int = 4,
    panel_area_m2: float = 200,
    efficiency: float = 0.18,
    noise_std: float = 0.02,
    plant_id: str = "plant_001"
) -> pd.DataFrame:
    rows = []
    start = datetime(2025, 1, 1, 6, 0)
    steps = int(days * 24 * 60 / interval_min)

    for i in range(steps):
        ts = start + timedelta(minutes=i * interval_min)
        hour = ts.hour + ts.minute / 60
        irr = irradiance_curve(hour)

        # tambah noise harian dan variasi awan kecil
        irr *= (1 + np.random.normal(0, noise_std))
        irr = max(0, irr)

        temp_ambient = 25 + 10 * np.sin(np.pi * (hour - 6) / 12)
        temp_module  = temp_ambient + 0.03 * irr

        # power = irradiance * area * efficiency * temp correction
        temp_coeff = 1 - 0.004 * max(0, temp_module - 25)
        power_kw   = irr * panel_area_m2 * efficiency * temp_coeff / 1000
        power_kw  *= (1 + np.random.normal(0, noise_std))
        power_kw   = max(0, power_kw)

        pr = power_kw / (irr * panel_area_m2 / 1000) if irr > 10 else None

        # string voltages (sedikit variasi antar string)
        strings = {
            f"string_{j+1}_v": 400 * (1 + np.random.normal(0, 0.005))
            for j in range(n_strings)
        }

        rows.append({
            "timestamp": ts,
            "plant_id":  plant_id,
            "irradiance": round(irr, 2),
            "temp_ambient": round(temp_ambient, 2),
            "temp_module":  round(temp_module, 2),
            "power_kw":     round(power_kw, 4),
            "voltage_v":    round(np.mean(list(strings.values())), 2),
            "current_a":    round(power_kw * 1000 / 400, 3) if power_kw > 0 else 0,
            "pr":           round(pr, 4) if pr else None,
            **{k: round(v, 2) for k, v in strings.items()}
        })

    return pd.DataFrame(rows)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days",   type=int, default=90)
    p.add_argument("--output", type=str, default="data/raw/normal.csv")
    args = p.parse_args()

    df = generate_normal(days=args.days)
    df.to_csv(args.output, index=False)
    print(f"Generated {len(df)} rows → {args.output}")