"""
Step 2 - ONE place that turns observations into model inputs. Training, validation and the live API
all call these same functions, so there is no train/serve skew when Node.js feeds the model.

A sample = "it is day `as_of`; here are the last <=12 readings of this well (with their ages), the rain
that has actually been reported up to today, the well's static traits; what will the level be in h days?"
"""
import numpy as np
import pandas as pd
from config import CFG

EPOCH = np.datetime64("1970-01-01")
N_TOK, N_STATIC, N_RAIN = 6, 11, 4 * len(CFG.rain_windows)
N_CTX = 5 + N_RAIN
AQ = ("unconfined", "semi-confined", "confined", "unknown")
WT = ("dug well", "piezometer", "unknown")


# ---------------------------------------------------------------- calendar helpers
def to_day(x):
    return (np.asarray(x).astype("datetime64[D]") - EPOCH).astype("int64")


def from_day(d):
    return EPOCH + np.asarray(d, dtype="int64").astype("timedelta64[D]")


def doy(day):
    dt = from_day(day)
    y = dt.astype("datetime64[Y]").astype("datetime64[D]")
    return np.minimum((dt - y).astype("int64") + 1, 365)


def season(day):
    a = 2 * np.pi * doy(day) / 365.0
    return np.sin(a), np.cos(a)


def month0(day):
    return from_day(day).astype("datetime64[M]").astype("int64") % 12


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def neighbors(lat, lon, glat, glon, k=None, max_km=None):
    k, max_km = k or CFG.rain_k, max_km or CFG.rain_max_km
    d = haversine(lat, lon, glat, glon)
    order = np.argsort(d)[:k]
    keep = order[d[order] <= max_km]
    if len(keep) == 0:
        return keep, np.array([])
    w = 1.0 / np.maximum(d[keep], 1.0) ** 2
    return keep, w / w.sum()


# ---------------------------------------------------------------- rainfall index (cumulative sums of REPORTED days only)
class RainIndex:
    def __init__(self, long, meta):
        self.gauges = meta.gauge.values
        self.glat, self.glon = meta.lat.values, meta.lon.values
        gi = pd.Categorical(long.gauge, categories=self.gauges).codes
        d = to_day(long.date.values)
        self.d0, self.n, G = int(d.min()), int(d.max() - d.min() + 1), len(self.gauges)
        rain = np.zeros((G, self.n), np.float32)
        obs = np.zeros((G, self.n), bool)
        rain[gi, d - self.d0] = long.mm.values
        obs[gi, d - self.d0] = True
        if CFG.rain_missing_means_zero:      # explicit user decision only
            for g in range(G):
                idx = np.flatnonzero(obs[g])
                if len(idx):
                    obs[g, idx[0]:idx[-1] + 1] = True
        z = np.zeros((G, 1))
        self.cs_r = np.concatenate([z, np.cumsum(rain, 1, dtype=np.float64)], 1).astype(np.float32)
        self.cs_o = np.concatenate([z.astype(np.int32), np.cumsum(obs, 1, dtype=np.int32)], 1)

    def window(self, gidx, w, day_end, W):
        """(sum_mm, coverage) of the IDW-weighted gauges that reported >= min_cov of the W days ending day_end."""
        if len(gidx) == 0:
            return None
        hi = day_end - self.d0 + 1
        lo = hi - W
        if hi <= 0 or lo >= self.n:
            return None
        lo_c, hi_c = max(lo, 0), min(hi, self.n)
        s = np.maximum(self.cs_r[gidx, hi_c] - self.cs_r[gidx, lo_c], 0.0)
        cov = (self.cs_o[gidx, hi_c] - self.cs_o[gidx, lo_c]) / W
        ok = cov >= CFG.rain_min_cov
        if not ok.any():
            return None
        ww = w[ok] / w[ok].sum()
        return float((s[ok] * ww).sum()), float((cov[ok] * ww).sum())

    def gauge_normals(self):
        """(G, n_windows, 365) mean W-day rainfall ending on each day-of-year, from the normals era only.
        Years with < min_cov reporting are skipped; DOYs with < min_years valid years stay NaN (not guessed)."""
        G, nW = len(self.gauges), len(CFG.rain_windows)
        out = np.full((G, nW, 365), np.nan, np.float32)
        d_lo, d_hi = int(to_day(f"{CFG.normals_era[0]}-01-01")), int(to_day(f"{CFG.normals_era[1]}-12-31"))
        days = np.arange(max(d_lo, self.d0 + max(CFG.rain_windows)), min(d_hi, self.d0 + self.n - 1) + 1)
        if len(days) == 0:
            return out
        dd, yy = doy(days), from_day(days).astype("datetime64[Y]").astype(int) + 1970
        hi = days - self.d0 + 1
        for g in range(G):
            if self.cs_o[g, hi[-1]] - self.cs_o[g, hi[0] - 1] < 365 * CFG.normals_min_years * 0.5:
                continue
            for wi, W in enumerate(CFG.rain_windows):
                s = self.cs_r[g, hi] - self.cs_r[g, hi - W]
                valid = (self.cs_o[g, hi] - self.cs_o[g, hi - W]) / W >= CFG.rain_min_cov
                if not valid.any():
                    continue
                t = pd.DataFrame({"doy": dd[valid], "s": s[valid], "y": yy[valid]}).groupby("doy").agg(
                    m=("s", "mean"), n=("y", "nunique"))
                t = t[t.n >= CFG.normals_min_years]
                out[g, wi, t.index.values - 1] = t.m.values
        return out


