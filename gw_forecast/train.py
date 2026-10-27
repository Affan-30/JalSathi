"""
Step 4 - train + honest evaluation.

  python train.py --mode eval     # time-split + unseen-wells test; prints model vs baselines. DO THIS FIRST.
  python train.py --mode final    # retrain on ALL data for deployment (same #epochs as the eval run)

Test windows are 2022-2025 (rain available) and a 10% set of wells the model never saw.
"""
import argparse
import json
import shutil
import zlib
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset
from config import CFG
from features import (RainIndex, used_gauges, neighbors, point_normals, static_row, tok_matrix, rain_feats,
                      ctx_vec, rain_windows_for, to_day, doy, month0)
from model import GWNet, pinball

BINS = [(20, 60), (60, 100), (100, 140), (140, 201)]


def load():
    P = CFG.proc_dir
    return (pd.read_parquet(P / "wells_obs.parquet"), pd.read_parquet(P / "wells_meta.parquet"),
            pd.read_parquet(P / "rain_long.parquet"), pd.read_parquet(P / "rain_meta.parquet"))


def enum_pairs(series):
    """Every (origin reading i, later reading j) whose gap is 20..200 days."""
    W, I, J, DI, DJ = [], [], [], [], []
    for w, (D, L) in enumerate(series):
        n = len(D)
        if n <= CFG.min_tokens:
            continue
        lo, hi = np.searchsorted(D, D + CFG.min_h, "left"), np.searchsorted(D, D + CFG.max_h, "right")
        for i in range(CFG.min_tokens - 1, n):
            for j in range(lo[i], hi[i]):
                W.append(w); I.append(i); J.append(j); DI.append(D[i]); DJ.append(D[j])
    return tuple(np.array(a) for a in (W, I, J, DI, DJ))


def materialize(sel, P, series, static, ri, nbs, normals, sc, rng, aug):
    """Pairs -> model-ready arrays. aug=True adds a second copy with a random 'today' between the two readings."""
    T, S, C, Y, H, W_, MO, MT = [], [], [], [], [], [], [], []
    W, I, J, DI, DJ = P
    for p in sel:
        w, i, j = W[p], I[p], J[p]
        D, L = series[w]
        s_opts = [0]
        if aug:
            room = min(DJ[p] - DI[p] - CFG.min_h, CFG.max_stale_aug)
            if room >= 5:
                s_opts.append(int(rng.integers(1, room + 1)))
        for s in s_opts:
            as_of = int(D[i] + s)
            h = int(D[j] - as_of)
            wins = rain_windows_for(ri, nbs[w], as_of)
            nrm = normals[w][:, int(doy(np.array([as_of]))[0]) - 1]
            T.append(tok_matrix(D[:i + 1], L[:i + 1], as_of, sc)); S.append(static[w])
            C.append(ctx_vec(as_of, h, rain_feats(wins, nrm)))
            Y.append(L[j] - L[i]); H.append(h); W_.append(w)
            MO.append(int(month0(np.array([D[i]]))[0])); MT.append(int(month0(np.array([D[j]]))[0]))
    return {"tok": np.stack(T), "static": np.stack(S), "ctx": np.stack(C), "y": np.array(Y, np.float32),
            "h": np.array(H), "w": np.array(W_), "mo": np.array(MO), "mt": np.array(MT)}


def tens(d, ys):
    return TensorDataset(torch.from_numpy(d["tok"]), torch.from_numpy(d["static"]), torch.from_numpy(d["ctx"]),
                         torch.from_numpy(d["y"] / ys))


@torch.no_grad()
def predict(net, d, ys):
    net.eval()
    out = []
    for i in range(0, len(d["y"]), 4096):
        sl = slice(i, i + 4096)
        out.append(net(torch.from_numpy(d["tok"][sl]), torch.from_numpy(d["static"][sl]),
                       torch.from_numpy(d["ctx"][sl])).numpy() * ys)
    return np.concatenate(out)


