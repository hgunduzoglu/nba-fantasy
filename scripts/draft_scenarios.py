"""İlk çift (16/17) × strateji senaryoları: draft sonuna kadar simülasyon ve 13'lü kadrolar (README §13.11).

Her senaryo = ilk turn'de zorlanan bir çift + sonraki turn'ler için bir strateji. Botlar ilk 15 pick'i
çiftin iki oyuncusu da kalacak şekilde oynar (koşullama; çiftin gerçekten kalma olasılığı ayrıca
raporlanır). Kullanıcının sonraki pick'leri advisor'ın miyopik politikasıyla (statik rakiplere karşı
ağırlıklı beklenen galibiyet) seçilir.

Aşamalar:
1. Aday çiftler: 16'da kalma olasılığı ≥ ``--min-avail`` olan, ΔECW'si en yüksek oyuncular + ``--pairs``;
   hepsi dengeli ve uyarlanabilir stratejiyle elenir.
2. En iyi ``--top-pairs`` çift + zorunlu çiftler × tüm stratejiler (CRN: aynı seed).
3. En iyi ``--top`` senaryo yeni simülasyonlarla yeniden ölçülür (kazananın lanetine karşı) ve
   kadroları kaydedilir.

Stratejiler: dengeli; uyarlanabilir (ilk çiftten sonra bir kategori P < 0.33 ise baştan punt, değilse
48/49 dengeli, sonra en zayıf P < 0.40 ise punt); "48/49 dengeli → X" ve "baştan X" (X: tek ve ikili
punt'lar, kadroya göre 1.25/1.5/0.5 ağırlıklı karışımlar).

    python scripts/draft_scenarios.py --out reports/draft_senaryolari.xlsx \\
        --pairs "Scottie Barnes+Karl-Anthony Towns" "Karl-Anthony Towns+Jamal Murray"
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.types import CATEGORY_LABELS

BROKEN_AFTER_PAIR = 0.33
BROKEN_LATER = 0.40
DOUBLE_PUNTS = (("FT_PCT", "TOV"), ("FG_PCT", "FT_PCT"), ("FG3M", "FT_PCT"), ("AST", "TOV"), ("PTS", "FG3M"),
                ("BLK", "REB"), ("PTS", "AST"))
#: kadroya göre karışımlar: (ad, güçlü kategori sayısı, güçlü ağırlığı, zayıf ağırlıkları [en zayıf, 2.])
MIXES = (
    ("güçlü2 ×1.25 · zayıf ×0.5", 2, 1.25, (0.5,)),
    ("güçlü2 ×1.5 · zayıf punt", 2, 1.5, (0.0,)),
    ("zayıf punt · 2. zayıf ×0.5", 0, 1.0, (0.0, 0.5)),
    ("güçlü3 ×1.25", 3, 1.25, ()),
    ("güçlü2 ×1.5 · zayıf2 ×0.75", 2, 1.5, (0.75, 0.75)),
)


@dataclass(frozen=True)
class Strategy:
    name: str
    kind: str                     # balanced | adaptive | fixed | mix
    start: int = 1                # bu turn'den (0 = ilk çift) itibaren hedef ağırlık; öncesi dengeli
    punt: tuple[str, ...] = ()
    mix: tuple = ()


def strategies(categories) -> list[Strategy]:
    out = [Strategy("Dengeli", "balanced"), Strategy("Uyarlanabilir (kural)", "adaptive")]
    lab = CATEGORY_LABELS
    punts = [(c,) for c in categories] + [p for p in DOUBLE_PUNTS if set(p) <= set(categories)]
    for start, prefix in ((1, "Baştan"), (2, "48/49 dengeli →")):
        for p in punts:
            out.append(Strategy(f"{prefix} punt {'+'.join(lab[c] for c in p)}", "fixed", start, punt=p))
        for m in MIXES:
            out.append(Strategy(f"{prefix} {m[0]}", "mix", start, mix=m))
    return out


def make_policy(st: Strategy, categories):
    """``play_draft`` politikası; karar ilk uygulandığı turn'de kadronun P'lerinden verilip sabitlenir."""
    C = len(categories)
    state: dict[str, np.ndarray] = {}

    def mix_weights(team_p: np.ndarray) -> np.ndarray:
        _, n_strong, w_strong, weak = st.mix
        W = np.ones_like(team_p)
        order = np.argsort(team_p, axis=1)                         # artan: zayıftan güçlüye
        rows = np.arange(len(team_p))
        for j, w in enumerate(weak):
            W[rows, order[:, j]] = w
        for j in range(n_strong):
            W[rows, order[:, C - 1 - j]] = w_strong
        return W

    def policy(ti: int, team_p: np.ndarray) -> np.ndarray:
        S = len(team_p)
        ones = np.ones((S, C))
        if st.kind == "balanced":
            return ones
        if st.kind == "adaptive":
            punted = state.setdefault("punted", np.full(S, -1))
            thr = BROKEN_AFTER_PAIR if ti <= 1 else BROKEN_LATER
            weakest = np.argmin(team_p, axis=1)
            new = (punted < 0) & (team_p[np.arange(S), weakest] < thr)
            punted[new] = weakest[new]
            W = ones.copy()
            W[punted >= 0, punted[punted >= 0]] = 0.0
            return W
        if ti < st.start:
            return ones
        if "W" not in state:
            if st.kind == "fixed":
                w = np.array([0.0 if c in st.punt else 1.0 for c in categories])
                state["W"] = np.broadcast_to(w, (S, C)).copy()
            else:
                state["W"] = mix_weights(team_p)
        return state["W"]

    return policy


def weights_label(w: np.ndarray, categories) -> str:
    if np.isnan(w).any():
        return ""
    if np.allclose(w, 1.0):
        return "dengeli"
    return " ".join(f"{CATEGORY_LABELS[c]}×{v:g}" for c, v in zip(categories, w) if abs(v - 1.0) > 1e-9)


# ---------------------------------------------------------------- işçi süreçleri
_CTX = None


def _init(data: str, league: str | None, seed: int) -> None:
    global _CTX
    from fdo.advisor.simulate import prepare_context
    from fdo.config import load_config
    from fdo.ingest.load import load_data_dir

    cfg = load_config(league) if league else load_config()
    ds, rep = load_data_dir(data, cfg)
    if ds is None:
        raise SystemExit("Veri yüklenemedi: " + "; ".join(rep.errors))
    _CTX = prepare_context(ds, cfg, seed)


def run_task(task: tuple) -> dict:
    """(çift indeksleri, strateji, S, seed, field_k) → kadrolar, kategori P'leri, kullanılan ağırlıklar."""
    from fdo.advisor.scenarios import play_draft
    from fdo.advisor.simulate import team_vectors
    from fdo.draft.events import DraftLog

    pair, st, S, seed, field_k = task
    ctx = _CTX
    cfg = ctx.config
    lg = cfg.league
    log = DraftLog(lg.teams, lg.rounds, lg.third_round_reversal)
    first = [n for n in range(1, lg.total_picks + 1) if log.seat_for(n) == lg.my_seat][:2]
    r = play_draft(ctx, log, S, seed, policy=make_policy(st, cfg.categories),
                   forced=dict(zip(first, pair)), reserve=list(pair))
    teams = team_vectors(r.engine, ctx.vecs, ctx.base_fill, r.engine.total + 1)
    user = teams[:, lg.my_seat - 1]
    opp = np.delete(teams, lg.my_seat - 1, axis=1)
    rng = np.random.default_rng(seed)
    field = opp.reshape(-1, opp.shape[-1])[rng.choice(opp.shape[0] * opp.shape[1], field_k, replace=False)] \
        if field_k else np.zeros((0, teams.shape[-1]))
    return {"pair": pair, "strategy": st, "rosters": r.rosters, "cat_p": r.P.mean(axis=1),
            "ew": r.P.sum(axis=-1).mean(axis=-1), "user_vec": user, "field": field,
            "w1": r.weights[1] if len(r.weights) > 1 else None,
            "w2": r.weights[2] if len(r.weights) > 2 else None}


