# """
# Step 1 - load each raw file in its OWN native form. Nothing is merged, interpolated or invented.

#   quarterly wells  -> data/processed/wells_obs.parquet  + wells_meta.parquet   (irregular readings)
#   rainfall files   -> data/processed/rain_long.parquet  + rain_meta.parquet    (only days that were reported)
#   telemetry (opt.) -> data/processed/tele_obs.parquet   + tele_meta.parquet    (daily mean of real 6-hourly values)

# Bad rows are dropped and counted. The report printed at the end tells you exactly what was removed.

#   python data_prep.py --wells data/raw/wells.csv --rain data/raw/rain_1961_1990.csv data/raw/rain_2022_2025.csv \
#                       --telemetry data/raw/telemetry.csv
# """
# import argparse
# import re
# import numpy as np
# import pandas as pd
# from config import CFG


# # ------------------------------------------------------------------ reading + column matching
# def _norm(c):
#     return re.sub(r"[^a-z0-9]+", "_", str(c).lower()).strip("_")


# def _compact(c):
#     return re.sub(r"[^a-z0-9]", "", str(c).lower())


# def read_table(path):
#     """Reads .xlsx/.xls/.csv (CSV tried as utf-8-sig, cp1252, latin1) and ALWAYS normalises column names."""
#     p = str(path)
#     if p.lower().endswith((".xlsx", ".xls")):
#         df = pd.read_excel(p)
#     else:
#         df, last = None, None
#         for enc in ("utf-8-sig", "cp1252", "latin1"):
#             try:
#                 df = pd.read_csv(p, low_memory=False, encoding=enc)
#                 break
#             except UnicodeDecodeError as e:
#                 last = e
#         if df is None:
#             raise ValueError(f"Could not decode {p}: {last}")
#     df.columns = [_norm(c) for c in df.columns]
#     return df.loc[:, ~df.columns.duplicated()]


# def _find(df, *keys, required=True):
#     """Column whose name contains ALL keys. An exact match wins; otherwise the SHORTEST matching name wins
#     (so 'district' picks 'District Name', not 'District LGD Code'). required=False -> None when absent."""
#     want = _compact("".join(keys))
#     cols = {c: _compact(c) for c in df.columns}
#     for c, cc in cols.items():
#         if cc == want:
#             return c
#     hits = [c for c, cc in cols.items() if all(_compact(k) in cc for k in keys)]
#     if hits:
#         return min(hits, key=lambda c: len(cols[c]))
#     if required:
#         raise KeyError(f"No column containing {keys}. Columns: {list(df.columns)}")
#     return None


# # ------------------------------------------------------------------ dates

# def parse_dates(s):
#     s = s.astype("string").str.strip()
#     s = s.replace("", pd.NA)

#     # Preallocate results
#     out = pd.Series(
#         pd.NaT,
#         index=s.index,
#         dtype="datetime64[ns]"
#     )

#     # Try common formats first; each attempt handles a whole batch.
#     formats = [
#         "%Y-%m-%d %H:%M:%S",
#         "%Y-%m-%d %H:%M",
#         "%Y-%m-%d",
#         "%d-%m-%Y %H:%M:%S",
#         "%d-%m-%Y %H:%M",
#         "%d-%m-%Y",
#         "%d/%m/%Y %H:%M:%S",
#         "%d/%m/%Y %H:%M",
#         "%d/%m/%Y",
#     ]

#     remaining = s.notna()

#     for fmt in formats:
#         if not remaining.any():
#             break

#         parsed = pd.to_datetime(
#             s.loc[remaining],
#             format=fmt,
#             errors="coerce"
#         )

#         valid = parsed.notna()
#         out.loc[parsed.index[valid]] = parsed.loc[valid]
#         remaining.loc[parsed.index[valid]] = False

#     failed = s.notna() & out.isna()

#     if failed.any():
#         print(f"Warning: {failed.sum()} timestamps could not be parsed.")
#         print("Examples:", s.loc[failed].head(10).tolist())

#     return out



# _DMY = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}")


