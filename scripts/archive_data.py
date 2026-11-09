"""Değiştirilemez ham veri arşivi (``fdo.ingest.archive``): elle arşivleme, listeleme, doğrulama, geri yükleme.

    python scripts/archive_data.py                       # data/real'in şu anki hâlini arşivle (değişmediyse yeni parti yok)
    python scripts/archive_data.py --list                # partiler: zaman, kaynak, eksik dosyalar
    python scripts/archive_data.py --verify              # bütün nesnelerin özetini doğrula
    python scripts/archive_data.py --restore <parti> <boş dizin>
    python scripts/archive_data.py --legacy              # eski snapshots/<gün>/ kopyalarını parti olarak içe al

Senkronizasyon (``yahoo_sync.py``, uygulamadaki "Yahoo'dan güncelle") ve ``news_refresh.py`` sonunda arşiv kendiliğinden
alınır; elle çalıştırma, dosyaları başka yoldan güncellediğinde gerekir. Arşiv ``data/real/snapshots/`` altında, git
dışında kalır ve sunucuya gönderilmez.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdo.ingest import archive as A  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--note", default="", help="partiye not")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--restore", nargs=2, metavar=("PARTI", "HEDEF"))
    g.add_argument("--legacy", action="store_true")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = Path(args.data)
    if args.list:
        for m in A.batches(data):
            miss = f" · eksik: {', '.join(m['missing'])}" if m["missing"] else ""
            print(f"{m['sequence']:>4} {m['batch_id']}  {m['source']:<22} {len(m['files']):>3} dosya{miss}  {m['note']}")
        return 0
    if args.verify:
        problems = A.verify(data)
        print("\n".join(problems) or f"{len(A.batches(data))} parti sağlam")
        return 1 if problems else 0
    if args.restore:
        out = A.restore(data, args.restore[0], args.restore[1])
        print(f"{len(out)} dosya → {args.restore[1]}")
        return 0
    if args.legacy:
        days = sorted(p for p in (data / "snapshots").glob("*") if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
        for day in days:
            files = sorted(p for p in day.iterdir() if p.is_file())
            r = A.archive(data, source=f"legacy:{day.name}", note=f"eski anlık görüntü klasörü snapshots/{day.name}",
                          files=files)
            print(f"{day.name}: {r.batch_id} ({len(files)} dosya, {r.new_objects} yeni nesne)"
                  + ("" if r.created else " — zaten arşivde"))
        return 0
    r = A.archive(data, source="manual", note=args.note)
    m = A.get(data, r.batch_id)
    print(f"{r.batch_id}: {r.files} dosya, {r.new_objects} yeni nesne" + ("" if r.created else " (değişiklik yok)")
          + (f" · eksik: {', '.join(m['missing'])}" if m["missing"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
