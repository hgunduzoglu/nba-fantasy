"""Yerel snapshot'tan takas analizi; Yahoo'ya işlem göndermez.

python scripts/analyze_trade.py --league 220594 --team-a 4 --team-b 1 --give-a 5352 --give-b 6014
Oyuncu kimlikleri güncel kadrolarda bulunmalı. --auto-balance eşit olmayan paketleri tamamlar.
"""
import argparse
from pathlib import Path

from fdo.trade import TradeEngine, TradeRequest, load_trade_data
from fdo.trade.report import export_result
from fdo.trade.strategy import PRESETS, Strategy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", default="data/real")
    p.add_argument("--league", required=True)
    p.add_argument("--team-a", required=True)
    p.add_argument("--team-b", required=True)
    p.add_argument("--give-a", nargs="+", required=True)
    p.add_argument("--give-b", nargs="+", required=True)
    p.add_argument("--strategy-a", choices=list(PRESETS), default="Dengeli")
    p.add_argument("--strategy-b", choices=list(PRESETS), default="Dengeli")
    p.add_argument("--auto-balance", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    engine = TradeEngine(load_trade_data(args.data), args.league)
    req = TradeRequest(args.team_a, args.team_b, tuple(args.give_a), tuple(args.give_b),
                       auto_drop=args.auto_balance, auto_fill=args.auto_balance)
    result = engine.analyze(req, strategy_a=Strategy.preset(args.strategy_a), strategy_b=Strategy.preset(args.strategy_b))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(export_result(engine, result), encoding="utf-8")
    print(result.metrics.to_string())


if __name__ == "__main__":
    main()