# ---------------------------------------------------------------- ana akış
def availability(ctx, n: int, seed: int) -> np.ndarray:
    """``(n, oyuncu)``: kullanıcının ilk pick'inde uygunluk (bot simülasyonu)."""
    from fdo.advisor.simulate import make_engine

    lg = ctx.config.league
    eng = make_engine(ctx, None, n, seed, cache_jitter=False)
    eng.run_until(lg.my_seat, skip_seat=None)
    return eng.taken_at == 0


def resolve(names: pd.Series, text: str) -> str:
    from fdo.ingest.load import normalize_name

    key = normalize_name(text)
    hits = [pid for pid, nm in names.items() if normalize_name(str(nm)) == key]
    if not hits:
        raise SystemExit(f"Oyuncu bulunamadı: {text}")
    return hits[0]


def typical_roster(R: np.ndarray) -> np.ndarray:
    """En temsili gerçek kadro: oyuncularının kendi pick'lerindeki sıklık toplamı en yüksek simülasyon
    (sütun bazında mod aynı oyuncuyu iki pick'e koyabilir)."""
    freq = np.zeros(R.shape, dtype=float)
    for j in range(R.shape[1]):
        vals, counts = np.unique(R[:, j], return_counts=True)
        freq[:, j] = pd.Series(counts, index=vals).reindex(R[:, j]).to_numpy()
    return R[int(np.argmax(freq.sum(axis=1)))]


