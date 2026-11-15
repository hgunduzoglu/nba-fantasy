"""İleriye dönük test: arşivdeki bir günün verisiyle modelin tahmini, sonra gerçekleşenle (``fdo.evaluation.forward``).

    python scripts/backtest_forward.py --day 2026-10-31 --league 93992 --team 7 --model <frozen-model-dir>
    # Yalnız oyuncu düzeyi: yukarıdaki komuta --no-pairs ekle.

Oyuncu düzeyinde beklenen maç ve değer gerçekleşenle karşılaştırılır; dönüş bekleyen sakatlarda ölçülmüş gecikme
dağılımı (``config/returns.yaml``) ile CBS tarihini kesin sayan varsayım yan yana. Takas düzeyinde takımın bütün 1'e 1
takaslarında modelin puanı ve oyuncu tahmini, pencerede gerçekleşen değer farkıyla (işaret uyumu, sıra korelasyonu).
Sonuç ``<veri>/evaluation/forward_<gün>_<lig>_<takım>.json`` (git dışı). Dağılım aynı raporlardan ölçüldüyse sakat
karşılaştırması örneklem içidir. Bu yüzden --model zorunludur: modelin trained_through tarihi karar gününden
önce olmalı. Sonuç oyuncu değeri yönünü ölçen teşhis raporudur; tam takas karar faydası değildir.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from fdo.api.state import AppState  # noqa: E402
from fdo.evaluation.forward import (forecast, pair_test, realized, replay_model, snapshot_dir, snapshot_id, summary, value,  # noqa: E402
                                    value_scales)
from fdo.config import load_config  # noqa: E402
from fdo.inseason.identity import load_overrides  # noqa: E402
from fdo.inseason.roles import load_logs  # noqa: E402
from fdo.trade import TradeEngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--day", required=True, help="arşivdeki kopyanın günü (snapshots/<gün>)")
    ap.add_argument("--league", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--no-pairs", action="store_true", help="takas düzeyini atla (hızlı)")
    ap.add_argument("--model", required=True, help="karardan önce eğitilmiş dondurulmuş model dizini (manifest.json)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    day = dt.date.fromisoformat(args.day)
    model_dir = Path(args.model)
    model_meta = replay_model(model_dir, day)
    with tempfile.TemporaryDirectory() as tmp:
        work = snapshot_dir(args.data, day, Path(tmp) / "data")
        st = AppState(work, config=load_config(model_dir / "league.yaml", model_dir / "model.yaml"),
                      returns_config=model_dir / "returns.yaml")
        st.decisions.enabled = False
        eng = st.engine(args.league)                                       # ölçülmüş gecikme dağılımıyla (varsa)
        plain = TradeEngine(st.data(True, delay=0), args.league)           # CBS tarihi kesin
        start = eng.data.as_of
        season = next(iter(eng.data.leagues.values())).config.league.season
        logs = load_logs(args.data, season)
        end = max(logs["game_date"])
        real, missing = realized(logs, eng.data.players, start, end, load_overrides(args.data))
        fc, fc0 = forecast(eng, start, end), forecast(plain, start, end)
        real = real.reindex(fc.index).fillna(0.0)
        scales = value_scales(real)
        vr, vf, vf0 = value(real, scales), value(fc, scales), value(fc0.reindex(fc.index).fillna(0.0), scales)
        ret = fc.index[fc["returning"].astype(bool)]
        out = {"day": str(start), "end": str(end), "days": (end - start).days + 1, "league": args.league,
               "data_snapshot_id": snapshot_id(work), "model_version": model_meta["model_version"],
               "trained_through": model_meta["trained_through"], "policy_version": model_meta["policy_version"],
               "evaluation_scope": "player_value_direction_diagnostic",
               "team": args.team, "players": len(fc), "unresolved_log_names": missing,
               "games_mae": float((fc["games"] - real["games"]).abs().mean()),
               "games_mae_no_delay": float((fc0["games"].reindex(fc.index) - real["games"]).abs().mean()),
               "value_spearman": float(vf.rank().corr(vr.rank())),
               "returning": {"n": len(ret), "realized_games": float(real.loc[ret, "games"].sum()),
                             "forecast_games": float(fc.loc[ret, "games"].sum()),
                             "forecast_games_no_delay": float(fc0["games"].reindex(ret).sum()),
                             "mae": float((fc.loc[ret, "games"] - real.loc[ret, "games"]).abs().mean()) if len(ret) else None,
                             "mae_no_delay": float((fc0["games"].reindex(ret) - real.loc[ret, "games"]).abs().mean())
                             if len(ret) else None}}
        print(f"Pencere {out['day']} → {out['end']} ({out['days']} gün), {out['players']} oyuncu; maç kaydında kimliği "
              f"bulunamayan ad: {missing}")
        print(f"Maç tahmini hatası (oyuncu başına ortalama mutlak): {out['games_mae']:.2f} "
              f"(CBS tarihi kesin: {out['games_mae_no_delay']:.2f})")
        r = out["returning"]
        if r["n"]:
            print(f"Dönüş bekleyen {r['n']} sakat: gerçekleşen {r['realized_games']:.0f} maç; tahmin "
                  f"{r['forecast_games']:.1f} (gecikme dağılımıyla) / {r['forecast_games_no_delay']:.1f} (CBS tarihi kesin); "
                  f"hata {r['mae']:.2f} / {r['mae_no_delay']:.2f}")
        print(f"Oyuncu değeri sıra korelasyonu (tahmin ↔ gerçekleşen): {out['value_spearman']:.2f}")
        if not args.no_pairs:
            pairs = pair_test(eng, args.team, vf, vr)
            out["pairs"] = summary(pairs)
            p = out["pairs"]
            if p["n"]:
                print(f"1'e 1 takaslar ({p['n']}): işaret uyumu model %{100 * p['model_sign']:.0f}, oyuncu tahmini "
                      f"%{100 * p['forecast_sign']:.0f}; sıra korelasyonu model {p['model_spearman']:.2f}, oyuncu tahmini "
                      f"{p['forecast_spearman']:.2f}")
    dest = Path(args.data) / "evaluation" / f"forward_{args.day}_{args.league}_{args.team}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=lambda x: None if x is np.nan else str(x)),
                    encoding="utf-8")
    print(f"Yazıldı: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
