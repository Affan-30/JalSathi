"""
Step 7 - inference core. Stateless w.r.t. rain/new readings: the caller (Node.js) passes them in each request.
"""
import json
import numpy as np
import pandas as pd
import torch
from config import CFG
from features import (static_row, tok_matrix, rain_feats, ctx_vec, to_day, from_day, doy, haversine)
from model import GWNet
from scoring import score_horizon


class Forecaster:
    def __init__(self, art=None):
        art = art or CFG.art_dir
        self.sc = json.load(open(art / "scalers.json"))
        self.net = GWNet(**json.load(open(art / "model_cfg.json")))
        self.net.load_state_dict(torch.load(art / "model.pt", map_location="cpu")); self.net.eval()
        self.wells = pd.read_parquet(art / "wells_static.parquet").reset_index(drop=True)
        self.normals = np.load(art / "normals.npy")
        obs = pd.read_parquet(art / "wells_obs.parquet").sort_values(["well_id", "date"])
        self.obs = {w: dict(zip(to_day(g.date.values).tolist(), g.level.tolist())) for w, g in obs.groupby("well_id")}
        self.idx = {w: i for i, w in enumerate(self.wells.well_id)}
        self.static = np.stack([static_row(r.lat, r.lon, r.depth, r.aquifer, r.well_type, self.sc) for r in self.wells.itertuples()])

    # ---- geography
    def nearby(self, lat, lon, k=3, max_km=40.0):
        d = haversine(lat, lon, self.wells.lat.values, self.wells.lon.values)
        return [(int(i), float(d[i])) for i in np.argsort(d)[:k] if d[i] <= max_km]

    # ---- history = stored readings + newer readings supplied by the caller (caller wins on same day)
    def _series(self, well_id, extra=None):
        m = dict(self.obs.get(well_id, {}))
        for date, lv in (extra or []):
            m[int(to_day(np.datetime64(str(date)[:10])))] = float(lv)
        D = np.array(sorted(m), dtype="int64")
        return D, np.array([m[d] for d in D])

    def _rain(self, rain, as_of):
        if not rain:
            return [None] * len(CFG.rain_windows)
        rd = np.array(sorted({int(to_day(np.datetime64(str(d)[:10]))): float(mm) for d, mm in rain}.items()))
        days, mm = rd[:, 0].astype("int64"), rd[:, 1]
        out = []
        for W in CFG.rain_windows:
            m = (days > as_of - W) & (days <= as_of)
            cov = m.sum() / W
            out.append((float(mm[m].sum()), float(cov)) if cov >= CFG.rain_min_cov else None)
        return out

    def forecast_well(self, wi, as_of, rain=None, extra=None, horizons=(30, 60, 90)):
        row = self.wells.iloc[wi]
        D, L = self._series(row.well_id, extra)
        keep = D <= as_of
        D, L = D[keep], L[keep]
        if len(D) < 2:
            raise ValueError(f"well {row.well_id}: fewer than 2 readings on/before {from_day(as_of)}")
        wins = self._rain(rain, as_of)
        nrm = self.normals[wi][:, int(doy(np.array([as_of]))[0]) - 1]
        rf = rain_feats(wins, nrm)
        tok = np.repeat(tok_matrix(D, L, as_of, self.sc)[None], len(horizons), 0)
        ctx = np.stack([ctx_vec(as_of, h, rf) for h in horizons])
        with torch.no_grad():
            q = self.net(torch.from_numpy(tok), torch.from_numpy(np.repeat(self.static[wi][None], len(horizons), 0)),
                         torch.from_numpy(ctx)).numpy() * self.sc["y_scale"]
        absq = np.clip(L[-1] + q, 0, None)
        return {"well_id": row.well_id, "row": row, "D": D, "L": L, "as_of": as_of, "has_rain": any(w is not None for w in wins),
                "horizons": {h: {"p10": absq[k, 0], "p50": absq[k, 1], "p90": absq[k, 2]} for k, h in enumerate(horizons)}}

    # ---- context for scoring (from the well's own history)
    @staticmethod
    def seasonal_hist(D, L, target_day):
        dd = (doy(D) - int(doy(np.array([target_day]))[0]) + 182) % 365 - 182
        return L[np.abs(dd) <= 45]

    @staticmethod
    def longterm_slope(D, L):
        yrs = from_day(D).astype("datetime64[Y]").astype(int) + 1970
        df = pd.DataFrame({"y": yrs, "l": L})
        df = df[df.y >= yrs.max() - 14]
        g = df.groupby("y").l.agg(["mean", "count"])
        g = g[g["count"] >= 3]
        if len(g) < 8:
            return None
        return float(np.polyfit(g.index.values, g["mean"].values, 1)[0])

    @staticmethod
    def trend_summary(series):
        """series: [{days,p50,seasonal_median,...}] sorted by days. Thresholds (0.3 m / 0.5 m) are policy values."""
        move = series[-1]["p50"] - series[0]["p50"]
        sm = series[-1].get("seasonal_median")
        vs = None if sm is None else round(series[-1]["p50"] - sm, 2)
        return {"series": series, "movement_m": round(move, 2),
                "movement": "DEEPENING" if move > 0.3 else "RECOVERING" if move < -0.3 else "STABLE",
                "vs_seasonal_norm_m": vs,
                "position_vs_norm": None if vs is None else "DEEPER_THAN_USUAL" if vs > 0.5 else
                "SHALLOWER_THAN_USUAL" if vs < -0.5 else "NEAR_USUAL"}

    def area_wells(self, district=None, block=None):
        m = np.ones(len(self.wells), bool)
        if district:
            m &= (self.wells.district.fillna("").str.lower() == district.lower()).values
        if block:
            m &= (self.wells.block.fillna("").str.lower() == block.lower()).values
        return np.flatnonzero(m)

    def report(self, wi, as_of_date, rain=None, extra=None, imd_5d_mm=None, horizons=(30, 60, 90)):
        as_of = int(to_day(np.datetime64(str(as_of_date)[:10])))
        f = self.forecast_well(wi, as_of, rain, extra, tuple(sorted(set(horizons))))
        D, L, row = f["D"], f["L"], f["row"]
        stale_days = int(as_of - D[-1])
        stale = stale_days > CFG.stale_days
        lt = self.longterm_slope(D, L)
        out = {}
        for h, q in f["horizons"].items():
            sc = score_horizon(h, stale_days + h, float(L[-1]), q, self.seasonal_hist(D, L, as_of + h), lt, stale, f["has_rain"])
            if imd_5d_mm is not None and imd_5d_mm >= 64.5:
                sc["reasons"].append("HEAVY_RAIN_EXPECTED")
            if stale_days > CFG.max_h:            # last reading older than anything seen in training
                sc["reasons"].append("BEYOND_TRAINING_RANGE")
            sc["target_date"] = str(from_day(as_of + h))
            out[str(h)] = sc
        series = []
        for h, q in sorted(f["horizons"].items()):
            sh = self.seasonal_hist(D, L, as_of + h)
            series.append({"days": h, "target_date": str(from_day(as_of + h)), "p10": round(float(q["p10"]), 2),
                           "p50": round(float(q["p50"]), 2), "p90": round(float(q["p90"]), 2),
                           "seasonal_median": round(float(np.median(sh)), 2) if len(sh) >= 8 else None})
        return {"well_id": f["well_id"], "trend": self.trend_summary(series),
                "location": {"lat": float(row.lat), "lon": float(row.lon),
                             **{k: row[k] for k in ("state", "district", "block", "village") if pd.notna(row[k])}},
                "as_of": str(from_day(as_of)), "last_reading": {"date": str(from_day(D[-1])), "depth_mbgl": round(float(L[-1]), 2)},
                "staleness_days": stale_days, "data_stale": stale, "long_term_trend_m_per_year": None if lt is None else round(lt, 2),
                "outlook": out}