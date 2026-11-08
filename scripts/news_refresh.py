"""Haberleri yeniler: CBS (RotoWire) oyuncu haberleri + ESPN, yenileri Claude ile analiz eder (README §13.25).

CBS durağan olarak yalnız son ~30 haberi veriyor; boşluk kalmaması için 2 saatte bir çalıştır (Windows Görev
Zamanlayıcı). Anahtar: ``ANTHROPIC_API_KEY`` ya da depo kökündeki ``.env``. Model: ``FDO_NEWS_MODEL`` (varsayılan
``claude-opus-5-5``).

    python scripts/news_refresh.py
    python scripts/news_refresh.py --max-items 40
"""

from __future__ import annotations

import argparse
import sys

from fdo.config import REPO_ROOT
from fdo.inseason import news
from fdo.trade.data import load_trade_data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--max-items", type=int, default=120, help="bir çalıştırmada en çok analiz edilecek haber")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    res = news.refresh(args.data, load_trade_data(args.data).players, max_items=args.max_items, log=print)
    store = news.load_store(args.data)
    print(f"{res['fetched']} haber okundu, {res['new']} yeni, {res['analyzed']} analiz edildi "
          f"(model {news.model_name()}; toplam maliyet ~${news.cost(store['usage']):.3f})")
    for note in res["notes"]:
        print("Not:", note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
