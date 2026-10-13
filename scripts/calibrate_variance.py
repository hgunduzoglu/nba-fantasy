"""Game log'larından varyans kalibrasyonu (README §13.2).

    python scripts/calibrate_variance.py --gamelogs data/real/gamelogs_nba_2025-26.csv --data data/real/

Çıktılar:
* ``<out>/variance_<kaynak>.csv`` + manifest (``kind: variance``) — UI'da veri setiyle birlikte
  yüklenir; ``uncalibrated: varyans φ`` rozeti kalkar.
* ``reports/variance_calibration.md`` — ``φ_s`` ve kategori korelasyonu; ``config/model.yaml``
  içine yapıştırılacak ``variance.phi`` / ``variance.category_corr`` YAML parçası.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

from fdo.calibration.variance import calibrate
from fdo.config import REPO_ROOT, load_config
from fdo.ingest import load_dataset
from fdo.ingest.load import load_table
from fdo.realism.report import md_table


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gamelogs", required=True)
    ap.add_argument("--data", default="data/real/", help="players/projections (ad eşleme ve ölçekleme)")
    ap.add_argument("--min-games", type=int, default=20)
    ap.add_argument("--min-minutes", type=float, default=5.0)
    ap.add_argument("--n0", type=float, default=10.0, help="φ'ye büzülme gücü (sanal maç)")
    ap.add_argument("--out", default=None, help="variance CSV dizini (varsayılan: --data)")
    ap.add_argument("--report", default="reports/")
    ap.add_argument("--manifests", default=None, help="manifest dizini (varsayılan: <out>/../manifests)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    from run_mock_batch import find_files

    cfg = load_config()
    files = find_files(Path(args.data))
    ds, rep = load_dataset(files["players"], files["projections"], files["adp"], config=cfg)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    logs, man, lrep = load_table(args.gamelogs, "gamelogs", players=ds.players, drop_unmatched=True)
    for w in lrep.warnings:
        print("uyarı:", w)
    if logs is None:
        print("Game log yüklenemedi:", *lrep.errors[:20], sep="\n  - ")
        return 1
    res = calibrate(logs, cfg, min_games=args.min_games, n0=args.n0, min_minutes=args.min_minutes,
                    projections=ds.projections)
    print(f"{res.n_players} oyuncu, {res.n_games} maç")
    print("φ:", {k: round(v, 3) for k, v in res.phi.items()})

    out = Path(args.out or args.data)
    path = out / f"variance_{Path(args.gamelogs).stem}.csv"
    res.variance.to_csv(path, index=False)
    # loader'ın arama sırası: CSV'nin yanındaki manifests/, sonra bir üst dizindeki manifests/
    mdir = Path(args.manifests) if args.manifests else next(
        (d for d in (path.parent / "manifests", path.parent.parent / "manifests") if d.exists()),
        path.parent / "manifests")
    mdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "file": rel(path), "kind": "variance",
        "source_name": f"calibrate_variance ← {man.get('source_name')}", "source_url": man.get("source_url"),
        "retrieved_at": dt.date.today().isoformat(), "retrieved_by": "scripts/calibrate_variance.py",
        "license_status": man.get("license_status", "unknown"),
        "license_notes": f"Türetilmiş veri; kaynak manifest: {man.get('_path')}",
        "season": man.get("season"), "is_synthetic": bool(man.get("is_synthetic", False)),
    }
    (mdir / f"{path.name}.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                                            encoding="utf-8")
    print(f"varyans -> {path}")

    snippet = {"variance": {"phi": {k: round(v, 3) for k, v in res.phi.items()},
                            "category_corr": {a: {b: round(float(res.category_corr.loc[a, b]), 3)
                                                  for b in res.category_corr.columns if b != a}
                                              for a in res.category_corr.index}}}
    rdir = Path(args.report)
    rdir.mkdir(parents=True, exist_ok=True)
    text = (f"# Varyans kalibrasyonu (README §13.2)\n\n- Game log: `{args.gamelogs}` "
            f"({res.n_players} oyuncu, {res.n_games} maç, min_games={args.min_games}, n0={args.n0})\n\n"
            "## Kategori korelasyonu (kazanma yönünde)\n\n" + md_table(res.category_corr.round(3))
            + "\n\n## `config/model.yaml` için\n\n```yaml\n"
            + yaml.safe_dump(snippet, sort_keys=False, allow_unicode=True) + "```\n")
    (rdir / "variance_calibration.md").write_text(text, encoding="utf-8")
    print(f"rapor -> {rdir / 'variance_calibration.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
