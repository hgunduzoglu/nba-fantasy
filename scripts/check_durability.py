"""Uzun sakatlıktan dönen oyuncunun dönüş sonrası oynama oranı, bir önceki sezonun oranıyla (README §13.19, §13.39).

    python scripts/check_durability.py --prev data/real/gamelogs_nba_2024-25.csv --cur data/real/gamelogs_nba_2025-26.csv
    python scripts/check_durability.py --ramp data/real/gamelogs_nba_2024-25.csv data/real/gamelogs_nba_2025-26.csv

``--ramp``: dönüş sonrası ilk maçlarda dakika / sakatlık öncesi dakika (medyan); modelin varsayılanı
(``fdo.inseason.injuries.DEFAULT_RAMP``) bundan alındı.

Dayanıklılık tavanı (``fdo.inseason.durability``) bilinen dönüş tarihinden sonraki maçlara sezon öncesi oynama oranını
uygular. Soru: oran zaten sakatlıkları içerdiği için dönüşten sonra risk iki kez mi sayılıyor? Dönüş sonrası oran önceki
oranla aynıysa risk sabittir (çift sayım yok); 1'e yakınsa sezonun sakatlık "payı" harcanmıştır (çift sayım var).
Önceki sezon oranı sezon öncesi projeksiyonun vekilidir. Oynamak = sahada süre almak (kadro dışı ve DNP kayıp sayılır).
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd


def team_days(df: pd.DataFrame) -> dict[str, list]:
    return {t: sorted(set(g)) for t, g in df.groupby("nba_team")["game_date"]}


def post_return(prev: pd.DataFrame, cur: pd.DataFrame, min_streak: int = 10, min_after: int = 10) -> pd.DataFrame:
    """Bu sezon en az ``min_streak`` takım maçı art arda kaçırıp sonra en az ``min_after`` takım maçı izlenen oyuncular:
    önceki sezon oranı ve dönüş sonrası oran (takım değiştirenler dışarıda)."""
    tp, tc = team_days(prev), team_days(cur)
    rate_prev = {n: len(g) / len(tp[g["nba_team"].iloc[-1]]) for n, g in prev[prev["minutes"] > 0].groupby("name")}
    rows = []
    for name, g in cur[cur["minutes"] > 0].groupby("name"):
        if name not in rate_prev or g["nba_team"].nunique() > 1:
            continue
        days = tc[g["nba_team"].iloc[-1]]
        played = set(g["game_date"])
        idx = [d in played for d in days]
        first = idx.index(True)
        best, run, start = 0, 0, None
        for i in range(first, len(idx)):
            run = 0 if idx[i] else run + 1
            if run > best:
                best, start = run, i - run + 1
        if best < min_streak or start + best > len(idx) - min_after:
            continue
        after = idx[start + best:]
        rows.append({"name": name, "prev_rate": min(rate_prev[name], 1.0), "streak": best,
                     "after_games": len(after), "after_rate": sum(after) / len(after)})
    return pd.DataFrame(rows, columns=["name", "prev_rate", "streak", "after_games", "after_rate"])


def minutes_ramp(logs: pd.DataFrame, min_streak: int = 10, min_minutes: float = 20, games: int = 8
                 ) -> tuple[list[float], int]:
    """En az ``min_streak`` takım maçı kaçırıp dönen, öncesindeki (en çok 15) maçta ort. ≥ ``min_minutes`` dakika
    oynayan oyuncuların dönüşten sonraki k. maçtaki dakikası / öncesindeki ortalama: k = 1..``games`` medyanları ve
    dönüş sayısı (takım değiştirenler dışarıda)."""
    days = {t: sorted(set(g)) for t, g in logs.groupby("nba_team")["game_date"]}
    ratios: list[list[float]] = [[] for _ in range(games)]
    n = 0
    for _, g in logs[logs["minutes"] > 0].groupby("name"):
        if g["nba_team"].nunique() > 1:
            continue
        mins = dict(zip(g["game_date"], g["minutes"]))
        td = days[g["nba_team"].iloc[0]]
        played = [d in mins for d in td]
        first = played.index(True)
        k = first
        while k < len(td):
            if played[k]:
                k += 1
                continue
            j = k
            while j < len(td) and not played[j]:
                j += 1
            before = [mins[d] for d in td[max(first, k - 15):k] if d in mins]
            after = [d for d in td[j:] if d in mins][:games]
            if j - k >= min_streak and len(before) >= 5 and sum(before) / len(before) >= min_minutes                     and len(after) == games:
                n += 1
                base = sum(before) / len(before)
                for i, d in enumerate(after):
                    ratios[i].append(mins[d] / base)
            k = j
    return [float(pd.Series(r).median()) if r else float("nan") for r in ratios], n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prev")
    ap.add_argument("--cur")
    ap.add_argument("--ramp", nargs="+", metavar="LOGS", help="dönüş sonrası dakika artışını bu sezonlarda ölç")
    ap.add_argument("--min-streak", type=int, default=10)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.ramp:
        for path in args.ramp:
            logs = pd.read_csv(path)
            logs["game_date"] = pd.to_datetime(logs["game_date"]).dt.date
            med, n = minutes_ramp(logs, args.min_streak)
            print(f"{path}: {n} dönüş · dakika oranı " + " ".join(f"{i}. %{100 * m:.0f}" for i, m in enumerate(med, 1)))
        return 0
    if not (args.prev and args.cur):
        ap.error("--prev ve --cur ya da --ramp gerekli")
    prev, cur = pd.read_csv(args.prev), pd.read_csv(args.cur)
    for df in (prev, cur):
        df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    r = post_return(prev, cur, args.min_streak)
    r = r[r["prev_rate"] >= .3]
    print(f"{len(r)} oyuncu: önceki sezon oranı ort. {r.prev_rate.mean():.2f}, dönüş sonrası ort. {r.after_rate.mean():.2f}")
    for lo, hi in ((.3, .7), (.7, .85), (.85, 1.01)):
        s = r[(r.prev_rate >= lo) & (r.prev_rate < hi)]
        if len(s):
            print(f"  önceki {lo:.2f}–{hi:.2f}: n={len(s)}, önceki {s.prev_rate.mean():.2f} → dönüş sonrası {s.after_rate.mean():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
