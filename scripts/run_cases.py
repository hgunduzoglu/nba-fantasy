"""Referans vakaları güncel veri ve kodla çalıştırır ve sonucu kaydeder (``fdo.evaluation.cases``).

    python scripts/run_cases.py                                  # data/real/cases.json → data/real/evaluation/
    python scripts/run_cases.py --compare eski.json yeni.json    # iki kaydın farkı

Vaka ve sonuç dosyaları kişisel lig verisi içerir; ``data/real`` altında, git dışında kalır.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdo.evaluation.cases import compare, load_cases, record, run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "real"))
    ap.add_argument("--cases", default=None, help="varsayılan: <data>/cases.json")
    ap.add_argument("--out-dir", default=None, help="varsayılan: <data>/evaluation")
    ap.add_argument("--compare", nargs=2, metavar=("ESKI", "YENI"))
    args = ap.parse_args()
    if args.compare:
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        print("\n".join(compare(old, new)))
        return 0
    from fastapi.testclient import TestClient

    from fdo.api.app import create_app

    data = Path(args.data)
    cases = load_cases(args.cases or data / "cases.json")
    app = create_app(data_dir=data, frontend_dir=data / "_no_frontend")
    state = app.state.fdo
    results = run(TestClient(app), cases)
    rec = record(results, data_signature=state.signature(), as_of=str(state.data().as_of))
    out_dir = Path(args.out_dir) if args.out_dir else data / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = rec["created_at"].replace(":", "").replace("-", "")[:15]
    path = out_dir / f"cases_{rec['data_as_of']}_{rec['code']['commit']}{'-dirty' if rec['code']['dirty'] else ''}_{stamp}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = 0
    for c in results:
        checks = c.get("checks", [])
        bad = [e for e in checks if e.get("ok") is not True]
        failed += bool(bad)
        state_txt = f"HTTP {c['status']}" if c["status"] != 200 else f"{c['result']['n_suggestions']} öneri"
        print(f"[{c['id']}] {state_txt}; beklenti {len(checks) - len(bad)}/{len(checks)}")
        for e in bad:
            print(f"    ✗ {e.get('reason', e)}")
    print(f"→ {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