def used_gauges(lats, lons, rmeta):
    used = set()
    for la, lo in zip(lats, lons):
        idx, _ = neighbors(la, lo, rmeta.lat.values, rmeta.lon.values)
        used.update(rmeta.gauge.values[idx])
    return used


def point_normals(lats, lons, ri, gnorm):
    """IDW of nearby gauge normals for each point -> (N, n_windows, 365), NaN where unavailable."""
    out = np.full((len(lats), gnorm.shape[1], 365), np.nan, np.float32)
    for p, (la, lo) in enumerate(zip(lats, lons)):
        idx, w = neighbors(la, lo, ri.glat, ri.glon)
        if len(idx) == 0:
            continue
        arr, m = gnorm[idx], ~np.isnan(gnorm[idx])
        ww = w.reshape(-1, 1, 1)
        den = (m * ww).sum(0)
        num = (np.nan_to_num(arr) * ww * m).sum(0)
        out[p] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    return out


# ---------------------------------------------------------------- feature vectors
def static_row(lat, lon, depth, aquifer, wtype, sc):
    miss = depth is None or not np.isfinite(depth) or depth <= 0
    v = [(lat - sc["lat_mean"]) / sc["lat_std"], (lon - sc["lon_mean"]) / sc["lon_std"],
         0.0 if miss else (depth - sc["depth_mean"]) / sc["depth_std"], float(miss)]       # missing -> flag, not a made-up depth
    v += [float(aquifer == a) for a in AQ] + [float(wtype == w) for w in WT]
    return np.array(v, np.float32)


def tok_matrix(days, lv, as_of, sc):
    """Last K readings (chronological, all <= as_of), right-aligned; padding rows are all-zero incl. valid flag."""
    K = CFG.K
    days, lv = days[-K:], lv[-K:]
    n = len(days)
    s, c = season(days)
    out = np.zeros((K, N_TOK), np.float32)
    out[K - n:, 0] = (lv - lv[-1]) / sc["y_scale"]       # change relative to the latest reading
    out[K - n:, 1] = (lv - sc["gw_mean"]) / sc["gw_std"]  # absolute depth regime
    out[K - n:, 2] = (as_of - days) / 365.0              # age of reading
    out[K - n:, 3], out[K - n:, 4], out[K - n:, 5] = s, c, 1.0
    return out


def rain_feats(wins, normals):
    """wins: per window (sum, cov) or None.  normals: per window mean rainfall or NaN."""
    o = []
    for w, nm in zip(wins, normals):
        if w is None:
            o += [0.0, 0.0, 0.0, 0.0]
            continue
        nm_ok = bool(np.isfinite(nm) and nm >= 10)
        o += [1.0, np.log1p(w[0]) / 6.0, float(nm_ok), min(w[0] / nm, 4.0) / 2.0 if nm_ok else 0.0]
    return np.array(o, np.float32)


def ctx_vec(as_of, h, rain12):
    sa, ca = season(np.array([as_of]))
    st, ct = season(np.array([as_of + h]))
    return np.concatenate([[h / 100.0, sa[0], ca[0], st[0], ct[0]], rain12]).astype(np.float32)


def rain_windows_for(ri, nb, as_of):
    if ri is None:
        return [None] * len(CFG.rain_windows)
    return [ri.window(nb[0], nb[1], as_of, W) for W in CFG.rain_windows]