# def date_hint(s):
#     """Non-ISO dates can PROVE their order (a first number > 12 must be a day). Warn if config disagrees."""
#     m = s.astype("string").dropna().str.extract(_DMY).dropna().astype(int)
#     if m.empty:
#         return None
#     first, second = int((m[0] > 12).sum()), int((m[1] > 12).sum())
#     if first and not second and not CFG.dayfirst:
#         return "dates look DAY-first (e.g. 25-10-2024) but CFG.dayfirst=False -> set dayfirst=True in config.py"
#     if second and not first and CFG.dayfirst:
#         return "dates look MONTH-first (e.g. 10-25-2024) but CFG.dayfirst=True -> set dayfirst=False in config.py"
#     if first and second:
#         return "file mixes day-first and month-first dates; check the source"
#     if not first and not second:
#         return "all dates have day<=12 and month<=12, so their order cannot be verified; confirm CFG.dayfirst"
#     return None


# def _need_rows(df, what, rep):
#     if df.empty:
#         raise ValueError(f"{what}: no valid rows left after cleaning. Report so far: {rep}")


# def _span(dates):
#     return f"{dates.min().year}-{dates.max().year}"


# def _category(series, rules):
#     s = series.astype(str).str.lower()
#     out = pd.Series("unknown", index=series.index)
#     for sub, label in rules:                     # first matching rule wins
#         out[(out == "unknown") & s.str.contains(sub, na=False)] = label
#     return out


# def _bbox_ok(lat, lon):
#     a, b, c, d = CFG.bbox
#     return lat.between(a, b) & lon.between(c, d)


# # ------------------------------------------------------------------ quarterly wells
# def load_wells(path):
#     df = read_table(path)
#     c_id, c_la, c_lo = _find(df, "well", "id"), _find(df, "latitude"), _find(df, "longitude")
#     c_dt, c_lv = _find(df, "date", "monitoring"), _find(df, "water", "level")
#     c_dp, c_aq, c_wt = _find(df, "well", "depth", required=False), _find(df, "aquifer", required=False), \
#         _find(df, "well", "type", required=False)
#     rep = {"rows_in": len(df)}
#     hint = date_hint(df[c_dt])
#     if hint:
#         rep["WARNING_date_format"] = hint

#     df["well_id"] = df[c_id].astype(str).str.strip()
#     df["ts"] = parse_dates(df[c_dt])
#     df["level"] = pd.to_numeric(df[c_lv], errors="coerce")
#     df["lat"], df["lon"] = pd.to_numeric(df[c_la], errors="coerce"), pd.to_numeric(df[c_lo], errors="coerce")
#     df["depth"] = pd.to_numeric(df[c_dp], errors="coerce") if c_dp else np.nan

#     rep["dropped_bad_date"] = int(df.ts.isna().sum())
#     rep["dropped_non_numeric_level (e.g. 'Dry')"] = int(df.level.isna().sum())
#     df = df.dropna(subset=["ts", "level"])
#     n = len(df)
#     df = df[(df.level >= CFG.gw_min) & (df.level <= CFG.gw_max)]
#     rep["dropped_out_of_range"] = n - len(df)
#     n = len(df)
#     df = df[~((df.depth > 0) & (df.level > df.depth + CFG.well_depth_tol))]
#     rep["dropped_deeper_than_well_bottom"] = n - len(df)
#     _need_rows(df, "wells", rep)

#     df["date"] = df.ts.dt.floor("D")
#     obs = df.groupby(["well_id", "date"], as_index=False)["level"].mean()

#     meta = df.groupby("well_id").agg(lat=("lat", "first"), lon=("lon", "first"), depth=("depth", "first"))
#     meta["aquifer"] = _category(df.groupby("well_id")[c_aq].first(), [("semi", "semi-confined"), ("unconf", "unconfined"),
#                                                                         ("conf", "confined")]) if c_aq else "unknown"
#     meta["well_type"] = _category(df.groupby("well_id")[c_wt].first(), [("dug", "dug well"), ("piez", "piezometer")]) \
#         if c_wt else "unknown"
#     for name in ("state", "district", "block", "village"):
#         col = _find(df, name, required=False)
#         meta[name] = df.groupby("well_id")[col].first() if col else None
#     ok = meta.lat.notna() & meta.lon.notna() & _bbox_ok(meta.lat, meta.lon)
#     rep["wells_dropped_bad_or_missing_coords"] = int((~ok).sum())
#     meta = meta[ok].reset_index()
#     obs = obs[obs.well_id.isin(meta.well_id)].sort_values(["well_id", "date"]).reset_index(drop=True)
#     _need_rows(obs, "wells (after coordinate filter)", rep)

