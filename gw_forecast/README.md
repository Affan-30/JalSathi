# Groundwater Forecast Service v2 (no synthetic data anywhere in this project)

## Data -> role
| Dataset | Role |
|---|---|
| Quarterly manual GWL 1970-2025 | **Main training data** (irregular-time LSTM) + per-well history for scoring |
| Rainfall 1961-1990 (+ your 2022-2025 gauges, same schema) | rain->recharge learning where it overlaps (1970-90, 2022-25) and **per-location rainfall normals** |
| Telemetry 2023-2025 | **independent validation only** (`validate_telemetry.py`), never trained on |
| IMD (fetched by Node) | observed recent rain + 5-day forecast, sent with every request |

## Run
    pip install -r requirements.txt
    python data_prep.py --wells data/raw/wells.csv --rain data/raw/rain_1961_1990.csv data/raw/rain_2022_2025.csv --telemetry data/raw/telemetry.csv
    python train.py --mode eval          # read the baselines table before trusting anything
    python validate_telemetry.py         # independent check on a different instrument
    python train.py --mode final         # retrain on all data for deployment
    uvicorn api:app --port 8000          # Node: see node_integration/

Set `dayfirst` in config.py if your dates look like 25-10-2024. Set GW_HOME to keep data/artifacts elsewhere.
Read the rainfall audit printed by data_prep (are 0 mm days recorded, or only rainy days?).
Depth = metres below ground level (bigger = deeper = worse).
Thresholds/weights in config.py + scoring.py are policy choices - agree them with a hydrogeologist.

## Getting a report for a location
    curl "http://localhost:8000/v1/forecast/quick?lat=18.52&lon=73.85"        # quick test (no IMD input)
    POST /v1/forecast  {lat, lon, rain:[{date,mm}], recent_levels:{...}, horizons:[15,30,45,60,75,90]}   # production
Returns: point report (blend of nearest wells), `trend` (movement + vs seasonal norm), `recognized_area`
(district/block/village of the nearest well) and `area_report` (block or district roll-up, worst/best well).
POST /v1/forecast/area {district, block?} gives a roll-up for a named area.