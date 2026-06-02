import pandas as pd
import numpy as np
from simulator.generate_normal import generate_normal

def inject_soiling(df: pd.DataFrame, severity: float = 0.3,
                   start_day: int = 5, duration_days: int = 10) -> pd.DataFrame:
    # pr turun gradual krn soiling (kotor)
    df = df.copy()
    start_idx = start_day * 288   # 288 = rows per hari (5 menit)
    for i in range(duration_days * 288):
        idx = start_idx + i
        if idx >= len(df): break
        progress = i / (duration_days * 288)
        factor = 1 - severity * progress
        df.at[idx, "power_kw"] *= factor
        df.at[idx, "pr"] = (df.at[idx, "pr"] or 0) * factor if df.at[idx, "pr"] else None
    return df

def inject_shading(df: pd.DataFrame, string_id: str = "string_1_v",
                   drop_pct: float = 0.4, start_idx: int = 500,
                   duration: int = 36) -> pd.DataFrame:
    """Voltage drop tiba-tiba di satu string (pohon, objek bayangan)."""
    df = df.copy()
    for i in range(duration):
        idx = start_idx + i
        if idx >= len(df): break
        df.at[idx, string_id] *= (1 - drop_pct)
        df.at[idx, "power_kw"] *= (1 - drop_pct * 0.25)
    return df

def inject_inverter_fault(df: pd.DataFrame, start_idx: int = 1000,
                          duration: int = 12) -> pd.DataFrame:
    # output drop ke ~0 mendadak (inverter trip).
    df = df.copy()
    for i in range(duration):
        idx = start_idx + i
        if idx >= len(df): break
        df.at[idx, "power_kw"] = 0.0
        df.at[idx, "current_a"] = 0.0
        df.at[idx, "pr"] = 0.0
    return df

def inject_degradation(df: pd.DataFrame,
                        annual_rate: float = 0.007) -> pd.DataFrame:
    """Degradasi lambat 0.7%/tahun (disimulasikan lebih cepat)."""
    df = df.copy()
    daily_rate = annual_rate / 365
    for i, row in df.iterrows():
        day = i // 288
        df.at[i, "power_kw"] *= (1 - daily_rate * day)
    return df

INJECTORS = {
    "soiling":         inject_soiling,
    "shading":         inject_shading,
    "inverter_fault":  inject_inverter_fault,
    "degradation":     inject_degradation,
}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--type",     choices=INJECTORS.keys(), required=True)
    p.add_argument("--severity", type=float, default=0.3)
    p.add_argument("--output",   default="data/raw/anomaly.csv")
    args = p.parse_args()

    df_normal = generate_normal(days=30)
    fn = INJECTORS[args.type]
    df_anomaly = fn(df_normal, severity=args.severity) \
                 if "severity" in fn.__code__.co_varnames \
                 else fn(df_normal)

    df_anomaly.to_csv(args.output, index=False)
    print(f"Injected {args.type} → {args.output}")