def summarize(results: list[dict], categories, names, pick_cols) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Senaryo özetleri ve kadro satırları."""
    labels = [CATEGORY_LABELS[c] for c in categories]
    rows, rosters = [], []
    for res in results:
        st, ew = res["strategy"], res["ew"]
        pair_label = " + ".join(names[p] for p in res["pair_ids"])
        S = len(ew)
        w1 = [weights_label(w, categories) for w in res["w1"]] if res["w1"] is not None else [""] * S
        w2 = [weights_label(w, categories) for w in res["w2"]] if res["w2"] is not None else [""] * S
        R = res["roster_ids"]
        modal = typical_roster(R)
        rows.append({"çift": pair_label, "16": names[res["pair_ids"][0]], "17": names[res["pair_ids"][1]],
                     "strateji": st.name, "E[W]": float(ew.mean()),
                     "SE": float(ew.std(ddof=1) / np.sqrt(S)) if S > 1 else 0.0,
                     "P10": float(np.quantile(ew, 0.1)), "P90": float(np.quantile(ew, 0.9)),
                     "güç (sabit alan)": float(res["power"].mean()), "P(çift kalır)": res["p_avail"],
                     "48/49 ağırlık": pd.Series(w1).mode().iloc[0], "80+ ağırlık": pd.Series(w2).mode().iloc[0],
                     **{lab: float(v) for lab, v in zip(labels, res["field_p"].mean(axis=0))},
                     **{f"tipik {k}": names[p] for k, p in zip(pick_cols, modal)},
                     "sim": S})
        for s in range(S):
            rosters.append({"çift": pair_label, "strateji": st.name, "sim": s, "E[W]": float(ew[s]),
                            "güç (sabit alan)": float(res["power"][s]),
                            **{str(k): names[p] for k, p in zip(pick_cols, R[s])},
                            "48/49 ağırlık": w1[s], "80+ ağırlık": w2[s],
                            **{lab: float(v) for lab, v in zip(labels, res["field_p"][s])}})
    return pd.DataFrame(rows), pd.DataFrame(rosters)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--league", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--pairs", nargs="*", default=[], help='zorunlu çiftler: "Ad Soyad+Ad Soyad"')
    ap.add_argument("--candidates", type=int, default=16, help="aday çiftler için oyuncu sayısı")
    ap.add_argument("--min-avail", type=float, default=0.08, help="16'da kalma olasılığı alt sınırı")
    ap.add_argument("--min-joint", type=float, default=0.02, help="çiftin birlikte kalma olasılığı alt sınırı")
    ap.add_argument("--screen-sims", type=int, default=24)
    ap.add_argument("--top-pairs", type=int, default=26)
    ap.add_argument("--grid-sims", type=int, default=32)
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--final-sims", type=int, default=96)
    ap.add_argument("--avail-sims", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="reports/draft_senaryolari.xlsx")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    t0 = time.perf_counter()

    from fdo.advisor.board import category_board
    from fdo.advisor.simulate import prepare_context
    from fdo.config import load_config
    from fdo.draft.events import DraftLog
    from fdo.ingest.load import load_data_dir
    from fdo.matchup.ecw import ecw_vs

    cfg = load_config(args.league) if args.league else load_config()
    ds, rep = load_data_dir(args.data, cfg)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    ctx = prepare_context(ds, cfg, args.seed)
    u, lg = ctx.universe, cfg.league
    names = ds.names()
    cats = list(cfg.categories)
    log = DraftLog(lg.teams, lg.rounds, lg.third_round_reversal)
    pick_cols = [n for n in range(1, lg.total_picks + 1) if log.seat_for(n) == lg.my_seat]

    avail = availability(ctx, args.avail_sims, args.seed + 101)
    p_av = avail.mean(axis=0)
    board = category_board(ctx, log, n_sims=0)
    forced = []
    for text in args.pairs:
        a, b = (resolve(names, x.strip()) for x in text.split("+"))
        forced.append(tuple(sorted((u.index[a], u.index[b]))))
    pool = [u.index[p] for p in board.table["player_id"] if p_av[u.index[p]] >= args.min_avail][: args.candidates]
    pool = sorted(set(pool) | {i for pr in forced for i in pr}, key=lambda i: -p_av[i])
    pairs = sorted({tuple(sorted(c)) for c in itertools.combinations(pool, 2)
                    if (avail[:, c[0]] & avail[:, c[1]]).mean() >= args.min_joint} | set(forced))
    joint = {pr: float((avail[:, pr[0]] & avail[:, pr[1]]).mean()) for pr in pairs}
    print(f"aday oyuncu {len(pool)}, çift {len(pairs)} ({len(forced)} zorunlu) · {time.perf_counter() - t0:.0f} s",
          flush=True)
    for i in pool:
        print(f"  {names[str(u.ids[i])]:<26} P(16'da uygun) {p_av[i]:.2f}")

    all_st = strategies(cats)
    st_screen = all_st[:2]

    def label(pr):
        return " + ".join(names[str(u.ids[i])] for i in pr)

    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.data, args.league, args.seed)) as ex:
        # 1) eleme
        tasks = [(pr, st, args.screen_sims, args.seed, 0) for pr in pairs for st in st_screen]
        screen = {}
        for k, res in enumerate(ex.map(run_task, tasks, chunksize=2)):
            screen.setdefault(res["pair"], []).append(float(res["ew"].mean()))
            if (k + 1) % 50 == 0:
                print(f"  eleme {k + 1}/{len(tasks)} · {time.perf_counter() - t0:.0f} s", flush=True)
        screen_df = pd.DataFrame([{"çift": label(pr), "P(çift kalır)": joint[pr], "E[W] dengeli": v[0],
                                   "E[W] uyarlanabilir": v[1], "zorunlu": pr in forced}
                                  for pr, v in screen.items()]).sort_values("E[W] uyarlanabilir", ascending=False)
        best_pairs = sorted(screen, key=lambda pr: -max(screen[pr]))[: args.top_pairs]
        grid_pairs = list(dict.fromkeys([*best_pairs, *forced]))
        print(f"eleme bitti: ızgara {len(grid_pairs)} çift × {len(all_st)} strateji · "
              f"{time.perf_counter() - t0:.0f} s", flush=True)

        # 2) ızgara
        tasks = [(pr, st, args.grid_sims, args.seed + 1, 0) for pr in grid_pairs for st in all_st]
        grid = []
        for k, res in enumerate(ex.map(run_task, tasks, chunksize=2)):
            grid.append({"pair": res["pair"], "strategy": res["strategy"], "E[W]": float(res["ew"].mean()),
                         "SE": float(res["ew"].std(ddof=1) / np.sqrt(len(res["ew"])))})
            if (k + 1) % 100 == 0:
                print(f"  ızgara {k + 1}/{len(tasks)} · {time.perf_counter() - t0:.0f} s", flush=True)
        grid_df = pd.DataFrame(grid).sort_values("E[W]", ascending=False)
        # en iyi senaryolar + her zorunlu çiftin en iyi 3'ü (farklı çiftler görünür olsun)
        chosen = list(grid_df.head(args.top)[["pair", "strategy"]].itertuples(index=False, name=None))
        for pr in grid_pairs:
            sub = grid_df[grid_df["pair"] == pr].head(3 if pr in forced else 1)
            chosen += [x for x in sub[["pair", "strategy"]].itertuples(index=False, name=None) if x not in chosen]
        print(f"ızgara bitti: son ölçüm {len(chosen)} senaryo × {args.final_sims} sim · "
              f"{time.perf_counter() - t0:.0f} s", flush=True)

        # 3) son ölçüm (yeni seed)
        tasks = [(pr, st, args.final_sims, args.seed + 2, 24) for pr, st in chosen]
        final = list(ex.map(run_task, tasks, chunksize=1))

    field = np.concatenate([r["field"] for r in final])
    for res in final:
        res["pair_ids"] = [str(u.ids[i]) for i in res["pair"]]
        res["roster_ids"] = np.vectorize(lambda i: str(u.ids[i]))(res["rosters"])
        fp = ecw_vs(res["user_vec"], field[None, :, :], cfg)                   # (S, F, C)
        res["field_p"] = fp.mean(axis=1)
        res["power"] = fp.sum(axis=-1).mean(axis=-1)
        res["p_avail"] = joint[res["pair"]]
    scen, rosters = summarize(final, cats, names, pick_cols)
    scen = scen.sort_values("E[W]", ascending=False).reset_index(drop=True)
    scen.insert(0, "sıra", range(1, len(scen) + 1))
    rank = dict(zip(zip(scen["çift"], scen["strateji"]), scen["sıra"]))
    rosters.insert(0, "senaryo sırası", [rank[(a, b)] for a, b in zip(rosters["çift"], rosters["strateji"])])
    rosters = rosters.sort_values(["senaryo sırası", "E[W]"], ascending=[True, False])

    grid_out = pd.DataFrame({"çift": [label(p) for p in grid_df["pair"]],
                             "strateji": [s.name for s in grid_df["strategy"]],
                             "E[W]": grid_df["E[W]"], "SE": grid_df["SE"],
                             "P(çift kalır)": [joint[p] for p in grid_df["pair"]]})
    pair_out = (scen.groupby("çift").agg(**{"en iyi E[W]": ("E[W]", "max"), "P(çift kalır)": ("P(çift kalır)", "first")})
                .join(scen.loc[scen.groupby("çift")["E[W]"].idxmax()].set_index("çift")[["strateji"]]
                      .rename(columns={"strateji": "en iyi strateji"}))
                .sort_values("en iyi E[W]", ascending=False).reset_index())
    avail_out = pd.DataFrame({"oyuncu": [names[str(u.ids[i])] for i in pool],
                              "P(16'da uygun)": [p_av[i] for i in pool]})
    elapsed = time.perf_counter() - t0
    n_drafts = (len(pairs) * len(st_screen) * args.screen_sims + len(grid_pairs) * len(all_st) * args.grid_sims
                + len(chosen) * args.final_sims)
    notes = pd.DataFrame({"açıklama": [
        f"{lg.name} · {lg.teams} takım · koltuk {lg.my_seat} · seed {args.seed} · toplam {n_drafts} simüle draft · "
        f"{elapsed / 60:.0f} dk",
        "Senaryo = 16/17 çifti + sonraki turn'ler için strateji. Botlar ilk 15 pick'i çiftin iki oyuncusu da kalacak "
        "şekilde oynar; 'P(çift kalır)' ikisinin birlikte gerçekten kalma olasılığıdır (bot simülasyonu).",
        "E[W]: draft sonunda 15 rakibe karşı rakip başına beklenen kategori galibiyeti (0–9), simüle rakip kadrolarıyla.",
        "güç (sabit alan): aynı kadronun herkes için ortak bir rakip havuzuna karşı E[W]'si — kadroları kendi "
        "aralarında adil karşılaştırmak için. Kategori sütunları bu havuza karşı kazanma olasılıklarıdır.",
        f"Uyarlanabilir: ilk çiftten sonra bir kategori P < {BROKEN_AFTER_PAIR} ise baştan punt; değilse 48/49 "
        f"dengeli, sonra en zayıf kategori P < {BROKEN_LATER} ise punt. '48/49 dengeli → X': 48/49 dengeli, 80'den "
        "itibaren X. 'Baştan X': 48/49'dan itibaren X.",
        "Karışımlar (güçlü2 ×1.25 vb.) ağırlıkları kadronun o anki en güçlü/en zayıf kategorilerinden belirler; "
        "uygulanan ağırlıklar '48/49 ağırlık' ve '80+ ağırlık' sütunlarında.",
        "Sonraki pick'ler advisor'ın miyopik politikasıyla seçilir (her turn'de statik rakiplere karşı en iyi kombinasyon); "
        "canlı draft'taki tam mod advisor daha iyi seçim yapabilir. Son ölçüm, ızgaradan bağımsız yeni simülasyonlardır.",
        "Kadrolar sayfası: sütun başlıkları pick numaralarıdır (16, 17, 48, …). Excel filtresiyle kendi "
        "seçimlerine göre daraltabilirsin.",
    ]})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(out, {"En iyi senaryolar": scen, "Kadrolar": rosters, "Çiftler": pair_out,
                     "Strateji ızgarası": grid_out, "Eleme": screen_df, "16'da uygunluk": avail_out,
                     "Açıklama": notes})
    rosters.to_csv(out.with_suffix(".kadrolar.csv"), index=False, encoding="utf-8-sig")
    print(f"yazıldı: {out} ({len(scen)} senaryo, {len(rosters)} kadro) · {elapsed / 60:.1f} dk")
    print(scen.head(15)[["sıra", "çift", "strateji", "E[W]", "SE", "P(çift kalır)"]].round(3).to_string(index=False))
    return 0


def write_xlsx(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            if len(df):
                ws.auto_filter.ref = ws.dimensions
            for j, col in enumerate(df.columns, start=1):
                letter = get_column_letter(j)
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.column_dimensions[letter].width = min(max(width, 6), 34)
                if pd.api.types.is_float_dtype(df[col]):
                    for cell in ws[letter][1:]:
                        cell.number_format = "0.000"
                    rng = f"{letter}2:{letter}{len(df) + 1}"
                    if col in {CATEGORY_LABELS[c] for c in CATEGORY_LABELS} or col in ("E[W]", "güç (sabit alan)",
                                                                                       "en iyi E[W]"):
                        ws.conditional_formatting.add(rng, ColorScaleRule(
                            start_type="min", start_color="F8696B", mid_type="percentile", mid_value=50,
                            mid_color="FFFFFF", end_type="max", end_color="63BE7B"))


if __name__ == "__main__":
    raise SystemExit(main())