#     rep.update(rows_kept=len(obs), wells=int(meta.shape[0]), years=_span(obs.date),
#                median_readings_per_well=int(obs.groupby("well_id").size().median()))
#     rep["readings_by_month (shows YOUR monitoring rounds)"] = obs.date.dt.month.value_counts().sort_index().to_dict()
#     return obs, meta, rep


# # ------------------------------------------------------------------ rainfall (one or more files, same schema)
# def load_rain(paths):
#     parts, hints = [], []
#     for p in paths:
#         df = read_table(p)
#         c_st, c_la, c_lo = _find(df, "station"), _find(df, "latitude"), _find(df, "longitude")
#         c_t, c_v = _find(df, "acquisition", "time"), _find(df, "rainfall")
#         h = date_hint(df[c_t])
#         if h:
#             hints.append(f"{p}: {h}")
#         parts.append(pd.DataFrame({
#             "station": df[c_st].astype(str).str.strip(),
#             "lat": pd.to_numeric(df[c_la], errors="coerce"), "lon": pd.to_numeric(df[c_lo], errors="coerce"),
#             "ts": parse_dates(df[c_t]),
#             "mm": pd.to_numeric(df[c_v], errors="coerce")}))
#     df = pd.concat(parts, ignore_index=True)
#     rep = {"rows_in": len(df), "dropped_bad_date_or_value": int((df.ts.isna() | df.mm.isna()).sum())}
#     if hints:
#         rep["WARNING_date_format"] = hints
#     df = df.dropna(subset=["ts", "mm", "lat", "lon"])
#     n = len(df)
#     df = df[(df.mm >= 0) & (df.mm <= CFG.rain_max_mm) & _bbox_ok(df.lat, df.lon)]
#     rep["dropped_out_of_range"] = n - len(df)
#     _need_rows(df, "rainfall", rep)
#     df["gauge"] = df.station + "|" + df.lat.round(3).astype(str) + "|" + df.lon.round(3).astype(str)
#     df["date"] = df.ts.dt.floor("D")
#     long = df.groupby(["gauge", "date"], as_index=False).mm.max()      # duplicate same-day rows: keep max, don't double count
#     meta = df.groupby("gauge", as_index=False).agg(lat=("lat", "first"), lon=("lon", "first"))

#     # ---- audit: do gauges report dry days as 0, or only rainy days? (decides how "missing" must be read)
#     g = long.groupby("gauge").date.agg(["min", "max", "count"])
#     span = (g["max"] - g["min"]).dt.days + 1
#     rep.update(gauges=len(meta), years=_span(long.date),
#                median_reporting_density=round(float((g["count"] / span).median()), 3),
#                share_of_readings_equal_0mm=round(float((long.mm == 0).mean()), 3))
#     rep["by_year_rows"] = long.date.dt.year.value_counts().sort_index().to_dict()
#     if rep["share_of_readings_equal_0mm"] < 0.05:
#         rep["WARNING"] = ("almost no 0 mm rows: gauges may list RAINY DAYS ONLY. Missing days would then mean 0 mm. "
#                           "Confirm with the data owner; if so set rain_missing_means_zero=True in config.py. "
#                           "Until you confirm, missing is treated as UNKNOWN (safe default).")
#     return long, meta, rep


# # ------------------------------------------------------------------ telemetry (validation only)
# def load_telemetry(path):
#     df = read_table(path)
#     c_st, c_la, c_lo = _find(df, "station"), _find(df, "latitude"), _find(df, "longitude")
#     c_t = _find(df, "acquisition", "time")
#     c_v = _find(df, "telemetry", required=False) or _find(df, "avg_ground_water_level")
#     rep = {"rows_in": len(df)}
#     hint = date_hint(df[c_t])
#     if hint:
#         rep["WARNING_date_format"] = hint
#     df["ts"] = parse_dates(df[c_t])
#     df["v"] = pd.to_numeric(df[c_v], errors="coerce")
#     df = df.dropna(subset=["ts", "v"])
#     df = df[(df.v >= CFG.gw_min) & (df.v <= CFG.gw_max)]
#     _need_rows(df, "telemetry", rep)
#     df["date"] = df.ts.dt.floor("D")
#     daily = df.groupby([c_st, "date"], as_index=False)["v"].mean().rename(columns={c_st: "station", "v": "level"})
#     out = []
#     for st, g in daily.groupby("station"):                       # spike removal = DROP, never replace
#         s = g.set_index("date")["level"]
#         s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
#         med = s.rolling(15, center=True, min_periods=3).median()
#         r = (s - med).abs()
#         mad = r.rolling(61, center=True, min_periods=5).median().clip(lower=0.5)
#         s = s.mask(r > 10 * 1.4826 * mad).dropna()
#         out.append(pd.DataFrame({"station": st, "date": s.index, "level": s.values}))
#     obs = pd.concat(out, ignore_index=True)
#     meta = df.groupby(c_st).agg(lat=(c_la, "first"), lon=(c_lo, "first")).reset_index().rename(columns={c_st: "station"})
#     meta["lat"], meta["lon"] = pd.to_numeric(meta.lat, errors="coerce"), pd.to_numeric(meta.lon, errors="coerce")
#     meta = meta[meta.lat.notna() & meta.lon.notna() & _bbox_ok(meta.lat, meta.lon)]
#     obs = obs[obs.station.isin(meta.station)]
#     _need_rows(obs, "telemetry (after coordinate filter)", rep)
#     rep.update(stations=len(meta), daily_rows_kept=len(obs), years=_span(obs.date))
#     return obs, meta, rep


