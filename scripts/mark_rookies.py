"""``players.csv``'ye ``is_rookie`` yazar: verilen game log sezonlarında hiç maçı olmayan oyuncu (README §13.5).

NBA'de son sezonlarda oynamamış oyuncular (rookie, yurt dışından gelen, uzun sakatlıktan dönen)
için rol belirsizliği daha geniştir; senaryolar bu bayrağı kullanır. ``import_yahoo_json.py``
oyuncu dosyasını yeniden yazarsa bu script tekrar çalıştırılmalıdır.

    python scripts/mark_rookies.py --gamelogs data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from fdo.ingest.load import find_data_files, load_data_dir, load_table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gamelogs", required=True, nargs="+")
    ap.add_argument("--data", default="data/real/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    ds, rep = load_data_dir(args.data, schedule=False)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    played: set[str] = set()
    for g in args.gamelogs:
        logs, _, lrep = load_table(g, "gamelogs", players=ds.players, drop_unmatched=True)
        if logs is None:
            print(f"{g} yüklenemedi:", *lrep.errors[:10], sep="\n  - ")
            return 1
        played |= set(logs["player_id"])
    path = find_data_files(args.data)["players"]
    players = pd.read_csv(path, dtype=str, keep_default_na=False)
    players["is_rookie"] = ~players["player_id"].isin(played)
    players.to_csv(path, index=False)
    pool = set(ds.draft_ids)
    flagged = players[players["is_rookie"] & players["player_id"].isin(pool)]
    print(f"{int(players['is_rookie'].sum())} oyuncu is_rookie (draft havuzunda {len(flagged)}) -> {Path(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
