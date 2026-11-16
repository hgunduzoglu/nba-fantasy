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
from fdo.evaluation.forward import (daily_box, ecw_summary, forecast, realized, realized_pair_test,  # noqa: E402
                                    replay_model, snapshot_dir, snapshot_id, summary, value, value_scales)
from fdo.config import load_config  # noqa: E402
from fdo.inseason.identity import load_overrides  # noqa: E402
from fdo.inseason.roles import load_logs  # noqa: E402
from fdo.trade import TradeEngine  # noqa: E402


def write_floor(pairs, source: str) -> str:
    """Hızlı puanın büyüklük dilimlerine göre işaret isabeti ve eşik (``fdo.evaluation.noise``) → config/noise.yaml."""
    import yaml

    from fdo.evaluation.noise import NOISE_CONFIG, agreement_bins, find_floor
    bins = agreement_bins(pairs)
    fl = find_floor(bins)
    cfg = {"strategy_delta_floor": fl, "source": f"forward test {source}",
           "agreement": [{"from": float(b.left), "to": float(b.right), "n": int(n), "sign_agreement": round(float(m), 3)}
                         for b, n, m in zip(bins["bin"], bins["size"], bins["mean"])]}
    NOISE_CONFIG.write_text("# scripts/backtest_forward.py --write-floor ile ölçüldü (gerçekleşen haftalık kategori "
                            "galibiyetine göre işaret isabeti).\n" + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                            encoding="utf-8")
    return f"Eşik {fl} → {NOISE_CONFIG}"


def compare_bases(st, league: str, start, end, scales, vr, pairs, vf_ros) -> dict:
    """Oyuncu tahmini farklı temellerle (``fdo.inseason.scenarios``): gerçekleşen oyuncu değeriyle sıra korelasyonu ve
    1'e 1 takaslarda (alınan − verilen tahmini) gerçekleşen kategori etkisiyle işaret uyumu."""
    from fdo.evaluation.forward import _spearman
    moved = pairs[~np.isclose(pairs["realized_ecw"], 0)]
    out = {}
    for basis in ("ros", "season", "blend"):
        vb = vf_ros if basis == "ros" else value(forecast(st.engine(league, True, basis), start, end), scales)
        vb = vb.reindex(vr.index).fillna(0.0)
        diff = np.array([vb.get(g, 0.0) - vb.get(k, 0.0) for g, k in zip(moved["get"], moved["give"])])
        out[basis] = {"value_spearman": float(vb.rank().corr(vr.rank())),
                      "pair_sign": float((np.sign(diff) == np.sign(moved["realized_ecw"].to_numpy())).mean()),
                      "pair_spearman": _spearman(diff, moved["realized_ecw"].to_numpy())}
    return out