# def _show(title, rep):
#     print(f"\n== {title} ==")
#     for k, v in rep.items():
#         print(f"  {k}: {v}")


# if __name__ == "__main__":
#     ap = argparse.ArgumentParser()
#     ap.add_argument("--wells", required=True)
#     ap.add_argument("--rain", nargs="+", required=True)
#     ap.add_argument("--telemetry")
#     a = ap.parse_args()
#     CFG.proc_dir.mkdir(parents=True, exist_ok=True)
#     o, m, r = load_wells(a.wells); o.to_parquet(CFG.proc_dir / "wells_obs.parquet", index=False)
#     m.to_parquet(CFG.proc_dir / "wells_meta.parquet", index=False); _show("quarterly wells", r)
#     o, m, r = load_rain(a.rain); o.to_parquet(CFG.proc_dir / "rain_long.parquet", index=False)
#     m.to_parquet(CFG.proc_dir / "rain_meta.parquet", index=False); _show("rainfall", r)
#     if a.telemetry:
#         o, m, r = load_telemetry(a.telemetry); o.to_parquet(CFG.proc_dir / "tele_obs.parquet", index=False)
#         m.to_parquet(CFG.proc_dir / "tele_meta.parquet", index=False); _show("telemetry", r)

"""
Step 1 - load each raw file in its OWN native form. Nothing is merged, interpolated or invented.

  quarterly wells  -> data/processed/wells_obs.parquet  + wells_meta.parquet   (irregular readings)
  rainfall files   -> data/processed/rain_long.parquet  + rain_meta.parquet    (only days that were reported)
  telemetry (opt.) -> data/processed/tele_obs.parquet   + tele_meta.parquet    (daily mean of real 6-hourly values)

Bad rows are dropped and counted. The report printed at the end tells you exactly what was removed.

  python data_prep.py --wells data/raw/wells.csv --rain data/raw/rain_1961_1990.csv data/raw/rain_2022_2025.csv \
                      --telemetry data/raw/telemetry.csv
"""
import argparse
import re
import numpy as np
import pandas as pd
from config import CFG


# ------------------------------------------------------------------ reading + column matching
def _norm(c):
    return re.sub(r"[^a-z0-9]+", "_", str(c).lower()).strip("_")


def _compact(c):
    return re.sub(r"[^a-z0-9]", "", str(c).lower())


def read_table(path):
    """Reads .xlsx/.xls/.csv (CSV tried as utf-8-sig, cp1252, latin1) and ALWAYS normalises column names."""
    p = str(path)
    if p.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(p)
    else:
        df, last = None, None
        for enc in ("utf-8-sig", "cp1252", "latin1"):
            try:
                df = pd.read_csv(p, low_memory=False, encoding=enc)
                break
            except UnicodeDecodeError as e:
                last = e
        if df is None:
            raise ValueError(f"Could not decode {p}: {last}")
    df.columns = [_norm(c) for c in df.columns]
    return df.loc[:, ~df.columns.duplicated()]


def _find(df, *keys, required=True):
    """Column whose name contains ALL keys. An exact match wins; otherwise the SHORTEST matching name wins
    (so 'district' picks 'District Name', not 'District LGD Code'). required=False -> None when absent."""
    want = _compact("".join(keys))
    cols = {c: _compact(c) for c in df.columns}
    for c, cc in cols.items():
        if cc == want:
            return c
    hits = [c for c, cc in cols.items() if all(_compact(k) in cc for k in keys)]
    if hits:
        return min(hits, key=lambda c: len(cols[c]))
    if required:
        raise KeyError(f"No column containing {keys}. Columns: {list(df.columns)}")
    return None


