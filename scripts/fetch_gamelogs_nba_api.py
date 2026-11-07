"""Bir sezonun oyuncu maç kayıtlarını ``nba_api`` ile indirir (README §13.2).

``nba_api`` opsiyoneldir (``pip install -e ".[nba]"``). Veriyi stats.nba.com'dan çeker;
kullanım şartları kararı **kullanıcınındır** (§5.1) ve manifest'e ``--license-status`` ile
yazılır (varsayılan ``unknown``). Oyuncular ``players.csv``'ye ad ile eşlenir
(``scripts/calibrate_variance.py`` yüklerken ``player_id``'yi çözer).

    python scripts/fetch_gamelogs_nba_api.py --season 2025-26
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

from fdo.config import REPO_ROOT
from fdo.ingest.nba_logs import fetch_season


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", required=True, help="örn. 2025-26")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--license-status", default="unknown",
                    choices=["personal_use_confirmed", "assumed", "unknown"])
    ap.add_argument("--license-notes", default="stats.nba.com kullanım şartları doğrulanmadı (§5.1).")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    try:
        df = fetch_season(args.season)
    except ImportError:
        print('nba_api kurulu değil: pip install -e ".[nba]"')
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"gamelogs_nba_{args.season}.csv"
    df.to_csv(path, index=False)
    manifest = {"file": path.relative_to(REPO_ROOT).as_posix(), "kind": "gamelogs",
                "source_name": "stats.nba.com via nba_api", "source_url": "https://stats.nba.com",
                "retrieved_at": dt.date.today().isoformat(), "retrieved_by": "scripts/fetch_gamelogs_nba_api.py",
                "license_status": args.license_status, "license_notes": args.license_notes,
                "season": args.season, "is_synthetic": False}
    mdir = REPO_ROOT / "data" / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"{path.name}.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                                            encoding="utf-8")
    print(f"{len(df)} maç satırı, {df['name'].nunique()} oyuncu -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
