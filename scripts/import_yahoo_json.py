"""Yahoo JSON dışa aktarımlarını şemaya uygun CSV'lere ve manifest'lere çevirir (README §5.2–§5.4).

Eşleştirme ve dönüşüm ``fdo.ingest.yahoo`` içindedir. Çıktılar ``data/real/`` (git'e girmez)
ve ``data/manifests/`` altına yazılır; ham JSON'lar ``data/real/raw/`` altına taşınır.
Manifest'lerde ``license_status: unknown`` yazılır: kaynağın kullanım şartlarını okuyup kararı
**kullanıcı** verir (§5.1).

    python scripts/import_yahoo_json.py --players players.json --adp adp.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from fdo.config import REPO_ROOT, load_config
from fdo.ingest import load_dataset
from fdo.ingest.yahoo import convert, manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", default="players.json")
    ap.add_argument("--adp", default="adp.json")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "real"))
    ap.add_argument("--manifests", default=str(REPO_ROOT / "data" / "manifests"))
    ap.add_argument("--adp-field", default="adp_preseason", choices=["adp_preseason", "adp_all", "adp_last7"])
    ap.add_argument("--keep-raw", action="store_true", help="ham JSON'ları taşımak yerine kopyala")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    cfg = load_config()
    P = json.loads(Path(args.players).read_text(encoding="utf-8"))
    A = json.loads(Path(args.adp).read_text(encoding="utf-8"))
    date = min(P["extracted_at"], A["extracted_at"])[:10]
    players, projections, adp, log = convert(P, A, args.adp_field)
    for line in log:
        print(line)

    out = Path(args.out)
    mdir = Path(args.manifests)
    out.mkdir(parents=True, exist_ok=True)
    mdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind, df, src, extracted, note in (
        ("players", players, A["source"], A["extracted_at"], "Kimlik ve pozisyonlar Draft Analysis sayfasından."),
        ("projections", projections, P["source"], P["extracted_at"],
         f"stats_mode={P.get('stats_mode')}; sezon toplamları gp'ye bölünerek maç başına çevrildi."),
        ("adp", adp, A["source"], A["extracted_at"], f"adp = {args.adp_field}; default_rank = xrank."),
    ):
        path = out / f"{kind}_yahoo_{date}.csv"
        df.to_csv(path, index=False)
        m = manifest(kind, path, src, extracted, note, cfg.league.season)
        (mdir / f"{path.name}.yaml").write_text(yaml.safe_dump(m, sort_keys=False, allow_unicode=True),
                                                encoding="utf-8")
        paths[kind] = path
        print(f"{kind:12s} {len(df):4d} satır -> {path.relative_to(REPO_ROOT)}")

    raw = out / "raw"
    raw.mkdir(exist_ok=True)
    for src, tag in ((Path(args.players), "players"), (Path(args.adp), "adp")):
        dst = raw / f"yahoo_{tag}_{date}.json"
        if src.resolve() != dst.resolve():
            (shutil.copy2 if args.keep_raw else shutil.move)(src, dst)
            print(f"ham JSON -> {dst.relative_to(REPO_ROOT)}")

    ds, report = load_dataset(paths["players"], paths["projections"], paths["adp"], config=cfg)
    print(f"\nValidasyon: {report.summary()}")
    for msg in report.errors + report.warnings:
        print("  -", msg[:300])
    if ds is not None:
        print("adp_status dağılımı:", ds.adp["adp_status"].value_counts().to_dict())
    return 0 if ds is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