# ------------------------------------------------------------------ dates
_TIMES = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", ""]
_SEPS = ["-", "/", "."]


def _formats(dayfirst):
    """Explicit formats so pandas can use its fast C parser. For each time pattern the preferred order
    (day-first or month-first, per CFG.dayfirst) is tried before the opposite one."""
    order = [("%d", "%m"), ("%m", "%d")] if dayfirst else [("%m", "%d"), ("%d", "%m")]
    return [f"{x}{sep}{y}{sep}%Y" + (f" {t}" if t else "") for sep in _SEPS for t in _TIMES for x, y in order]


def parse_dates(s):
    """1) ISO strings are read as ISO.  2) Other strings are tried against explicit formats (fast, vectorised);
    the order of day/month follows CFG.dayfirst and is only used when a string fits no other reading.
    3) Whatever is left (month names etc.) goes through the slow generic parser, on UNIQUE strings only.
    (The old 'format=mixed' path took ~50 microseconds per row: minutes on millions of telemetry rows.)"""
    s = s.astype("string").str.strip().replace("", pd.NA)
    out = pd.to_datetime(s, errors="coerce", format="ISO8601")
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_localize(None)                      # keep wall-clock time, drop the offset
    todo = out.isna() & s.notna()
    for f in _formats(CFG.dayfirst):
        if not todo.any():
            break
        got = pd.to_datetime(s[todo], errors="coerce", format=f)
        ok = got.notna()
        if ok.any():
            out.loc[got.index[ok]] = got[ok]
            todo = out.isna() & s.notna()
    if todo.any():
        u = s[todo].dropna().unique().tolist()
        parsed = pd.to_datetime(pd.Series(u, dtype="string"), errors="coerce", dayfirst=CFG.dayfirst, format="mixed")
        lut = dict(zip(u, parsed))
        out.loc[todo] = pd.to_datetime(s[todo].map(lut))
    return out


_DMY = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}")


def date_hint(s):
    """Non-ISO dates can PROVE their order (a first number > 12 must be a day). Warn if config disagrees."""
    m = s.astype("string").dropna().str.extract(_DMY).dropna().astype(int)
    if m.empty:
        return None
    first, second = int((m[0] > 12).sum()), int((m[1] > 12).sum())
    if first and not second and not CFG.dayfirst:
        return "dates look DAY-first (e.g. 25-10-2024) but CFG.dayfirst=False -> set dayfirst=True in config.py"
    if second and not first and CFG.dayfirst:
        return "dates look MONTH-first (e.g. 10-25-2024) but CFG.dayfirst=True -> set dayfirst=False in config.py"
    if first and second:
        return "file mixes day-first and month-first dates; check the source"
    if not first and not second:
        return "all dates have day<=12 and month<=12, so their order cannot be verified; confirm CFG.dayfirst"
    return None


def _need_rows(df, what, rep):
    if df.empty:
        raise ValueError(f"{what}: no valid rows left after cleaning. Report so far: {rep}")


def _span(dates):
    return f"{dates.min().year}-{dates.max().year}"


def _category(series, rules):
    s = series.astype(str).str.lower()
    out = pd.Series("unknown", index=series.index)
    for sub, label in rules:                     # first matching rule wins
        out[(out == "unknown") & s.str.contains(sub, na=False)] = label
    return out


def _bbox_ok(lat, lon):
    a, b, c, d = CFG.bbox
    return lat.between(a, b) & lon.between(c, d)


