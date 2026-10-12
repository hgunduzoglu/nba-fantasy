"""Bot ve simülasyonlar için vektörleştirilmiş oyuncu evreni.

Draft havuzundaki (``Dataset.adp``) her oyuncu bir indekse sahiptir. Dizi
tabanlı bu temsil, ``(simülasyon × oyuncu)`` boyutlu hızlı seçim için kullanılır.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.ingest.load import Dataset
from fdo.roster.eligibility import position_key
from fdo.types import POSITIONS
from fdo.valuation import value_players
from fdo.valuation.pool import value_rank


@dataclass
class BotUniverse:
    ids: np.ndarray                 # (n,) player_id
    index: dict[str, int]
    adp: np.ndarray                 # A_i (adp_eff)
    sigma: np.ndarray               # σ_i (sınıf çarpanı dahil, profil çarpanı hariç)
    default_rank: np.ndarray        # AutoDrafter sırası (yoksa A)
    value_rank: np.ndarray          # dengeli Z-değer sırası (projeksiyonsuz → A)
    punt_rank: np.ndarray           # (n_cat, n): kategori c punt edilmiş değer sırası
    zcat: np.ndarray                # (n, n_cat) dengeli z (projeksiyonsuz → 0)
    has_proj: np.ndarray            # (n,) bool
    status: np.ndarray              # adp_status
    group: np.ndarray               # (n,) pozisyon grubu indeksi
    groups: list[frozenset[str]]
    pure_pos: np.ndarray            # (n,) saf pozisyon indeksi (POSITIONS) ya da -1
    categories: tuple[str, ...]

    @property
    def n(self) -> int:
        return len(self.ids)

    def idx(self, player_ids) -> np.ndarray:
        return np.array([self.index[p] for p in player_ids], dtype=np.int64)


def player_sigma(adp_tab: pd.DataFrame, config: Config) -> np.ndarray:
    """``σ_i = mult · min(σ_cap, max(σ_floor, adp_std))`` (varsa), yoksa ``mult · min(σ_cap, σ₀ + σ₁·A)``.

    ``σ_cap`` olmadan σ ADP ile sınırsız büyür ve ADP'si havuzun çok ötesindeki
    (tail) oyuncular t-kuyruğu yüzünden ilk turlarda seçilebilir (ilk gerçekçilik raporu).
    """
    b = config.model.bots
    a = adp_tab["adp_eff"].to_numpy(float)
    std = adp_tab["adp_std"].to_numpy(float) if "adp_std" in adp_tab else np.full(len(a), np.nan)
    mult = adp_tab["sigma_mult"].to_numpy(float)
    base = np.where(np.isnan(std), b.sigma0 + b.sigma1 * a, np.maximum(b.sigma_floor, np.nan_to_num(std)))
    return mult * np.minimum(b.sigma_cap, base)


def build_universe(dataset: Dataset, config: Config) -> BotUniverse:
    tab = dataset.adp
    ids = np.array(tab.index, dtype=object)
    a = tab["adp_eff"].to_numpy(float)
    cats = tuple(config.categories)

    val = value_players(dataset.projections, config, method="z")
    z = val.scores.reindex(ids)
    has_proj = z.notna().all(axis=1).to_numpy()
    zcat = np.nan_to_num(z.to_numpy(float))

    vr = val.table["rank"].reindex(ids).to_numpy(float)
    vrank = np.where(has_proj, vr, a)
    punt = np.empty((len(cats), len(ids)))
    zs = val.scores
    for j, c in enumerate(cats):
        v = zs.drop(columns=[c]).sum(axis=1)
        punt[j] = np.where(has_proj, value_rank(v).reindex(ids).to_numpy(float), a)

    dr = tab["default_rank"].to_numpy(float) if "default_rank" in tab else np.full(len(ids), np.nan)
    default_rank = np.where(np.isnan(dr), a, dr)

    pos = dataset.positions().reindex(ids)
    keys = [position_key(p) for p in pos]
    uniq = sorted(set(keys), key=lambda k: (k.count(","), [POSITIONS.index(x) for x in k.split(",")]))
    gidx = {k: i for i, k in enumerate(uniq)}
    groups = [frozenset(k.split(",")) for k in uniq]
    pure = np.array([POSITIONS.index(k) if "," not in k else -1 for k in keys], dtype=np.int64)

    return BotUniverse(
        ids=ids, index={p: i for i, p in enumerate(ids)}, adp=a, sigma=player_sigma(tab, config),
        default_rank=default_rank, value_rank=vrank, punt_rank=punt, zcat=zcat, has_proj=has_proj,
        status=tab["adp_status"].to_numpy(object), group=np.array([gidx[k] for k in keys]),
        groups=groups, pure_pos=pure, categories=cats,
    )
