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

import requests

from fdo.config import REPO_ROOT
from fdo.inseason.injuries import SOURCE_URL, interpret, parse_cbs

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--html", default=None, help="indirmek yerine kayıtlı HTML dosyasını ayrıştır")
    ap.add_argument("--season-start", default="2026-10-20")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    captured = dt.datetime.now(dt.timezone.utc)
    if args.html:
        page = Path(args.html).read_text(encoding="utf-8")
    else:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        page = r.text
    df = parse_cbs(page)
    if df.empty:
        print("Sakatlık tablosu bulunamadı (sayfa yapısı değişmiş olabilir).")
        return 1
    start = dt.date.fromisoformat(args.season_start)
    kinds = [interpret(s, start) for s in df["status_text"]]
    df["kind"] = [k for k, _ in kinds]
    df["return_date"] = [d.isoformat() if d else "" for _, d in kinds]
    df["source_url"] = SOURCE_URL
    df["captured_at"] = captured.isoformat(timespec="seconds")
    out = Path(args.out) / f"injuries_cbs_{captured.date().isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"{len(df)} sakatlık kaydı, {df['nba_team'].nunique()} takım → {out}")
    print(df["kind"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