# ------------------------------------------------------------------ quarterly wells
def load_wells(path):
    df = read_table(path)
    c_id, c_la, c_lo = _find(df, "well", "id"), _find(df, "latitude"), _find(df, "longitude")
    c_dt, c_lv = _find(df, "date", "monitoring"), _find(df, "water", "level")
    c_dp, c_aq, c_wt = _find(df, "well", "depth", required=False), _find(df, "aquifer", required=False), \
        _find(df, "well", "type", required=False)
    rep = {"rows_in": len(df)}
    hint = date_hint(df[c_dt])
    if hint:
        rep["WARNING_date_format"] = hint

    df["well_id"] = df[c_id].astype(str).str.strip()
    df["ts"] = parse_dates(df[c_dt])
    df["level"] = pd.to_numeric(df[c_lv], errors="coerce")
    df["lat"], df["lon"] = pd.to_numeric(df[c_la], errors="coerce"), pd.to_numeric(df[c_lo], errors="coerce")
    df["depth"] = pd.to_numeric(df[c_dp], errors="coerce") if c_dp else np.nan

    rep["dropped_bad_date"] = int(df.ts.isna().sum())
    rep["dropped_non_numeric_level (e.g. 'Dry')"] = int(df.level.isna().sum())
    df = df.dropna(subset=["ts", "level"])
    n = len(df)
    df = df[(df.level >= CFG.gw_min) & (df.level <= CFG.gw_max)]
    rep["dropped_out_of_range"] = n - len(df)
    n = len(df)
    df = df[~((df.depth > 0) & (df.level > df.depth + CFG.well_depth_tol))]
    rep["dropped_deeper_than_well_bottom"] = n - len(df)
    _need_rows(df, "wells", rep)

    df["date"] = df.ts.dt.floor("D")
    obs = df.groupby(["well_id", "date"], as_index=False)["level"].mean()

    meta = df.groupby("well_id").agg(lat=("lat", "first"), lon=("lon", "first"), depth=("depth", "first"))
    meta["aquifer"] = _category(df.groupby("well_id")[c_aq].first(), [("semi", "semi-confined"), ("unconf", "unconfined"),
                                                                        ("conf", "confined")]) if c_aq else "unknown"
    meta["well_type"] = _category(df.groupby("well_id")[c_wt].first(), [("dug", "dug well"), ("piez", "piezometer")]) \
        if c_wt else "unknown"
    for name in ("state", "district", "block", "village"):
        col = _find(df, name, required=False)
        meta[name] = df.groupby("well_id")[col].first() if col else None
    ok = meta.lat.notna() & meta.lon.notna() & _bbox_ok(meta.lat, meta.lon)
    rep["wells_dropped_bad_or_missing_coords"] = int((~ok).sum())
    meta = meta[ok].reset_index()
    obs = obs[obs.well_id.isin(meta.well_id)].sort_values(["well_id", "date"]).reset_index(drop=True)
    _need_rows(obs, "wells (after coordinate filter)", rep)

    rep.update(rows_kept=len(obs), wells=int(meta.shape[0]), years=_span(obs.date),
               median_readings_per_well=int(obs.groupby("well_id").size().median()))
    rep["readings_by_month (shows YOUR monitoring rounds)"] = obs.date.dt.month.value_counts().sort_index().to_dict()
    return obs, meta, rep


# ------------------------------------------------------------------ rainfall (one or more files, same schema)
def load_rain(paths):
    parts, hints = [], []
    for p in paths:
        df = read_table(p)
        c_st, c_la, c_lo = _find(df, "station"), _find(df, "latitude"), _find(df, "longitude")
        c_t, c_v = _find(df, "acquisition", "time"), _find(df, "rainfall")
        h = date_hint(df[c_t])
        if h:
            hints.append(f"{p}: {h}")
        parts.append(pd.DataFrame({
            "station": df[c_st].astype(str).str.strip(),
            "lat": pd.to_numeric(df[c_la], errors="coerce"), "lon": pd.to_numeric(df[c_lo], errors="coerce"),
            "ts": parse_dates(df[c_t]),
            "mm": pd.to_numeric(df[c_v], errors="coerce")}))
    df = pd.concat(parts, ignore_index=True)
    rep = {"rows_in": len(df), "dropped_bad_date_or_value": int((df.ts.isna() | df.mm.isna()).sum())}
    if hints:
        rep["WARNING_date_format"] = hints
    df = df.dropna(subset=["ts", "mm", "lat", "lon"])
    n = len(df)
    df = df[(df.mm >= 0) & (df.mm <= CFG.rain_max_mm) & _bbox_ok(df.lat, df.lon)]
    rep["dropped_out_of_range"] = n - len(df)
    _need_rows(df, "rainfall", rep)
    df["gauge"] = df.station + "|" + df.lat.round(3).astype(str) + "|" + df.lon.round(3).astype(str)
    df["date"] = df.ts.dt.floor("D")
    long = df.groupby(["gauge", "date"], as_index=False).mm.max()      # duplicate same-day rows: keep max, don't double count
    meta = df.groupby("gauge", as_index=False).agg(lat=("lat", "first"), lon=("lon", "first"))

    # ---- audit: do gauges report dry days as 0, or only rainy days? (decides how "missing" must be read)
    g = long.groupby("gauge").date.agg(["min", "max", "count"])
    span = (g["max"] - g["min"]).dt.days + 1
    rep.update(gauges=len(meta), years=_span(long.date),
               median_reporting_density=round(float((g["count"] / span).median()), 3),
               share_of_readings_equal_0mm=round(float((long.mm == 0).mean()), 3))
    rep["by_year_rows"] = long.date.dt.year.value_counts().sort_index().to_dict()
    if rep["share_of_readings_equal_0mm"] < 0.05:
        rep["WARNING"] = ("almost no 0 mm rows: gauges may list RAINY DAYS ONLY. Missing days would then mean 0 mm. "
                          "Confirm with the data owner; if so set rain_missing_means_zero=True in config.py. "
                          "Until you confirm, missing is treated as UNKNOWN (safe default).")
    return long, meta, rep


