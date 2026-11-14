"""Sakatlık dönüş gecikmesini ölçer: CBS'in "en erken" tarihi ile oyuncunun gerçekten oynadığı ilk maç.

    python scripts/calibrate_returns.py                # data/real: bütün CBS raporları (arşiv dahil) + NBA maç kayıtları
    python scripts/calibrate_returns.py --list         # gözlemleri tek tek de yaz
    python scripts/calibrate_returns.py --write        # dağılımı ve Q oynama oranını config/returns.yaml'a yaz

Ölçülenler: CBS'in en erken tarihinden sonra kaç takım maçı daha kaçırıldığının dağılımı (``delay_games``, Kaplan–Meier;
dönmeyenler gözlem sonuna kadar sansürlü) ve belirsiz (game time decision, day-to-day, questionable) listelenen
oyuncunun takımının bir sonraki maçında oynama oranı (``questionable_play``). ``--write`` yalnız yeterli gözlem varsa
(``--min`` , varsayılan 30) yazar; model bu değerleri kullanır (``fdo.inseason.injuries.return_pmf`` /
``questionable_play``). Yazılmazsa CBS tarihi kesin sayılır ve Q oyuncu oynar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from fdo.inseason.identity import load_overrides  # noqa: E402
from fdo.inseason.injuries import RETURNS_CONFIG, questionable_play, return_delay, return_pmf  # noqa: E402
from fdo.inseason.returns import (delay_pmf, load_reports, median_delay, observed_returns,  # noqa: E402
                                  questionable_outcomes, return_curve)
from fdo.inseason.roles import load_logs  # noqa: E402
from fdo.trade import load_trade_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--list", action="store_true", help="gözlemleri tek tek yaz")
    ap.add_argument("--write", action="store_true", help="dağılımı ve Q oranını config/returns.yaml'a yaz")
    ap.add_argument("--min", type=int, default=30, help="yazmak için en az gözlem (her ölçü için ayrı)")
    ap.add_argument("--config", default=str(RETURNS_CONFIG))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = load_trade_data(args.data)
    season = next(iter(data.leagues.values())).config.league.season
    logs = load_logs(args.data, season)
    if logs is None:
        print(f"NBA maç kayıtları yok (gamelogs_nba_{season}.csv); ölçülemiyor.")
        return 1
    start = pd.to_datetime(data.schedule["game_date"]).min().date() if data.schedule is not None else data.as_of
    reports = load_reports(args.data)
    obs = observed_returns(reports, logs, data.players, start, load_overrides(args.data))
    print(f"CBS raporları: {len(reports)} gün ({', '.join(str(d) for d, _ in reports)}); "
          f"son maç günü {max(logs['game_date'])}")
    print(f"Gözlem: {len(obs)} 'en erken tarih' (tarihi son maç gününden önce); {int(obs['returned'].sum())} oyuncu döndü, "
          f"{int((~obs['returned']).sum())} henüz dönmedi (sansürlü).")
    if obs.empty:
        return 0
    early = obs[obs["returned"] & (obs["delay_days"] <= 0)]
    print(f"En erken tarihte ya da önce dönen: {len(early)}")
    for unit, label, points in (("games_missed", "takım maçı", (0, 1, 2, 3, 5, 8)), ("delay_days", "gün", (0, 3, 7, 14, 21))):
        curve = return_curve(obs, unit, points)
        cells = " · ".join(f"≤{int(r.k)}: %{100 * r.returned_share:.0f} ({r.at_risk})" for r in curve.itertuples())
        print(f"En erken tarihten sonra en çok k {label} içinde dönme (izlenen): {cells}")
    med = median_delay(obs, "delay_days")
    print(f"Medyan gecikme: {'belirlenemedi (dönüşlerin yarısı henüz gözlenmedi)' if med is None else f'{med:.0f} gün'}")
    print(f"Modelin varsayımı (config/returns.yaml delay_days): {return_delay()} gün")
    pmf = delay_pmf(obs, "games_missed", 10)
    print("Gecikme dağılımı (en erken tarihten sonra k takım maçı daha kaçırma): "
          + " · ".join(f"{k}{'+' if k == 10 else ''}: %{100 * v:.0f}" for k, v in pmf.items()))
    q = questionable_outcomes(reports, logs, data.players, start, load_overrides(args.data))
    rate = float(q["played"].mean()) if len(q) else None
    print(f"Belirsiz listelenip takımının bir sonraki maçında oynayan: "
          + (f"%{100 * rate:.0f} ({int(q['played'].sum())}/{len(q)})" if rate is not None else "gözlem yok"))
    print(f"Modelde şu an: dağılım {'var' if return_pmf(args.config) else 'yok (CBS tarihi kesin)'}, "
          f"Q oynama {questionable_play(args.config):.2f}")
    if args.write:
        path = Path(args.config)
        cfg = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
        wrote = []
        if len(obs) >= args.min:
            cfg["delay_games"] = {int(k): round(float(v), 4) for k, v in pmf.items()}
            wrote.append(f"delay_games ({len(obs)} gözlem)")
        if rate is not None and len(q) >= args.min:
            cfg["questionable_play"] = round(rate, 3)
            wrote.append(f"questionable_play ({len(q)} gözlem)")
        if wrote:
            path.write_text("# scripts/calibrate_returns.py --write ile ölçüldü (CBS raporları + NBA maç kayıtları).\n"
                            + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
            print(f"Yazıldı: {path} → {', '.join(wrote)}")
        else:
            print(f"Yazılmadı: gözlem en az {args.min} olmalı.")
    if args.list:
        for r in obs.sort_values(["report_date", "stated"]).itertuples():
            state = f"ilk maç {r.first_game} ({r.delay_days:+d} gün, {r.games_missed} maç)" if r.returned \
                else f"henüz oynamadı (≥ {r.delay_days} gün, ≥ {r.games_missed} maç)"
            print(f"  {r.report_date} {r.name}: en erken {r.stated} → {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
