"""
Step 5 - independent reality check on the telemetry data (different instruments, 2023-2025, never trained on).

For many 'today' dates per telemetry station we give the model ONLY quarterly-style history (readings ~91 days
apart, exactly like the training data), ask for +30/+60/+90 days, and compare with what the sensor really
recorded. Baselines: persistence, and 'what changed over the same window last year at this station'.

  python validate_telemetry.py
"""
import json
import numpy as np
import pandas as pd
import torch
from config import CFG
from features import (RainIndex, used_gauges, neighbors, point_normals, static_row, tok_matrix, rain_feats,
                      ctx_vec, rain_windows_for, to_day, doy)
from model import GWNet

HORIZONS = (30, 60, 90)


def nearest(D, L, day, tol):
    i = np.searchsorted(D, day)
    c = [k for k in (i - 1, i) if 0 <= k < len(D) and abs(D[k] - day) <= tol]
    if not c:
        return None
    k = min(c, key=lambda k: abs(D[k] - day))
    return int(D[k]), float(L[k])


def main(stride=15):
    art = CFG.art_dir
    sc = json.load(open(art / "scalers.json"))
    net = GWNet(**json.load(open(art / "model_cfg.json")))
    net.load_state_dict(torch.load(art / "model.pt", map_location="cpu")); net.eval()
    tobs = pd.read_parquet(CFG.proc_dir / "tele_obs.parquet")
    tmeta = pd.read_parquet(CFG.proc_dir / "tele_meta.parquet").reset_index(drop=True)
    rlong, rmeta = pd.read_parquet(CFG.proc_dir / "rain_long.parquet"), pd.read_parquet(CFG.proc_dir / "rain_meta.parquet")
    used = used_gauges(tmeta.lat.values, tmeta.lon.values, rmeta)
    ri = RainIndex(rlong[rlong.gauge.isin(used)], rmeta[rmeta.gauge.isin(used)]) if used else None
    nbs = [neighbors(la, lo, ri.glat, ri.glon) if ri else (np.array([], int), np.array([])) for la, lo in zip(tmeta.lat, tmeta.lon)]
    normals = point_normals(tmeta.lat.values, tmeta.lon.values, ri, ri.gauge_normals()) if ri else \
        np.full((len(tmeta), len(CFG.rain_windows), 365), np.nan, np.float32)

    rows, T, S, C = [], [], [], []
    for si, st in enumerate(tmeta.station):
        g = tobs[tobs.station == st].sort_values("date")
        if len(g) < 200:
            continue
        D, L = to_day(g.date.values), g.level.values.astype(float)
        stat = static_row(tmeta.lat[si], tmeta.lon[si], None, "unknown", "unknown", sc)
        for a in range(0, len(D), stride):
            as_of = int(D[a])
            toks = [nearest(D, L, as_of - 91 * k, 3) for k in range(CFG.K)]
            toks = [t for t in toks[::-1] if t is not None]
            if len(toks) < CFG.min_tokens or toks[-1][0] != as_of:
                continue
            td, tl = np.array([t[0] for t in toks]), np.array([t[1] for t in toks])
            a0 = nearest(D, L, as_of - 365, 2)
            for h in HORIZONS:
                tgt = nearest(D, L, as_of + h, 1)
                if tgt is None:
                    continue
                ly = nearest(D, L, as_of - 365 + h, 2) if a0 else None
                wins = rain_windows_for(ri, nbs[si], as_of)
                T.append(tok_matrix(td, tl, as_of, sc)); S.append(stat)
                C.append(ctx_vec(as_of, h, rain_feats(wins, normals[si][:, int(doy(np.array([as_of]))[0]) - 1])))
                rows.append({"h": h, "y": tgt[1] - tl[-1], "analog": (ly[1] - a0[1]) if (a0 and ly) else np.nan})
    if not rows:
        raise SystemExit("No usable telemetry windows (need >= 3 quarterly-spaced observations before 'today').")
    with torch.no_grad():
        P = net(torch.from_numpy(np.stack(T)), torch.from_numpy(np.stack(S)), torch.from_numpy(np.stack(C))).numpy() * sc["y_scale"]
    df = pd.DataFrame(rows)
    out = {"n_windows": int(len(df)), "stations": int(tmeta.shape[0])}
    for h in HORIZONS:
        m = (df.h == h).values
        if m.sum() < 20:
            continue
        y, p = df.y.values[m], P[m]
        r = {"n": int(m.sum()), "MAE_model_m": round(float(np.abs(p[:, 1] - y).mean()), 3),
             "MAE_persistence_m": round(float(np.abs(y).mean()), 3),
             "P10_P90_coverage": round(float(((y >= p[:, 0]) & (y <= p[:, 2])).mean()), 3)}
        a = ~np.isnan(df.analog.values[m])
        if a.sum() >= 20:
            r["subset_with_last_year_analog"] = {"n": int(a.sum()), "MAE_model_m": round(float(np.abs(p[a, 1] - y[a]).mean()), 3),
                                                 "MAE_last_year_analog_m": round(float(np.abs(df.analog.values[m][a] - y[a]).mean()), 3)}
        out[f"+{h}d"] = r
    print(json.dumps(out, indent=1))
    json.dump(out, open(art / "metrics_telemetry.json", "w"), indent=1)


if __name__ == "__main__":
    main()