# ------------------------------------------------------------------ telemetry (validation only)
def load_telemetry(path):
    df = read_table(path)
    c_st, c_la, c_lo = _find(df, "station"), _find(df, "latitude"), _find(df, "longitude")
    c_t = _find(df, "acquisition", "time")
    c_v = _find(df, "telemetry", required=False) or _find(df, "avg_ground_water_level")
    rep = {"rows_in": len(df)}
    hint = date_hint(df[c_t])
    if hint:
        rep["WARNING_date_format"] = hint
    df["ts"] = parse_dates(df[c_t])
    df["v"] = pd.to_numeric(df[c_v], errors="coerce")
    df = df.dropna(subset=["ts", "v"])
    df = df[(df.v >= CFG.gw_min) & (df.v <= CFG.gw_max)]
    _need_rows(df, "telemetry", rep)
    df["date"] = df.ts.dt.floor("D")
    daily = df.groupby([c_st, "date"], as_index=False)["v"].mean().rename(columns={c_st: "station", "v": "level"})
    out = []
    for st, g in daily.groupby("station"):                       # spike removal = DROP, never replace
        s = g.set_index("date")["level"]
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
        med = s.rolling(15, center=True, min_periods=3).median()
        r = (s - med).abs()
        mad = r.rolling(61, center=True, min_periods=5).median().clip(lower=0.5)
        s = s.mask(r > 10 * 1.4826 * mad).dropna()
        out.append(pd.DataFrame({"station": st, "date": s.index, "level": s.values}))
    obs = pd.concat(out, ignore_index=True)
    meta = df.groupby(c_st).agg(lat=(c_la, "first"), lon=(c_lo, "first")).reset_index().rename(columns={c_st: "station"})
    meta["lat"], meta["lon"] = pd.to_numeric(meta.lat, errors="coerce"), pd.to_numeric(meta.lon, errors="coerce")
    meta = meta[meta.lat.notna() & meta.lon.notna() & _bbox_ok(meta.lat, meta.lon)]
    obs = obs[obs.station.isin(meta.station)]
    _need_rows(obs, "telemetry (after coordinate filter)", rep)
    rep.update(stations=len(meta), daily_rows_kept=len(obs), years=_span(obs.date))
    return obs, meta, rep


def _show(title, rep):
    print(f"\n== {title} ==")
    for k, v in rep.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wells", required=True)
    ap.add_argument("--rain", nargs="+", required=True)
    ap.add_argument("--telemetry")
    a = ap.parse_args()
    CFG.proc_dir.mkdir(parents=True, exist_ok=True)
    o, m, r = load_wells(a.wells); o.to_parquet(CFG.proc_dir / "wells_obs.parquet", index=False)
    m.to_parquet(CFG.proc_dir / "wells_meta.parquet", index=False); _show("quarterly wells", r)
    o, m, r = load_rain(a.rain); o.to_parquet(CFG.proc_dir / "rain_long.parquet", index=False)
    m.to_parquet(CFG.proc_dir / "rain_meta.parquet", index=False); _show("rainfall", r)
    if a.telemetry:
        o, m, r = load_telemetry(a.telemetry); o.to_parquet(CFG.proc_dir / "tele_obs.parquet", index=False)
        m.to_parquet(CFG.proc_dir / "tele_meta.parquet", index=False); _show("telemetry", r)