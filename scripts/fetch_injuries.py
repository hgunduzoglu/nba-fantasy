"""CBS Sports NBA sakatlık raporunu indirir ve ``data/real/injuries_cbs_<tarih>.csv`` olarak yazar (README §13.16).

Kişisel kullanım; dosya yerelde kalır (``.gitignore``). ESPN sayfası otomatik isteği reddettiği için CBS
kullanılır. Durum metinleri (``Expected to be out until at least Nov 22`` vb.) ``fdo.inseason.injuries``
tarafından dönüş tarihine çevrilir.

    python scripts/fetch_injuries.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from fdo.config import REPO_ROOT
from fdo.inseason.injuries import fetch_cbs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--html", default=None, help="indirmek yerine kayıtlı HTML dosyasını ayrıştır")
    ap.add_argument("--season-start", default="2026-10-20")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    page = Path(args.html).read_text(encoding="utf-8") if args.html else None
    try:
        out, df = fetch_cbs(args.out, dt.date.fromisoformat(args.season_start), page)
    except ValueError as e:
        print(e)
        return 1
    print(f"{len(df)} sakatlık kaydı, {df['nba_team'].nunique()} takım → {out}")
    print(df["kind"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
