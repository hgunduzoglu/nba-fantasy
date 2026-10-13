"""Yahoo draft sonuçlarını (yapıştırılmış mock sonuç metni ``*.md`` ya da sonuç JSON'u) kalibrasyon
CSV'lerine çevirir (README §13.6).

Her dosya için ``<out>/<ad>.csv``: ``pick, round, fantasy_team, player, nba_team, positions, auto, user``.
``auto``: takım adı ``Team N`` (Yahoo botu). ``user``: kullanıcının takımı (``--user``; JSON için
``--json-user``). Snake sırası ve oyuncu adı eşleşmesi kontrol edilir.

    python scripts/convert_draft_results.py --raw data/real/draft_logs/raw --out data/real/draft_logs \\
        --user Hüsamettin --json-user "New York Hav Havs"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fdo.calibration.bots import league_config
from fdo.config import load_config
from fdo.draft.events import DraftError
from fdo.draft.io import import_names
from fdo.ingest.load import load_data_dir
from fdo.ingest.yahoo import parse_results_text, results_from_json, snake_violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="data/real/draft_logs/raw")
    ap.add_argument("--out", default="data/real/draft_logs")
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--user", default=None, help="mock'lardaki kullanıcı takım adı")
    ap.add_argument("--json-user", default=None, help="JSON draft'taki kullanıcı takım adı")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    base_cfg = load_config()
    ds, rep = load_data_dir(args.data, base_cfg, schedule=False)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for path in sorted(Path(args.raw).iterdir()):
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            body = text.split("```")[1] if "```" in text else text
            m = re.search(r"Takım:\s*(\d+)", text)
            df = parse_results_text(body, args.user, int(m.group(1)) if m else None)
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            df = results_from_json(data, args.json_user)
        else:
            continue
        teams = int(df["pick_in_round"].max())
        rounds = int(df["round"].max())
        issues = snake_violations(df, teams)
        if len(df) != teams * rounds:
            issues.append(f"{len(df)} pick, beklenen {teams * rounds}")
        cfg = league_config(base_cfg, teams, rounds)
        try:
            import_names(df[["pick", "player", "auto", "user"]].to_csv(index=False), ds.players, cfg)
        except DraftError as e:
            issues.append(f"ad eşleşmesi: {e}")
        dst = out / f"{path.stem}.csv"
        df.to_csv(dst, index=False)
        status = "OK" if not issues else "SORUN: " + "; ".join(issues[:5])
        failed += bool(issues)
        print(f"{path.name}: {teams}×{rounds}, bot {int(df['auto'].sum())}, kullanıcı {int(df['user'].sum())} "
              f"-> {dst.name} · {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
