"""Kaydedilen tekliflerin cevaplarına göre kabul oranı: kabul gerekçesi düzeyi ve rakibin gözündeki oran grupları.

    python scripts/calibrate_thresholds.py                 # data/real/decisions (bütün ligler)
    python scripts/calibrate_thresholds.py --league 93992

Teklifler Takas Analizi'nde "Teklif ettim" ile, cevaplar aynı listeden kaydedilir (karar günlüğü; sunucuda kullanıldıysa
betik sunucudaki veri dizininde çalıştırılır). Betik eşikleri değiştirmez; grup başına sayıyı ve oranı gösterir.
Kodda kullanılan eşikler: kendi gözünde eşit sayılma 0,95 (``PERCEIVED_EVEN``), piyasa bandı üstü 1,25 (``max_view``),
karşılıklı faydada alt sınır 0,80 (``min_view``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdo.evaluation.decisions import DecisionLog  # noqa: E402
from fdo.evaluation.offers import acceptance, offers  # noqa: E402

MIN_N = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--league", default=None)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = offers(DecisionLog(args.data).entries("user_reported"), args.league)
    answered = [r for r in rows if r["outcome"] != "pending"]
    print(f"Teklif: {len(rows)} ({len(answered)} cevaplı, {len(rows) - len(answered)} bekliyor)")
    for name, title in (("acceptability", "Kabul gerekçesi"), ("perceived_view", "Rakibin gözünde")):
        print(f"\n{title}:")
        for g in acceptance(rows)[name]:
            note = "" if g["n"] >= MIN_N else f"  (az kayıt: {MIN_N}'dan az, oran belirsiz)"
            print(f"  {g['group']:>12s}: {g['accepted']}/{g['n']} kabul (%{100 * g['rate']:.0f}){note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