def lineup_sample(st, eng, league: str, team: str, pairs, n: int, seed: int = 7, pairs_window=None) -> dict:
    """Rastgele ``n`` takasın günlük kadro farkı (``fdo.inseason.lineup_rank``) ve aynı alt kümede hızlı puan ile oyuncu
    tahmininin gerçekleşen kategori etkisine göre işaret uyumu. ``pairs_window``: pencerenin günleri verilirse günlük
    kadro farkı yalnız pencerenin haftalarında ölçülür (gerçekleşenle aynı ufuk)."""
    from fdo.evaluation.forward import _spearman
    from fdo.inseason.lineup_rank import LineupMeter
    from fdo.trade import Strategy, TradeRequest
    sim = st.season_sim(league, True)
    moved = pairs[~np.isclose(pairs["realized_ecw"], 0)]
    sample = moved.sample(min(n, len(moved)), random_state=seed).copy()
    span = {sim.weeks.week_of(eng.data.as_of + dt.timedelta(days=k))
            for k in range((max(pairs_window) - eng.data.as_of).days + 1)} if pairs_window else None
    meter = LineupMeter(sim, team, tuple(w for w in span if w) if span else None)
    vals = []
    for r in sample.itertuples():
        pair = {team: Strategy(), r.team_b: Strategy()}
        req = TradeRequest(team, r.team_b, (r.give,), (r.get,), auto_drop=True, auto_fill=True)

        def resolve(req=req, pair=pair):
            rosters, _, il = eng.resolve(req, pair)
            return rosters, il
        d = meter.measure((team, r.team_b), pair, resolve)
        vals.append(np.nan if d is None else d.strategy)
    sample["lineup"] = vals
    sample = sample[np.isfinite(sample["lineup"])]
    sign = lambda col: float((np.sign(sample[col]) == np.sign(sample["realized_ecw"])).mean())
    return {"n": len(sample), "lineup_sign": sign("lineup"), "model_sign": sign("model"), "forecast_sign": sign("forecast"),
            "lineup_spearman": _spearman(sample["lineup"], sample["realized_ecw"]),
            "model_spearman": _spearman(sample["model"], sample["realized_ecw"]),
            "forecast_spearman": _spearman(sample["forecast"], sample["realized_ecw"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--day", required=True, help="arşivdeki kopyanın günü (snapshots/<gün>)")
    ap.add_argument("--league", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--no-pairs", action="store_true", help="takas düzeyini atla (hızlı)")
    ap.add_argument("--pairs-out", help="takas satırlarını bu CSV'ye yaz (gürültü eşiği ölçümü için)")
    ap.add_argument("--write-floor", action="store_true",
                    help="takas farkının sinyal eşiğini (gerçekleşen kategoriye göre işaret isabeti) config/noise.yaml'a yaz")
    ap.add_argument("--bases", action="store_true",
                    help="oyuncu tahminini Yahoo projeksiyonu yanında bu sezonki oranlar ve karma temelle de ölç")
    ap.add_argument("--lineup-sample", type=int, default=0,
                    help="rastgele bu kadar takası günlük kadro farkıyla da ölç (yavaş; 0 = kapalı)")
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
            box = daily_box(logs, eng.data.players, start, end, load_overrides(args.data))
            per_game = (vf / fc["games"].where(fc["games"] > 0)).fillna(0.0)
            pairs = realized_pair_test(eng, args.team, vf, vr, box, per_game)
            out["pairs"] = summary(pairs)
            out["pairs_ecw"] = ecw_summary(pairs)
            if args.pairs_out:
                pairs.to_csv(args.pairs_out, index=False)
            if args.write_floor and len(pairs):
                print(write_floor(pairs, f"{args.day} {args.league}/{args.team} → {end}"))
            if args.bases and len(pairs):
                out["bases"] = compare_bases(st, args.league, start, end, scales, vr, pairs, vf)
                for b, r in out["bases"].items():
                    print(f"Temel {b}: oyuncu değeri sıra korelasyonu {r['value_spearman']:.2f}; takas işaret uyumu "
                          f"(gerçekleşen kategori) %{100 * r['pair_sign']:.0f}, sıra korelasyonu {r['pair_spearman']:.2f}")
            if args.lineup_sample and len(pairs):
                out["lineup_sample"] = lineup_sample(st, eng, args.league, args.team, pairs, args.lineup_sample,
                                                     pairs_window=[end])
                ls = out["lineup_sample"]
                print(f"Günlük kadro farkı, rastgele {ls['n']} takas (gerçekleşen kategori etkisiyle): işaret uyumu "
                      f"günlük kadro %{100 * ls['lineup_sign']:.0f}, hızlı puan %{100 * ls['model_sign']:.0f}, oyuncu tahmini "
                      f"%{100 * ls['forecast_sign']:.0f}; sıra korelasyonu {ls['lineup_spearman']:.2f} / "
                      f"{ls['model_spearman']:.2f} / {ls['forecast_spearman']:.2f}")
            out["evaluation_scope"] = "player_value_direction_and_realized_category_wins"
            p = out["pairs"]
            if p["n"]:
                print(f"1'e 1 takaslar ({p['n']}): işaret uyumu model %{100 * p['model_sign']:.0f}, oyuncu tahmini "
                      f"%{100 * p['forecast_sign']:.0f}; sıra korelasyonu model {p['model_spearman']:.2f}, oyuncu tahmini "
                      f"{p['forecast_spearman']:.2f}")
                e = out["pairs_ecw"]
                print(f"Gerçekleşen kategori galibiyetine göre ({e['n_moved']} takas kadroyu değiştirdi): işaret uyumu "
                      f"model %{100 * e['model_sign']:.0f}, oyuncu tahmini %{100 * e['forecast_sign']:.0f}, gerçekleşen "
                      f"oyuncu değeri %{100 * e['player_value_sign']:.0f}; sıra korelasyonu model {e['model_spearman']:.2f}, "
                      f"oyuncu tahmini {e['forecast_spearman']:.2f}, gerçekleşen oyuncu değeri {e['player_value_spearman']:.2f}")
    dest = Path(args.data) / "evaluation" / f"forward_{args.day}_{args.league}_{args.team}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=lambda x: None if x is np.nan else str(x)),
                    encoding="utf-8")
    print(f"Yazıldı: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
