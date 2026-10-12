"""ADP güven sınıfları ve imputasyon (README §5.6).

Bu, değerin ADP'ye sızdığı **tek** yerdir: ADP'si olmayan oyuncu için dengeli
Z-değer sırasından izotonik (monoton) bir eşleme ile ADP *tahmini* üretilir.

| adp_status       | A_i                                         | σ çarpanı |
|------------------|---------------------------------------------|-----------|
| ok               | adp                                         | 1.0       |
| low_confidence   | w·adp + (1−w)·Â                             | 1.5       |
| imputed          | Â                                           | 2.0       |
| tail             | max(A) + (değer sırası − havuz boyutu N)    | 2.0       |
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.config import AdpFallbackParams


def pav_increasing(y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    """Pool-Adjacent-Violators: ``y``'ye en yakın (ağırlıklı L2) azalmayan dizi."""
    y = np.asarray(y, dtype=float)
    w = np.ones_like(y) if w is None else np.asarray(w, dtype=float)
    vals: list[float] = []
    wts: list[float] = []
    counts: list[int] = []
    for yi, wi in zip(y, w):
        vals.append(yi)
        wts.append(wi)
        counts.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), counts.pop()
            v1, w1, c1 = vals.pop(), wts.pop(), counts.pop()
            wt = w1 + w2
            vals.append((v1 * w1 + v2 * w2) / wt)
            wts.append(wt)
            counts.append(c1 + c2)
    return np.repeat(vals, counts)


@dataclass(frozen=True)
class IsotonicMap:
    """Değer sırası → ADP monoton eşlemesi; kapsam ötesine doğrusal uzatma."""

    x: np.ndarray
    y: np.ndarray
    tail_slope: float

    @classmethod
    def fit(cls, x, y, tail_fraction: float = 0.2) -> "IsotonicMap":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        order = np.lexsort((y, x))
        x, y = x[order], y[order]
        fitted = pav_increasing(y)
        # aynı x için tek nokta (ortalama)
        ux, inv = np.unique(x, return_inverse=True)
        uy = np.bincount(inv, weights=fitted) / np.bincount(inv)
        uy = np.maximum.accumulate(uy)
        slope = 1.0
        if len(ux) >= 2:
            start = ux[0] + (1 - tail_fraction) * (ux[-1] - ux[0])
            sel = ux >= start
            if sel.sum() < 2:
                sel = np.zeros_like(ux, dtype=bool)
                sel[-2:] = True
            dx = ux[sel][-1] - ux[sel][0]
            slope = float((uy[sel][-1] - uy[sel][0]) / dx) if dx > 0 else 1.0
            slope = max(slope, 0.0) or 1.0
        return cls(x=ux, y=uy, tail_slope=slope)

    def __call__(self, x_new) -> np.ndarray:
        x_new = np.asarray(x_new, dtype=float)
        out = np.interp(x_new, self.x, self.y)
        beyond = x_new > self.x[-1]
        out[beyond] = self.y[-1] + self.tail_slope * (x_new[beyond] - self.x[-1])
        return out


def apply_adp_fallback(draft_ids: list[str], adp: pd.DataFrame, value_rank: pd.Series,
                       params: AdpFallbackParams, pool_size: int) -> tuple[pd.DataFrame, list[str]]:
    """Her draft edilebilir oyuncuya ``adp_eff``, ``adp_status``, ``sigma_mult`` atar.

    ``draft_ids``: draft havuzundaki oyuncular (projeksiyonu veya ADP satırı olanlar).
    ``value_rank``: projeksiyonu olan oyuncular için dengeli Z-değer sırası.
    Dönüş: ``player_id`` index'li tablo ve notlar. ADP'si ve değeri olmayan
    oyuncular tablodan çıkarılır (notlarda raporlanır).
    """
    notes: list[str] = []
    a = adp.set_index("player_id") if len(adp) else pd.DataFrame(index=pd.Index([], name="player_id"))
    df = pd.DataFrame(index=pd.Index(list(draft_ids), name="player_id"))
    for col in ("adp", "adp_std", "adp_min", "adp_max", "pct_drafted", "default_rank"):
        df[col] = a[col].reindex(df.index).astype(float) if col in a else np.nan
    df["value_rank"] = value_rank.reindex(df.index).astype(float)

    no_info = df["adp"].isna() & df["value_rank"].isna()
    if no_info.any():
        notes.append(f"ADP'si ve projeksiyonu olmayan {int(no_info.sum())} oyuncu havuz dışı")
        df = df[~no_info].copy()

    tau = float(params.pct_drafted_threshold)
    has_adp = df["adp"].notna()
    pct = df["pct_drafted"]
    ok = has_adp & (pct.isna() | (pct >= tau)) & (df["adp"] <= params.coverage_limit)

    fit_mask = ok & df["value_rank"].notna()
    if fit_mask.sum() >= 2:
        iso = IsotonicMap.fit(df.loc[fit_mask, "value_rank"], df.loc[fit_mask, "adp"],
                              params.extrapolation_tail_fraction)
        df["adp_hat"] = np.where(df["value_rank"].notna(), iso(df["value_rank"].fillna(0)), np.nan)
    else:
        notes.append("İzotonik eşleme için yeterli 'ok' ADP yok — Â = değer sırası")
        df["adp_hat"] = df["value_rank"]

    status = pd.Series("ok", index=df.index, dtype=object)
    eff = df["adp"].copy()

    low = has_adp & ~ok
    status[low] = "low_confidence"
    w = (pct / tau).clip(0, 1).fillna(params.low_confidence_default_w)
    blended = w * df["adp"] + (1 - w) * df["adp_hat"]
    eff[low] = blended[low].fillna(df["adp"][low])

    missing = ~has_adp
    is_tail = missing & (df["value_rank"] > pool_size)
    imputed = missing & ~is_tail
    status[imputed] = "imputed"
    eff[imputed] = df.loc[imputed, "adp_hat"]
    if is_tail.any():
        base = float(eff[~is_tail].max()) if (~is_tail).any() else float(pool_size)
        status[is_tail] = "tail"
        eff[is_tail] = base + (df.loc[is_tail, "value_rank"] - pool_size)

    df["adp_eff"] = eff.astype(float)
    df["adp_status"] = status
    df["sigma_mult"] = status.map(params.sigma_mult).astype(float)
    return df, notes
