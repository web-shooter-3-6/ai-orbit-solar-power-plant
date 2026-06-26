# ⚡ AI-ORBIT Solar Power Plant Anomaly Monitoring System

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-660066?logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#-license)

> An **agentic AI** web system for **real-time anomaly detection** on solar power plants — combining a 5-model machine-learning stack with a transparent rule-based safety layer, automated agent reasoning, live MQTT ingestion, and Telegram alerting.

<!-- screenshot dashboard -->
> 📸 *Replace with actual screenshot of the dashboard (Live Monitor / Realtime Feed page).*

---

## 📑 Table of Contents

- [✨ Features](#-features)
- [🚀 Quick Start](#-quick-start)
- [🏗️ Architecture](#️-architecture)
- [📂 Repository Structure](#-repository-structure)
- [📊 Dataset](#-dataset)
- [🤖 Models](#-models)
- [⚠️ Known Limitations](#️-known-limitations)
- [🧭 Ethical Considerations](#-ethical-considerations)
- [🤝 Contributing](#-contributing)
- [👥 Team & Context](#-team--context)
- [📜 License](#-license)

---

## ✨ Features

- **🔴 Live Monitor** — manually set 5 key sensors and run all 5 models instantly.
- **🟢 Realtime Feed** — streaming results from the MQTT → Agent pipeline, auto-refresh every 3 s.
- **📊 Statistics & Charts** — interactive Plotly charts: fault distribution, risk timeline, level breakdown, hourly anomaly heatmap.
- **📋 History** — searchable, color-coded anomaly log with CSV export.
- **🚀 Automated Demo** — runs 6 fault scenarios end-to-end in one click.
- **🧠 Two-layer risk scoring** — ML model votes + independent physical rule-based layer (works even when the dataset is weak).
- **🛡️ 3-layer guardrails** — input validation, score sanity checks, output filtering.
- **📨 Telegram alerts** — compact messages with per-level cooldown, retry + queue, and MEDIUM summaries to avoid rate limiting.
- **💾 TimescaleDB persistence** — dynamic sensor storage with CSV fallback when the DB is unavailable.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+** (Reflex frontend is developed on 3.14)
- **Docker Desktop** (optional — only for the legacy TimescaleDB / MQTT pipeline)
- Install dependencies (the project is configured for [uv](https://docs.astral.sh/uv/)):

```bash
# recommended — uses pyproject.toml + CPU-only torch index
uv sync

# or with pip
pip install -r ai_orbit_solar_power_plant/requirements.txt
```

<details>
<summary><b>📦 Detailed installation steps</b></summary>

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/ai-orbit-solar-power-plant.git
cd ai-orbit-solar-power-plant

# 2. (Recommended) create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / Mac
source .venv/bin/activate

# 3. Install Python dependencies
uv sync                                              # recommended
# or: pip install -r ai_orbit_solar_power_plant/requirements.txt

# 4. Configure environment variables
copy .env.example .env      # Windows
cp .env.example .env        # Linux / Mac
# then edit .env with your Telegram token, chat id, and DB password

# 5. (Optional) verify the risk-scoring logic
python tests/test_risk_score.py
```

> If the trained model files in `models/output/` are missing, run `python run_all_models.py` first.

</details>

### Environment Variables (`.env`)

```ini
# Storage
DB_PASSWORD=your_db_password                 # local TimescaleDB / Postgres
SUPABASE_DB_URL=postgresql://...             # cloud storage for Realtime Feed & History

# Telegram alerts (optional)
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ADMIN_TELEGRAM_ID_1=telegram_id_allowed_to_approve   # approve high-risk actions
ADMIN_TELEGRAM_ID_2=telegram_id_allowed_to_approve

# LLM agent (optional)
ANTHROPIC_API_KEY=optional_for_llm
```

> See `.env.example` for the full template. All Telegram functionality is **gracefully disabled** if the token/chat id are empty, and the cloud `SUPABASE_DB_URL` falls back to local file storage (`realtime_results.json`) when unset — the rest of the system keeps running.

### Run Modes

#### 🖥️ Mode 1 — Manual Dashboard
```bash
streamlit run dashboard.py
```

> **Two frontends:** the **Streamlit** dashboard (`dashboard.py`) is the primary UI and the one used in cloud deployment (`Procfile` / `railway.json`). The repo also ships a **Reflex** app under `ai_orbit_solar_power_plant/` (config in `rxconfig.py`) — run it with `reflex run`. Both consume the same agent/model layer.

#### 🎬 Mode 2 — Automated Demo
```bash
python scripts/run_demo.py
```

#### 📡 Mode 3 — Realtime Pipeline (no Docker, no MQTT)
```bash
# Terminal 1 — realtime simulator (reads dataset → agent → realtime_results.json)
python scripts/run_realtime.py

# Terminal 2 — dashboard (open the "Realtime Feed" page)
streamlit run dashboard.py
```

> The realtime feed now runs **MQTT-free** so it can be deployed to the cloud (e.g. **Railway**). `scripts/realtime_simulator.py` streams the dataset row-by-row directly into the agent. The legacy MQTT pipeline (`simulator/mqtt_publisher.py`, `ingestion/mqtt_client.py`) is kept for architecture reference but is no longer required.

<details>
<summary><b>☁️ Cloud deployment (Railway)</b></summary>

Deployment runs both processes from one start command (see `railway.json` / `Procfile`):

```bash
python scripts/realtime_simulator.py & streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0
```

The simulator runs in the background and continuously feeds `realtime_results.json`, which the dashboard reads on every refresh.

</details>

#### 🔁 Mode 4 — Retrain All Models
```bash
python run_all_models.py
```

---

## 🏗️ Architecture

```
                         Sensor Data
                              │  MQTT
                              ▼
                      Ingestion Pipeline
                              │
              ┌───────────────────────────────┐
              │  Guardrail 1: Input Validation │
              └───────────────────────────────┘
                              │
                      Multi-Model Stack
              ├── XGBoost          (supervised)
              ├── LSTM             (time-series)
              ├── Autoencoder      (reconstruction)
              ├── Isolation Forest (outlier)
              └── KMeans           (clustering)
                              │
              ┌───────────────────────────────┐
              │ Guardrail 2: Score Sanity Check│
              └───────────────────────────────┘
                              │
                         Agent Layer
              ├── anomaly_agent.py   (risk scoring)
              ├── decision_engine.py (recommendations)
              └── root_cause.py      (pattern detection)
                              │
              ┌───────────────────────────────┐
              │  Guardrail 3: Output Filter    │
              └───────────────────────────────┘
                              │
                            Output
              ├── Streamlit Dashboard
              ├── Telegram Alert
              └── History JSON
```

### Two-Layer Risk Scoring

| Layer | Source | Role |
|---|---|---|
| **Layer 1** | 5 ML models (votes / errors / distances) | Statistical anomaly signal |
| **Layer 2** | Physical sensor thresholds (rule-based) | Deterministic safety net — **independent of model quality** |

`final_risk = min(layer1 + layer2, 1.0)` → mapped to **LOW / MEDIUM / HIGH / CRITICAL**.

---

## 📂 Repository Structure

```
ai-orbit-solar/
├── agent/
│   ├── anomaly_agent.py      # Multi-model risk scoring
│   ├── decision_engine.py    # Fault explanation & recommendations
│   ├── root_cause.py         # Pattern detection & history
│   ├── guardrails.py         # Input validation
│   ├── orchestrator.py       # Agent orchestration
│   ├── aggregator.py         # Model vote aggregation
│   ├── drift_monitor.py      # Data / concept drift monitoring
│   ├── memory.py             # Agent memory
│   └── prompts.py            # LLM prompts
├── agent_memory/
│   └── history.json          # Analysis history
├── alert/
│   ├── telegram_alert.py     # Telegram notification (cooldown + retry + summary)
│   ├── telegram_bot.py       # Telegram approval bot
│   └── audit_log.py          # Action audit log
├── features/
│   └── engineer.py           # Feature engineering
├── ingestion/
│   ├── mqtt_client.py        # MQTT subscriber + agent pipeline (legacy)
│   └── db_writer.py          # TimescaleDB writer (CSV fallback)
├── models/
│   ├── preprocessing.py      # Data preprocessing
│   ├── train_xgboost.py      # XGBoost training
│   ├── autoencoder.py        # Autoencoder model
│   ├── isolation_forest.py   # Isolation Forest model
│   ├── kmeans.py             # KMeans clustering
│   ├── lstm.py               # LSTM model
│   ├── online_detector.py    # Online / incremental detector
│   ├── evaluate_models.py    # Model evaluation
│   └── output/               # Trained model files (.pkl, .pt)
├── simulator/
│   ├── mqtt_publisher.py     # Simulate sensor data via MQTT (legacy)
│   ├── generate_anomaly.py   # Anomaly data generator
│   └── generate_normal.py    # Normal data generator
├── scripts/
│   ├── run_demo.py           # End-to-end demo script
│   ├── run_realtime.py       # Realtime pipeline runner
│   ├── realtime_simulator.py # MQTT-free realtime feeder (used in deployment)
│   ├── train_models.py       # Train all models
│   ├── retrain.py            # Retrain on new data
│   ├── scheduled_tasks.py    # Background scheduled jobs
│   └── seed_normal_data.py   # Seed baseline normal data
├── tests/
│   ├── test_risk_score.py    # Risk score unit tests
│   ├── test_guardrails.py    # Guardrail tests
│   ├── test_memory.py        # Agent memory tests
│   ├── test_online_learning.py
│   ├── test_simulator.py
│   └── test_e2e.py           # End-to-end tests
├── data/
│   ├── Condition_Monitoring_Dataset.csv   # Training / eval dataset
│   └── Realtime_Test_Sequence.csv         # Realtime Feed demo sequence
├── ai_orbit_solar_power_plant/  # Reflex app (alternative frontend)
│   ├── ai_orbit_solar_power_plant.py      # Reflex app entrypoint (rx.App)
│   ├── pages/  components/  backend/       # UI pages, components, agent backend
│   ├── state.py                            # Reflex state
│   └── requirements.txt                    # pip dependency list
├── dashboard.py              # Streamlit web dashboard (primary UI)
├── run_all_models.py         # Train all models
├── rxconfig.py               # Reflex config
├── pyproject.toml            # Project metadata & dependencies (uv)
├── railway.json / Procfile   # Cloud deployment (Railway)
├── docker-compose.yml        # Docker services (legacy realtime stack)
├── mosquitto.conf            # MQTT broker config (legacy)
├── config.yaml               # System configuration
└── .env.example              # Environment variables template
```

---

## 📊 Dataset

| Property | Value |
|---|---|
| **Name** | Virtual Power Plant Monitoring Dataset |
| **Source** | Kaggle (programmer3) |
| **Type** | Synthetic |
| **Rows** | 50,000 |
| **Features** | 49 |
| **Classes** | 10 |

**Fault classes:** `Normal`, `PV_Fault`, `Battery_Degradation`, `Battery_Overheating`, `EV_Charging_Fault`, `Grid_Instability`, `Inverter_Fault`, `Communication_Failure`, `Overload_Condition`, `Sensor_Failure`.

> ⚠️ **Limitation:** the class labels are **not well correlated** with the raw sensor values (documented in the *Bias Analysis Report*). This is the root cause of the low supervised-model accuracy — and the reason the **rule-based layer exists**.

### Data untuk Realtime Feed

| File | Sumber | Tujuan |
|------|--------|--------|
| `Condition_Monitoring_Dataset.csv` | Kaggle (asli) | Training & evaluasi model |
| `Realtime_Test_Sequence.csv` | Simulasi/buatan | Demo Realtime Feed |

`Realtime_Test_Sequence.csv` (500 baris) dibuat khusus untuk **mendemonstrasikan respons sistem terhadap perubahan kondisi secara bertahap** (story arc: `Normal → PV_Fault → Normal → Battery_Overheating → Normal → Grid_Instability → Normal → Communication_Failure → Normal`), sehingga di Realtime Feed `risk_level` terlihat berganti-ganti (LOW → MEDIUM/HIGH/CRITICAL → LOW). File ini **TIDAK** dipakai untuk training maupun evaluasi model — evaluasi tetap memakai dataset asli `Condition_Monitoring_Dataset.csv` sesuai *Bias Analysis Report*. Kolomnya berkapital agar cocok dengan `FEATURE_ORDER`.

---

## 🤖 Models

| Model | Metric | Result |
|---|---|---|
| XGBoost | Accuracy | 45.3% |
| LSTM | Accuracy | 45.4% |
| Autoencoder | ROC-AUC | 0.496 |
| Isolation Forest | ROC-AUC | 0.500 |
| KMeans | ARI | 0.0004 |

> **Note:** the low scores are caused by the synthetic dataset's label/sensor mismatch — **not** by the implementation. The **rule-based layer operates independently** of dataset quality, so physical threshold breaches (e.g. `Battery_Temperature > 70°C`) are still detected reliably and verified by `tests/test_risk_score.py` (6/6 passing).

---

## ⚠️ Known Limitations

**Dataset**
- Labels are statistically uncorrelated with the raw sensor features.
- `Grid_Voltage` is ~230 V for *every* class; `Packet_Loss_Rate` is on a 0–7 scale (not 0–1) — so naïve thresholds had to be re-calibrated to the real data distribution.
- Fully synthetic — does not reflect real plant physics or seasonal patterns.

**Models**
- Supervised models (XGBoost, LSTM) cannot learn faults from this data → they default to predicting `Normal`.
- Unsupervised models (Autoencoder, KMeans, Isolation Forest) flag extreme inputs inconsistently.
- The system therefore **leans on the rule-based layer** for trustworthy risk scoring.

**System**
- `Inverter_Fault` has no dedicated rule (relies on models) — flagged correctly only in forced-demo mode.
- Telegram MEDIUM summaries are flushed on the next event after the 5-minute window (no background timer).
- TimescaleDB / Grafana require Docker; without it the system runs in file-fallback mode.

---

## 🧭 Ethical Considerations

- **Human-in-the-loop** — the AI is a decision-support tool, **not** an autonomous decision-maker.
- **Explainability** — every per-model prediction and rule trigger is shown in the dashboard.
- **Safety** — a 3-layer guardrail design (input → score → output) protects the pipeline.
- **Transparency** — dataset bias and model weaknesses are documented openly rather than hidden.

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository and create a feature branch: `git checkout -b feature/your-feature`
2. Keep code comments and UI text consistent with the existing style.
3. Run `python tests/test_risk_score.py` and make sure all tests pass.
4. Commit with a clear message and open a Pull Request describing the change.

> Please **do not commit secrets** — keep credentials in `.env` (which is git-ignored) and update `.env.example` instead.

---

## 👥 Team & Context

- **Project type:** UAS (Final Exam Project)
- **Course:** Kecerdasan Buatan (Artificial Intelligence)
- **Institution:** Teknik Informatika, FMIPA, Universitas Padjadjaran
- **Year:** 2025

---

## 📜 License

This project is licensed under the **MIT License**.

```
MIT License — Copyright (c) 2025 AI-ORBIT Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, subject to the inclusion of the above copyright
notice and this permission notice in all copies.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

---

<div align="center">

**⚡ AI-ORBIT** — *Monitoring the sun, one anomaly at a time.*

</div>
