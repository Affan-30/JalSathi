"""Every tunable lives here. Values below are *policy / modelling parameters*, not data."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent
HOME = Path(os.getenv("GW_HOME", ROOT))          # where data/ and artifacts/ live


@dataclass
class Config:
    proc_dir: Path = HOME / "data" / "processed"
    art_dir: Path = HOME / "artifacts"

    # ---------- cleaning (rows are DROPPED, never repaired or invented) ----------
    dayfirst: bool = False                 # True if dates look like 25-10-2024
    gw_min: float = -5.0                   # m bgl
    gw_max: float = 200.0
    well_depth_tol: float = 1.0            # reading deeper than well bottom + tol is physically impossible
    bbox: tuple = (6.0, 38.0, 68.0, 98.0)  # lat_min, lat_max, lon_min, lon_max sanity box (catches swapped/zero coords)
    rain_max_mm: float = 500.0
    rain_missing_means_zero: bool = False  # ONLY set True if you confirm gauges list rainy days only (see audit)

    # ---------- rainfall features ----------
    rain_k: int = 6                        # nearest gauges considered ...
    rain_max_km: float = 50.0              # ... within this radius
    rain_min_cov: float = 0.8              # a window counts only if >=80% of its days were actually reported
    rain_windows: tuple = (30, 90, 180)
    normals_era: tuple = (1961, 1990)
    normals_min_years: int = 10

    # ---------- sequence / query ----------
    K: int = 12                            # last 12 readings (~3 yrs of quarterly data)
    min_tokens: int = 3
    min_h: int = 20                        # forecast distance range seen in training (days)
    max_h: int = 200
    max_stale_aug: int = 120               # training randomises "today" up to this many days after the last reading

    # ---------- model / training ----------
    hidden: int = 96
    layers: int = 2
    dropout: float = 0.2
    quantiles: tuple = (0.1, 0.5, 0.9)
    batch: int = 512
    epochs: int = 40
    lr: float = 2e-3
    patience: int = 6
    max_train_pairs: int = 600_000
    seed: int = 42
    train_end: str = "2018-12-31"          # eval mode: train on targets <= this
    val_end: str = "2021-12-31"            # validation; TEST = origins after this (2022-2025, has rain)
    holdout_frac: float = 0.10             # wells never seen in training (tests generalisation to new locations)

    # ---------- scoring ----------
    stale_days: int = 150                  # > 1 missed quarterly round => STALE_DATA
    max_usable_stale_days: int = 400       # wells whose newest reading is older than this are NOT used for a forecast
    stale_conf_factor: float = 0.6         # heuristic confidence haircut when stale
    depth_curve: tuple = ((0, 85), (3, 100), (5, 92), (10, 72), (15, 52), (20, 32), (30, 12), (40, 0))


CFG = Config()