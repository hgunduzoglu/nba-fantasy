"""Oyuncu durumuna göre maç sayısı düzeltmesi (README §5.8).

Durumu ``availability.out_statuses`` içinde olan oyuncunun ``projected_gp``'si
``availability.out_gp_factor`` ile çarpılır. Diğer etiketler (Q, GTD, NA) etkilenmez.
Değerleme ve haftalık matchup vektörleri projeksiyonu buradan geçirerek okur; ham
projeksiyon tablosu değişmez (config değişince veri seti yeniden kurulmaz).
"""

from __future__ import annotations

import pandas as pd

from fdo.config import Config


def out_mask(proj: pd.DataFrame, config: Config) -> pd.Series:
    """Projeksiyon satırı başına "out" maskesi (``injury_status`` kolonu yoksa hepsi False)."""
    if "injury_status" not in proj:
        return pd.Series(False, index=proj.index)
    out = set(config.model.availability.out_statuses)
    return proj["injury_status"].fillna("").astype(str).map(lambda s: bool(out & set(s.split())))


def effective_projections(proj: pd.DataFrame, config: Config) -> pd.DataFrame:
    """``projected_gp``'si durum katsayısıyla düzeltilmiş kopya (gerekmiyorsa aynı tablo)."""
    factor = config.model.availability.out_gp_factor
    mask = out_mask(proj, config)
    if factor == 1.0 or not mask.any():
        return proj
    proj = proj.copy()
    proj.loc[mask, "projected_gp"] = proj.loc[mask, "projected_gp"].astype(float) * factor
    return proj
