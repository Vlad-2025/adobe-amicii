"""Derived metrics. Everything here is computed from daily_stats (what a platform reports)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def with_rates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    imp = df["impressions"].clip(lower=1)
    clk = df["clicks"].clip(lower=1)
    df["ctr"] = df["clicks"] / imp
    df["cvr"] = df["conversions"] / clk
    df["cpm"] = df["spend"] / imp * 1000
    df["cpc"] = df["spend"] / clk
    df["cpa"] = df["spend"] / df["conversions"].clip(lower=1)
    df["roas"] = df["revenue"] / df["spend"].clip(lower=0.01)
    df["frequency"] = df["impressions7"] / df["reach7"].clip(lower=1)
    df["annoyed_share"] = df["comments_annoyed"] / df["comments_total"].clip(lower=1)
    return df


def ad_daily(df_comm: pd.DataFrame) -> pd.DataFrame:
    """Per ad per day, summed across communities."""
    g = df_comm.drop(columns=["community_id"], errors="ignore").groupby(["ad_id", "day"], as_index=False).sum()
    return with_rates(g)


def robust_z(recent: np.ndarray, base: np.ndarray) -> float:
    base = base[np.isfinite(base)]
    recent = recent[np.isfinite(recent)]
    if len(base) < 4 or len(recent) == 0:
        return 0.0
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    denom = max(mad, 0.05 * abs(med), 1e-9)
    return float((np.mean(recent) - med) / denom)


def window(series: pd.Series, day: int, recent: int = 3, base: int = 14, gap: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Recent = last `recent` days up to `day`. Baseline = the `base` days before that, ending `gap`
    days earlier, so a problem that started a week ago is still compared to healthy days.
    The baseline slides forward (shrinks the gap) when there is not enough history."""
    s = series
    r = s[(s.index > day - recent) & (s.index <= day)].to_numpy(float)
    first = int(s.index.min()) if len(s) else 0
    end = day - recent - gap
    while gap > 0 and end - first + 1 < 7:
        gap -= 1
        end = day - recent - gap
    b = s[(s.index > end - base) & (s.index <= end)].to_numpy(float)
    return r, b


def slope(y: np.ndarray) -> float:
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    if len(y) < 3:
        return 0.0
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0])


def rate_z(df: pd.DataFrame, num: str, den: str, day: int, gap: int = 0, recent: int = 3, base: int = 14, extra_rel_sd: float = 0.12) -> float:
    """z-score of a pooled rate (e.g. clicks/impressions) in the recent window vs the baseline window.
    Binomial variance plus `extra_rel_sd` relative noise, so big samples do not make tiny wobbles look significant."""
    idx = df.index
    first = int(idx.min()) if len(idx) else 0
    end = day - recent - gap
    while gap > 0 and end - first + 1 < 7:
        gap -= 1
        end = day - recent - gap
    r = df[(idx > day - recent) & (idx <= day)]
    b = df[(idx > end - base) & (idx <= end)]
    if len(b) < 4 or len(r) == 0 or b[den].sum() <= 0 or r[den].sum() <= 0:
        return 0.0
    pb = b[num].sum() / b[den].sum()
    pr = r[num].sum() / r[den].sum()
    var = pb * (1 - pb) / r[den].sum() + (extra_rel_sd * pb) ** 2
    return float((pr - pb) / max(var ** 0.5, 1e-9))