def evaluate(net, d, ys, base_w, base_g):
    if d is None or len(d["y"]) == 0:
        return {"n": 0}
    P = predict(net, d, ys)
    idx3 = pd.MultiIndex.from_arrays([d["w"], d["mo"], d["mt"]])
    idx2 = pd.MultiIndex.from_arrays([d["mo"], d["mt"]])
    clim = base_w.reindex(idx3).values
    g = base_g.reindex(idx2).values
    clim = np.where(np.isnan(clim), np.where(np.isnan(g), 0.0, g), clim)
    res = {"n": int(len(d["y"]))}
    for lo, hi in BINS:
        m = (d["h"] >= lo) & (d["h"] < hi)
        if m.sum() < 20:
            continue
        y = d["y"][m]
        res[f"h{lo}-{hi - 1}d"] = {
            "n": int(m.sum()), "MAE_model_m": round(float(np.abs(P[m, 1] - y).mean()), 3),
            "MAE_persistence_m": round(float(np.abs(y).mean()), 3),
            "MAE_well_seasonal_climatology_m": round(float(np.abs(clim[m] - y).mean()), 3),
            "P10_P90_coverage": round(float(((y >= P[m, 0]) & (y <= P[m, 2])).mean()), 3)}
    return res


def run(mode):
    rng = np.random.default_rng(CFG.seed)
    torch.manual_seed(CFG.seed)
    CFG.art_dir.mkdir(parents=True, exist_ok=True)
    obs, meta, rlong, rmeta = load()
    meta = meta[meta.well_id.isin(obs.well_id)].reset_index(drop=True)
    wid = {w: i for i, w in enumerate(meta.well_id)}
    obs = obs.assign(w=obs.well_id.map(wid)).sort_values(["w", "date"])
    series = [(np.array([], "int64"), np.array([])) for _ in range(len(meta))]
    for w, g in obs.groupby("w"):
        series[int(w)] = (to_day(g.date.values), g.level.values.astype(float))

    # ---- rainfall index (only gauges near a well), per-well neighbours + normals
    used = used_gauges(meta.lat.values, meta.lon.values, rmeta)
    ri = RainIndex(rlong[rlong.gauge.isin(used)], rmeta[rmeta.gauge.isin(used)]) if used else None
    nbs = [neighbors(la, lo, ri.glat, ri.glon) if ri else (np.array([], int), np.array([]))
           for la, lo in zip(meta.lat, meta.lon)]
    normals = point_normals(meta.lat.values, meta.lon.values, ri, ri.gauge_normals()) if ri \
        else np.full((len(meta), len(CFG.rain_windows), 365), np.nan, np.float32)
    print(f"[rain] gauges used: {len(used)}; wells with any normals: "
          f"{int((~np.isnan(normals).all(axis=(1, 2))).sum())}/{len(meta)}")

    # ---- pairs + split
    P = enum_pairs(series)
    W, I, J, DI, DJ = P
    print(f"[pairs] {len(W):,} (origin reading -> later reading) pairs from {len(meta)} wells")
    hold = np.array([zlib.crc32(w.encode()) % 100 < CFG.holdout_frac * 100 for w in meta.well_id])
    if mode == "eval":
        te, ve = int(to_day(CFG.train_end)), int(to_day(CFG.val_end))
        sel = {"train": np.flatnonzero(~hold[W] & (DJ <= te)), "val": np.flatnonzero(~hold[W] & (DI > te) & (DJ <= ve)),
               "test_seen": np.flatnonzero(~hold[W] & (DI > ve)), "test_unseen_wells": np.flatnonzero(hold[W] & (DI > ve))}
    else:
        te = int(DJ.max())
        sel = {"train": np.arange(len(W))}
    if len(sel["train"]) > CFG.max_train_pairs:
        sel["train"] = rng.choice(sel["train"], CFG.max_train_pairs, replace=False)
    print({k: len(v) for k, v in sel.items()})
    if len(sel["train"]) < 500:
        raise SystemExit("Too few training pairs - check dates / config.")

    # ---- scalers from TRAIN-period data only
    trw = ~hold if mode == "eval" else np.ones(len(meta), bool)
    allgw = np.concatenate([L[D <= te] for (D, L), ok in zip(series, trw) if ok and len(D)])
    dm = meta.depth[meta.depth > 0]
    delta = np.array([series[W[p]][1][J[p]] - series[W[p]][1][I[p]] for p in sel["train"]])
    sc = {"gw_mean": float(allgw.mean()), "gw_std": float(allgw.std()), "y_scale": float(max(delta.std(), 0.1)),
          "lat_mean": float(meta.lat.mean()), "lat_std": float(meta.lat.std() or 1), "lon_mean": float(meta.lon.mean()),
          "lon_std": float(meta.lon.std() or 1), "depth_mean": float(dm.mean()) if len(dm) else 0.0,
          "depth_std": float(dm.std()) if len(dm) > 1 else 1.0, "train_cutoff_day": int(te), "mode": mode}
    static = np.stack([static_row(r.lat, r.lon, r.depth, r.aquifer, r.well_type, sc) for r in meta.itertuples()])
    ys = sc["y_scale"]

    mk = lambda s, aug: materialize(sel[s], P, series, static, ri, nbs, normals, sc, rng, aug)
    data = {"train": mk("train", True)}
    print(f"[samples] train {len(data['train']['y']):,}  (rain available in "
          f"{(data['train']['ctx'][:, 5] > 0).mean():.0%} of them)")
    for s in sel:
        if s != "train":
            data[s] = mk(s, False)

    # ---- baseline from TRAIN pairs (s=0): per-well seasonal climatology of the change
    t0 = materialize(sel["train"], P, series, static, ri, nbs, normals, sc, rng, False)
    tb = pd.DataFrame({"w": t0["w"], "mo": t0["mo"], "mt": t0["mt"], "d": t0["y"]})
    base_w, base_g = tb.groupby(["w", "mo", "mt"]).d.mean(), tb.groupby(["mo", "mt"]).d.mean()

    # ---- train
    net = GWNet()
    opt = torch.optim.AdamW(net.parameters(), lr=CFG.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=2)
    dl = DataLoader(tens(data["train"], ys), batch_size=CFG.batch, shuffle=True)
    vl = DataLoader(tens(data["val"], ys), batch_size=2048) if mode == "eval" and len(data["val"]["y"]) else None
    epochs = CFG.epochs
    if mode == "final":
        epochs = json.load(open(CFG.art_dir / "metrics_eval.json"))["best_epoch"] + 1
    best, best_ep, bad, state = 1e9, 0, 0, None
    for ep in range(epochs):
        net.train()
        tl = 0.0
        for tk, st, cx, y in dl:
            loss = pinball(net(tk, st, cx), y)
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0); opt.step()
            tl += loss.item() * len(y)
        tl /= len(dl.dataset)
        if vl:
            net.eval()
            with torch.no_grad():
                vloss = sum(pinball(net(tk, st, cx), y).item() * len(y) for tk, st, cx, y in vl) / len(vl.dataset)
            sched.step(vloss)
            print(f"epoch {ep:02d} train {tl:.4f} val {vloss:.4f}")
            if vloss < best - 1e-4:
                best, best_ep, bad = vloss, ep, 0
                state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= CFG.patience:
                    print("early stop"); break
        else:
            print(f"epoch {ep:02d} train {tl:.4f}")
    if state:
        net.load_state_dict(state)

    # ---- evaluation (eval mode)
    if mode == "eval":
        res = {"best_epoch": best_ep, "y_scale_m": ys}
        for s in ("val", "test_seen", "test_unseen_wells"):
            res[s] = evaluate(net, data[s], ys, base_w, base_g)
        print(json.dumps(res, indent=1))
        json.dump(res, open(CFG.art_dir / "metrics_eval.json", "w"), indent=1)

    # ---- artifacts for the service
    torch.save(net.state_dict(), CFG.art_dir / "model.pt")
    json.dump({"hidden": CFG.hidden, "layers": CFG.layers}, open(CFG.art_dir / "model_cfg.json", "w"))
    json.dump(sc, open(CFG.art_dir / "scalers.json", "w"), indent=1)
    meta.to_parquet(CFG.art_dir / "wells_static.parquet", index=False)
    np.save(CFG.art_dir / "normals.npy", normals)
    shutil.copy(CFG.proc_dir / "wells_obs.parquet", CFG.art_dir / "wells_obs.parquet")
    print(f"[done] mode={mode}; artifacts in {CFG.art_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["eval", "final"], default="eval")
    run(ap.parse_args().mode)
