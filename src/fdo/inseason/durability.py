"""Dayanıklılık: kalan sezon (ROS) maç sayısını oyuncunun beklenen oynama oranıyla sınırlar (README §13.19).

Yahoo'nun kalan sezon projeksiyonu neredeyse her sağlıklı oyuncuya takımının kalan maçlarının tamamını verir;
sakatlık riski yok sayılır ve sık sakatlanan oyuncular dayanıklılara göre değerli görünür. Sezon öncesi
projeksiyonun maç sayısı ise bu riski içerir (ör. Caruso 58/82).

* Önsel oran: sezon öncesi projeksiyon maçı / 82.
* Bu sezon: oynanan maç / takımın oynadığı maç, ``prior_games`` maçlık önselle birleştirilir ve oranı yalnız
  yukarı çekebilir (rotasyona girmiş, her maça çıkan oyuncu). Kaçırılan maçlar düşürmez: güncel sakatlık zaten
  dönüş tarihiyle modellenir, çift sayılmaz.
* Tavan = oran × dönüşten sonraki takım maçı (dönüş tarihi bilinmiyorsa bugünden). ROS maçı tavanı aşıyorsa ROS
  toplamları orantılı küçültülür; maç başı değerler korunur.

Sezon öncesi projeksiyonu olmayan oyuncuya dokunulmaz. Ham dosyalar değişmez; düzeltme bellekte ve açıkça
raporlanır. Sakatlık dönüş tarihlerinden (``apply_injuries``) sonra uygulanır.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from fdo.inseason.injuries import team_games_from
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

SEASON_GAMES = 82
PRIOR_GAMES = 20.0


def apply_durability(data: TradeData, prior_games: float = PRIOR_GAMES) -> TradeData:
    """ROS toplamlarını beklenen oynama oranına göre kısar ve oran tablosunu ekler (yeni ``TradeData``)."""
    if data.schedule is None or prior_games < 0:
        return data
    games = team_games_from(data.schedule)
    stats = {k: v.copy() for k, v in data.stats.items()}
    ros, pre, season = stats[ROS], stats["preseason"]["gp"], stats["season_total"]["gp"]
    inj = data.injuries
    rows = []
    for pid in ros.index:
        gp, pre_gp = float(ros.loc[pid, "gp"]), float(pre.get(pid, np.nan))
        if not (np.isfinite(gp) and gp > 0 and np.isfinite(pre_gp)):
            continue
        team_games = games.get(normalize_team(data.players.loc[pid, "nba_team"] or ""), [])
        played = sum(d < data.as_of for d in team_games)
        start = data.as_of
        if inj is not None and pid in inj.index and inj.loc[pid, "kind"] == "out_until" \
                and not pd.isna(inj.loc[pid, "return_date"]):
            start = max(start, pd.Timestamp(inj.loc[pid, "return_date"]).date())
        left = sum(d >= start for d in team_games)
        prior = min(1.0, max(0.0, pre_gp / SEASON_GAMES))
        seen = min(float(np.nan_to_num(season.get(pid, 0.0))), played)    # takas: eski takımında fazla maç
        rate = max(prior, min(1.0, (prior_games * prior + seen) / (prior_games + played))) \
            if prior_games + played > 0 else prior
        new_gp = min(gp, rate * left)
        if new_gp < gp:
            ros.loc[pid, [*STATS, "gp"]] = ros.loc[pid, [*STATS, "gp"]] * (new_gp / gp)
        rows.append({"player_id": pid, "preseason_rate": prior, "season_gp": seen, "team_played": played,
                     "rate": rate, "games_left": left, "ros_gp_before": gp, "ros_gp_after": new_gp})
    if not rows:
        return data
    table = pd.DataFrame(rows).set_index("player_id")
    cut = table["ros_gp_after"] < table["ros_gp_before"] - 1e-9
    sources = {**data.sources, "durability": {"kind": "durability", "basis": "preseason projected_gp / 82",
                                              "prior_games": prior_games, "rows": int(cut.sum())}}
    note = (f"Dayanıklılık uygulandı: {int(cut.sum())} oyuncunun kalan sezon maçı sezon öncesi oynama oranıyla "
            f"sınırlandı (toplam {table['ros_gp_before'].sum():.0f} → {table['ros_gp_after'].sum():.0f} maç).")
    return dataclasses.replace(data, stats=stats, sources=sources, durability=table,
                               fingerprint=f"{data.fingerprint}:dur{int(cut.sum())}", issues=(*data.issues, note))
