"""ADP güven sınıfları ve imputasyon (README §5.6).

Bu, değerin ADP'ye sızdığı **tek** yerdir: ADP'si olmayan oyuncunun efektif ADP'si
dengeli Z-değer sırasından türetilir.

| adp_status       | A_i                                                   | σ çarpanı |
|------------------|-------------------------------------------------------|-----------|
| ok               | adp                                                   | 1.0       |
| low_confidence   | w·adp + (1−w)·Â                                       | 1.5       |
| imputed / tail   | ``missing_adp_policy``'ye göre (aşağıda)              | 2.0       |

``missing_adp_policy``:

* ``after_coverage`` (varsayılan): ADP kaynağında listelenmeyen ya da az draft edilen oyuncu
  pratikte kaynağın kapsadığı pick'lerde (çoğu ligde) seçilmiyordur. ``Â`` bu oyuncular için
  kapsamın **sonrasıdır**, değer sırasıyla: ``Â = max(gözlenen adp) + (ok olmayanlar arasındaki
  değer sırası)``. ``imputed``/``tail`` için ``A = Â``; ``low_confidence`` harmanı aynen
  ``w·adp + (1−w)·Â`` (``w = pct/τ``: oyuncunun liglerin ``pct``'sinde ADP civarında, kalanında
  kapsam sonrasında gitmesi). Böylece k. en küçük efektif ADP ≈ k korunur (ADP'si 123'te biten
  bir kaynakla 208 pick'lik ligde imputasyonun kapsam içine sıkışmasını önler).
* ``isotonic`` (README'nin ilk şartnamesi): ``imputed`` için ``Â`` (değer sırası → ADP izotonik
  eşlemesi), ``tail`` için ``max(A) + (değer sırası − N)``.

Her iki politikada da ``status``: değer sırası ≤ N → ``imputed``, aksi hâlde ``tail``.
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


def _tail_slope(x: np.ndarray, y: np.ndarray, tail_fraction: float) -> float:
    """Son ``tail_fraction``'lık x diliminde ham noktalara en küçük kareler eğimi.

    PAV basamaklarının uç noktaları gürültülü olduğundan eğim noktalardan fit edilir.
    Pozitif bir eğim bulunamazsa 1.0 (sıra → sıra) kullanılır.
    """
    if len(x) < 2 or x[-1] <= x[0]:
        return 1.0
    sel = x >= x[0] + (1 - tail_fraction) * (x[-1] - x[0])
    if sel.sum() < 3:
        sel = np.zeros_like(x, dtype=bool)
        sel[-min(len(x), 3):] = True
    xs, ys = x[sel], y[sel]
    var = float(np.var(xs))
    slope = float(np.cov(xs, ys, bias=True)[0, 1] / var) if var > 0 else 0.0
    return slope if slope > 0 else 1.0


@dataclass(frozen=True)
class IsotonicMap:
    """``x → y`` monoton eşlemesi; kapsam ötesine doğrusal uzatma."""

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
        return cls(x=ux, y=uy, tail_slope=_tail_slope(x, y, tail_fraction))

    def __call__(self, x_new) -> np.ndarray:
        x_new = np.asarray(x_new, dtype=float)
        out = np.interp(x_new, self.x, self.y)
        beyond = x_new > self.x[-1]
        out[beyond] = self.y[-1] + self.tail_slope * (x_new[beyond] - self.x[-1])
        return out

    def inverse(self) -> "IsotonicMap":
        """``y → x`` ters eşleme (aynı ``y`` basamakları için ``x`` ortalaması).

        Uzatma eğimi ileri eğimin tersidir.
        """
        uy, inv = np.unique(self.y, return_inverse=True)
        ux = np.bincount(inv, weights=self.x) / np.bincount(inv)
        return IsotonicMap(x=uy, y=np.maximum.accumulate(ux), tail_slope=1.0 / self.tail_slope)


def value_to_adp_map(value_rank, adp, tail_fraction: float = 0.2) -> IsotonicMap:
    """Dengeli değer sırası → ADP monoton eşlemesi.

    Fit ``ADP → değer sırası`` yönünde yapılıp ters çevrilir: ``ok`` sınıfı
    ``adp ≤ coverage_limit`` ile seçildiği için seçim ADP üzerindedir; ADP'yi
    regresör yapmak bu kesilmenin eşlemeyi ve uzatma eğimini yanlı kılmasını önler.
    """
    return IsotonicMap.fit(adp, value_rank, tail_fraction).inverse()


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

    if params.missing_adp_policy not in ("after_coverage", "isotonic"):
        raise ValueError(f"missing_adp_policy: after_coverage | isotonic ({params.missing_adp_policy!r})")

    fit_mask = ok & df["value_rank"].notna()
    if fit_mask.sum() >= 2:
        iso = value_to_adp_map(df.loc[fit_mask, "value_rank"], df.loc[fit_mask, "adp"],
                               params.extrapolation_tail_fraction)
        df["adp_hat"] = np.where(df["value_rank"].notna(), iso(df["value_rank"].fillna(0)), np.nan)
    else:
        notes.append("İzotonik eşleme için yeterli 'ok' ADP yok — Â = değer sırası")
        df["adp_hat"] = df["value_rank"]

    missing = ~has_adp
    low = has_adp & ~ok
    if params.missing_adp_policy == "after_coverage":
        # Â: kaynağın kapsamı (gözlenen en büyük ADP) + ok olmayanlar arasındaki değer sırası
        edge = float(df.loc[has_adp, "adp"].max()) if has_adp.any() else 0.0
        not_ok = (low | missing) & df["value_rank"].notna()
        df.loc[not_ok, "adp_hat"] = (edge + float(params.after_coverage_offset)
                                     + df.loc[not_ok, "value_rank"].rank(method="first"))
        df.loc[ok, "adp_hat"] = np.nan

    status = pd.Series("ok", index=df.index, dtype=object)
    eff = df["adp"].copy()

    status[low] = "low_confidence"
    w = (pct / tau).clip(0, 1).fillna(params.low_confidence_default_w).clip(lower=params.low_confidence_w_min)
    blended = w * df["adp"] + (1 - w) * df["adp_hat"]
    eff[low] = blended[low].fillna(df["adp"][low])

    is_tail = missing & (df["value_rank"] > pool_size)
    imputed = missing & ~is_tail
    status[imputed] = "imputed"
    status[is_tail] = "tail"
    if params.missing_adp_policy == "after_coverage":
        eff[missing] = df.loc[missing, "adp_hat"]
    else:
        eff[imputed] = df.loc[imputed, "adp_hat"]
        if is_tail.any():
            base = float(eff[~is_tail].max()) if (~is_tail).any() else float(pool_size)
            eff[is_tail] = base + (df.loc[is_tail, "value_rank"] - pool_size)

    df["adp_eff"] = eff.astype(float)
    df["adp_status"] = status
    df["sigma_mult"] = status.map(params.sigma_mult).astype(float)
    return df, notes
