"""Yahoo'dan güncel veriyi çeker: kadrolar, haftanın skorları, biten haftalar, puan durumu, alım hakkı, FAB,
waiver listesi, (``--no-players`` verilmezse) oyuncu projeksiyonları ve CBS sakatlık raporu (README §13.20).

Önce bir kez ``python scripts/yahoo_login.py`` ile giriş yapılmış olmalı. Dosyalar ``data/real`` altında kalır.
Her sabah otomatik çalıştırmak için Windows Görev Zamanlayıcı'ya bu komutu ekle.

    python scripts/yahoo_sync.py
    python scripts/yahoo_sync.py --no-players     # hızlı: projeksiyon sayfaları hariç
"""

from __future__ import annotations

import argparse
import sys
import time

from fdo.config import REPO_ROOT
from fdo.ingest.yahoo_sync import Fetcher, NotLoggedIn, sync
from fdo.inseason.injuries import refresh_cbs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--no-players", action="store_true", help="oyuncu projeksiyon sayfalarını atla")
    ap.add_argument("--no-injuries", action="store_true", help="CBS sakatlık raporunu güncelleme")
    ap.add_argument("--delay", type=float, default=0.8, help="istekler arası bekleme (sn)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    t0 = time.time()
    try:
        fetch = Fetcher(delay=args.delay)
        res = sync(args.out, fetch, players=not args.no_players, log=print)
    except NotLoggedIn as e:
        print(e)
        return 2
    except RuntimeError as e:
        print(f"Senkronizasyon durdu, dosyalara dokunulmadı: {e}")
        return 1
    print(f"{res.pages} sayfa, {time.time() - t0:.0f} sn · tarih {res.as_of} · yazılan: {', '.join(res.written)}")
    for note in res.notes:
        print("Not:", note)
    if not args.no_injuries:
        print(refresh_cbs(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
