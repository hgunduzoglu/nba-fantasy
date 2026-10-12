"""Gerçekçilik raporu: Markdown ve tablolar (README §7)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from fdo.config import Config
from fdo.realism.metrics import RealismMetrics


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}", index: bool = True) -> str:
    """Bağımlılıksız basit Markdown tablo."""
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]

    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else floatfmt.format(v)
        return str(v)

    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def build_report(m: RealismMetrics, config: Config, *, data_label: str = "",
                 is_synthetic: bool = False) -> str:
    p = config.model.realism
    lines = [f"# Gerçekçilik raporu — {m.n_mocks} mock, seed {m.seed}", ""]
    if is_synthetic:
        lines += ["> **SENTETİK VERİ — gerçek oyuncu değeri değildir.**", ""]
    lines += [
        f"- Üretim: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- Veri: {data_label}" if data_label else "- Veri: —",
        f"- Config hash: `{config.config_hash}`",
        "- Bot parametreleri **kalibre edilmemiştir** (`uncalibrated`). Hedefler varsayımdır;",
        "  gerçek draft log'u olmadan botların gerçek insanlara benzediği iddia edilmez.",
        "",
        "## Tur bazında `pick − A`",
        "",
        "Hedef (varsayım): medyan ≈ 0, yayılım tur ilerledikçe artar; erken turlarda uygunsuz",
        f"reach (`z_reach > {p.reach_z_bad}`) < %2 fakat sıfır değil.",
        "",
        md_table(m.rounds.rename(columns={"bad_reach_rate": f"reach>{p.reach_z_bad}σ",
                                          "warn_reach_rate": f"reach {p.reach_z_warn}–{p.reach_z_bad}σ",
                                          "slide_rate": f"slide>{p.slide_z}σ"})),
        "",
        "## Uç reach örneği",
        "",
        f"ADP ∈ [{m.extreme['adp_range'][0]:.0f}, {m.extreme['adp_range'][1]:.0f}] olan "
        f"{m.extreme['n_players']} oyuncunun ilk {config.league.teams} pick'te gitme sıklığı "
        f"(oyuncu×mock başına): **{m.extreme['rate_per_player_mock']:.5f}** "
        f"({m.extreme['hits']} olay). Hedef: ≈ 0 ama > 0 (hard ban yok).",
        "",
        "## Mock çeşitliliği",
        "",
        f"- İlk {p.diversity_top_n} pick kümesi Jaccard ortalaması: {m.diversity['jaccard_mean']:.3f}",
        f"- Ortak oyuncular üzerinde Kendall τ ortalaması: {m.diversity['kendall_tau_mean']:.3f} "
        "(hedef varsayımı: < 0.98)",
        f"- Karşılaştırılan çift: {m.diversity['pairs']}",
        "",
        "## Pozisyon dağılımı (tur bazında pay)",
        "",
        md_table(m.positions),
        "",
        f"13. tur sonunda tamamlanamayan kadro sayısı: **{m.incomplete}** (hedef: 0, feasibility "
        f"{'açık' if config.model.bots.enforce_completion_feasibility else 'kapalı'}).",
        "",
        "## Bot tutarlılığı",
        "",
        f"- Seçilen oyuncunun botun kalıcı algılanan sırasında 1. olma oranı: "
        f"{m.consistency.get('top1_agreement', float('nan')):.3f}",
        f"- Uygun oyuncular arasında ortalama algılanan sıra (0 = ilk): "
        f"{m.consistency.get('mean_perceived_rank', float('nan')):.2f}",
        "",
        "## Profil bazında",
        "",
        md_table(m.profiles),
        "",
        "## En uç 25 reach",
        "",
        md_table(m.worst_reaches, index=False),
        "",
    ]
    if m.external:
        lines += ["## Dış karşılaştırma (KS testi)", ""]
        lines += [f"- {k}: {v}" for k, v in m.external.items()]
        lines.append("")
    return "\n".join(lines)
