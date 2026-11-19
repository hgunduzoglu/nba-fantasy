"""Dayanıklılık: kalan sezon (ROS) maç sayısını oyuncunun beklenen oynama oranıyla sınırlar (README §13.19).

Yahoo'nun kalan sezon projeksiyonu neredeyse her sağlıklı oyuncuya takımının kalan maçlarının tamamını verir;
sakatlık riski yok sayılır ve sık sakatlanan oyuncular dayanıklılara göre değerli görünür. Sezon öncesi
projeksiyonun maç sayısı ise bu riski içerir (ör. Caruso 58/82).

* Önsel oran: sezon öncesi projeksiyon maçı / 82.
* Bu sezon: oynanan maç / takımın oynadığı maç, ``prior_games`` maçlık önselle birleştirilir ve oranı yalnız
  yukarı çekebilir (rotasyona girmiş, her maça çıkan oyuncu). Kaçırılan maçlar düşürmez: güncel sakatlık zaten
  dönüş tarihiyle modellenir, çift sayılmaz.
* Tavan = oran × dönüşten sonraki takım maçı (dönüş tarihi bilinmiyorsa bugünden). ROS maçı tavanı aşıyorsa ROS
  toplamları orantılı küçültülür; maç başı değerler korunur.

* Yahoo'nun 0 maç (ya da hiç satır) verdiği, dönüşü bilinen sakat ya da kadrodaki aktif oyuncu önce sezon + sezon öncesi maç başı değerleriyle
  doldurulur (``_fill_missing_ros``); yoksa hiç modellenmez.
* Yahoo'nun maç başı değeri bariz bayat oyuncu (bu sezonun ve sezon öncesinin yarısının altında; çoğu yedek ve
  rotasyon oyuncusu, ör. her maç 20+ dakika oynayana maç başı 1 sayı) bu sezon ağırlıklı oranlarla düzeltilir
  (``_fix_stale_ros``, README §13.57).
* Diğer oyuncularda Yahoo'nun maç başı değeri bu sezona doğru kaydırılır (``_shrink_to_season``, README §13.59):
  kategori başına ``n / (n + k)`` ağırlıkla (``n`` bu sezon oynanan maç; ``k`` sayı ve isabette küçük, top çalma ve
  blokta büyük: Yahoo orada daha isabetli). Maç kayıtları verilirse dakikası son maçlarda değişen oyuncunun maç başı
  değerleri dakika oranıyla çarpılır (``_minutes_factor``): ``((1 − q) · sezon dk + q · son 5 maç dk) / sezon dk``.
  Kaydırma öncesi Yahoo satırı ``stats["yahoo_ros"]``'ta kalır (``yahoo`` temeli).

Sezon öncesi projeksiyonu olmayan oyuncuya dokunulmaz. Ham dosyalar değişmez; düzeltme bellekte ve açıkça
raporlanır. Sakatlık dönüş tarihlerinden (``apply_injuries``) sonra uygulanır.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd

from fdo.inseason.injuries import team_games_from
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS, TradeData
from fdo.types import STATS

SEASON_GAMES = 82
PRIOR_GAMES = 20.0
STALE_RATIO = .5             # Yahoo ROS maç başı hacmi bu sezonun ve sezon öncesinin küçüğünün bu oranından azsa bayat
STALE_MIN_GP = 5             # bu sezon en az bu kadar maç (oynadığı gerçek rol bilinsin)
STALE_PRIOR_GAMES = 5.0      # bayat düzeltmede sezon öncesine önsel (maç): gerçek oynanan role ağırlık
STALE_VOLUME = ("pts", "reb", "ast", "stl", "blk", "fg3m")
YAHOO = "yahoo_ros"          # kaydırma öncesi Yahoo kalan sezon satırı (bayat düzeltme ve doldurma sonrası)
#: Bu sezona kaydırma: kategori başına önsel maç (geçmiş iki sezonun maç kayıtlarıyla ölçüldü; README §13.59).
SHRINK_GAMES = {"fgm": 4.0, "fga": 4.0, "pts": 3.0, "reb": 5.0, "ast": 5.0, "ftm": 8.0, "fta": 8.0, "fg3m": 8.0,
                "tov": 8.0, "stl": 14.0, "blk": 12.0}
SHRINK_MIN_GAMES = 3         # en az bu kadar maç (tek maçlık sakatlık çıkışı oranı bozmasın)
MINUTES_WEIGHT = .25         # dakika oranında son maçların ağırlığı
MINUTES_RECENT = 5           # son kaç maç
MINUTES_MIN_GAMES = 5        # en az bu kadar oynanan maç
MINUTES_CLIP = (.6, 1.5)


def apply_durability(data: TradeData, prior_games: float = PRIOR_GAMES, logs: pd.DataFrame | None = None) -> TradeData:
    """ROS toplamlarını beklenen oynama oranına göre kısar ve oran tablosunu ekler (yeni ``TradeData``). ``logs``: bu
    sezonun NBA maç kayıtları (dakika oranı için; yoksa yalnız bu sezona kaydırma)."""
    if data.schedule is None or prior_games < 0:
        return data
    games = team_games_from(data.schedule)
    stats = {k: v.copy() for k, v in data.stats.items()}
    ros, pre, season = stats[ROS], stats["preseason"]["gp"], stats["season_total"]["gp"]
    inj = data.injuries
    filled = _fill_missing_ros(data, stats, games, prior_games)
    stale = _fix_stale_ros(stats)
    stats[YAHOO] = stats[ROS].copy()
    skip = set(filled) | set(stale)
    shrunk = _shrink_to_season(stats, skip)
    minutes = _minutes_factor(data, logs, skip)
    for pid, f in minutes.items():
        if pid in ros.index:
            ros.loc[pid, list(STATS)] = ros.loc[pid, list(STATS)] * f
    rows = []
    for pid in ros.index:
        gp, pre_gp = float(ros.loc[pid, "gp"]), float(pre.get(pid, np.nan))
        if not (np.isfinite(gp) and gp > 0 and np.isfinite(pre_gp)):
            continue
        team_games = games.get(normalize_team(data.players.loc[pid, "nba_team"] or ""), [])
        played = sum(d < data.as_of for d in team_games)
        start = data.as_of
        if inj is not None and pid in inj.index and inj.loc[pid, "kind"] == "out_until" \
                and not pd.isna(inj.loc[pid, "return_date"]):
            start = max(start, pd.Timestamp(inj.loc[pid, "return_date"]).date())
        left = sum(d >= start for d in team_games)
        prior = min(1.0, max(0.0, pre_gp / SEASON_GAMES))
        seen = min(float(np.nan_to_num(season.get(pid, 0.0))), played)    # takas: eski takımında fazla maç
        rate = max(prior, min(1.0, (prior_games * prior + seen) / (prior_games + played))) \
            if prior_games + played > 0 else prior
        new_gp = min(gp, rate * left)
        if new_gp < gp:
            ros.loc[pid, [*STATS, "gp"]] = ros.loc[pid, [*STATS, "gp"]] * (new_gp / gp)
        rows.append({"player_id": pid, "preseason_rate": prior, "season_gp": seen, "team_played": played,
                     "rate": rate, "games_left": left, "ros_gp_before": gp, "ros_gp_after": new_gp})
    if not rows:
        return data
    table = pd.DataFrame(rows).set_index("player_id")
    table["ros_filled"] = table.index.isin(filled)
    table["ros_stale"] = table.index.isin(stale)
    table["ros_shrunk"] = table.index.isin(shrunk)
    table["minutes_factor"] = pd.Series(minutes, dtype=float).reindex(table.index).fillna(1.0)
    cut = table["ros_gp_after"] < table["ros_gp_before"] - 1e-9
    sources = {**data.sources, "durability": {"kind": "durability", "basis": "preseason projected_gp / 82",
                                              "prior_games": prior_games, "rows": int(cut.sum()),
                                              "ros_filled": sorted(filled), "ros_stale": sorted(stale),
                                              "shrink_games": SHRINK_GAMES, "ros_shrunk": len(shrunk),
                                              "minutes_weight": MINUTES_WEIGHT, "minutes_adjusted": len(minutes)}}
    note = (f"Dayanıklılık uygulandı: {int(cut.sum())} oyuncunun kalan sezon maçı sezon öncesi oynama oranıyla "
            f"sınırlandı (toplam {table['ros_gp_before'].sum():.0f} → {table['ros_gp_after'].sum():.0f} maç).")
    notes = [note]
    if shrunk or minutes:
        notes.insert(0, f"Yahoo projeksiyonu {len(shrunk)} oyuncuda bu sezona doğru kaydırıldı (kategori başına önsel "
                        f"maç); {len(minutes)} oyuncunun maç başı değeri son {MINUTES_RECENT} maçtaki dakika "
                        f"değişimiyle çarpıldı.")
    if filled:
        names = ", ".join(str(data.players.loc[p, "name"]) for p in filled)
        notes.append(f"Kalan sezon projeksiyonu 0 maç ya da boş olan {len(filled)} oyuncu sezon ve sezon "
                     f"öncesi maç başı değerleriyle dolduruldu: {names}")
    if stale:
        notes.append(f"Yahoo kalan sezon projeksiyonu bu sezonun ve sezon öncesinin yarısının altında kalan "
                     f"{len(stale)} oyuncunun maç başı değeri bu sezon + sezon öncesiyle düzeltildi (bayat projeksiyon).")
    return dataclasses.replace(data, stats=stats, sources=sources, durability=table,
                               fingerprint=f"{data.fingerprint}:dur{int(cut.sum())}f{len(filled)}s{len(stale)}"
                                           f"k{len(shrunk)}m{len(minutes)}",
                               issues=(*data.issues, *notes))


def _fix_stale_ros(stats: dict, ratio: float = STALE_RATIO, min_gp: int = STALE_MIN_GP,
                   prior_games: float = STALE_PRIOR_GAMES) -> list[str]:
    """Yahoo'nun kalan sezon projeksiyonu yedek ve rotasyon oyuncularında çoğu zaman neredeyse hiç süre almayacakmış
    gibi maç başı çok düşük değer verir (ör. her maç oynayan oyuncuya maç başı 1 sayı) ve rol değişimine tepki vermez.
    Maç başı hacmi (sayı + ribaund + asist + top çalma + blok + üçlük) bu sezonun (en az ``min_gp`` maç) ve sezon
    öncesinin küçüğünün ``ratio`` katından azsa maç başı değerler bu sezon ile sezon öncesinin ``prior_games``
    maçlık önselle ağırlıklı ortalamasıyla değiştirilir (gerçek oynanan role ağırlık); maç sayısı Yahoo'nunki kalır
    (``stats`` yerinde güncellenir). Düzeltilenlerin kimlikleri döner."""
    ros, pre, season = stats[ROS], stats["preseason"], stats["season_total"]
    vol = lambda f: f[list(STALE_VOLUME)].sum(axis=1) / f["gp"].where(f["gp"] > 0)      # noqa: E731
    seen = season["gp"].reindex(ros.index).fillna(0.0)
    floor = np.minimum(vol(season).reindex(ros.index).where(seen >= min_gp), vol(pre).reindex(ros.index))
    bad = ros.index[(ros["gp"] > 0) & (vol(ros) < ratio * floor)]
    out = []
    for pid in bad:
        cur = season.loc[pid, list(STATS)].astype(float) / seen[pid]
        pre_pg = pre.loc[pid, list(STATS)].astype(float) / float(pre.loc[pid, "gp"])
        if not (np.isfinite(cur.to_numpy()).all() and np.isfinite(pre_pg.to_numpy()).all()):
            continue
        w = seen[pid] / (seen[pid] + prior_games)
        ros.loc[pid, list(STATS)] = ((w * cur + (1 - w) * pre_pg) * float(ros.loc[pid, "gp"])).to_numpy()
        for col in ros.columns.difference(["gp", *STATS]):
            if pd.api.types.is_float_dtype(ros[col]):
                ros.loc[pid, col] = np.nan          # kaynaktaki yüzde vb. artık bu satırı anlatmaz
        out.append(pid)
    return out


def _shrink_to_season(stats: dict, skip: set[str], games: dict[str, float] | None = None) -> list[str]:
    """Yahoo'nun maç başı değerini bu sezonun maç başına kaydırır: kategori ``s`` için ``w = n / (n + k_s)``
    (``n`` bu sezon oynanan maç, en az ``SHRINK_MIN_GAMES``; ``k_s`` ``SHRINK_GAMES``), maç başı = ``(1 − w) · Yahoo + w · bu sezon``; maç sayısı
    Yahoo'nunki kalır. Geçmiş sezonlarda saf Yahoo'ya göre hata ~%6,5 düşük (README §13.59). ``skip``: bayat düzeltilen
    ya da doldurulan (zaten bu sezon ağırlıklı) oyuncular. ``stats`` yerinde güncellenir; kaydırılanlar döner."""
    games = SHRINK_GAMES if games is None else games
    ros, season = stats[ROS], stats["season_total"].reindex(stats[ROS].index)
    n = season["gp"].fillna(0.0)
    ok = (ros["gp"] > 0) & (n >= SHRINK_MIN_GAMES) & ~ros.index.isin(list(skip))
    cols = list(STATS)
    yahoo = ros.loc[ok, cols].div(ros.loc[ok, "gp"], axis=0)
    cur = season.loc[ok, cols].div(n[ok], axis=0)
    good = np.isfinite(yahoo.to_numpy(float)).all(axis=1) & np.isfinite(cur.to_numpy(float)).all(axis=1)
    yahoo, cur, n = yahoo[good], cur[good], n[ok][good]
    if yahoo.empty:
        return []
    w = pd.DataFrame({c: n / (n + games.get(c, 8.0)) for c in cols})
    pg = yahoo * (1 - w) + cur * w
    pg["fgm"] = np.minimum(pg["fgm"], pg["fga"])
    pg["ftm"] = np.minimum(pg["ftm"], pg["fta"])
    pg["fg3m"] = np.minimum(pg["fg3m"], pg["fgm"])
    ros.loc[pg.index, cols] = pg.mul(ros.loc[pg.index, "gp"], axis=0).to_numpy()
    for col in ros.columns.difference(["gp", *STATS]):
        if pd.api.types.is_float_dtype(ros[col]):
            ros.loc[pg.index, col] = np.nan              # kaynaktaki yüzde artık bu satırı anlatmaz
    return list(pg.index)


def _minutes_factor(data: TradeData, logs: pd.DataFrame | None, skip: set[str], q: float = MINUTES_WEIGHT,
                    recent: int = MINUTES_RECENT, min_games: int = MINUTES_MIN_GAMES) -> dict[str, float]:
    """Oyuncu → maç başı çarpanı ``((1 − q) · sezon dk + q · son ``recent`` maç dk) / sezon dk`` (``data.as_of``
    öncesi oynanan maçlar; en az ``min_games``; ``MINUTES_CLIP`` ile sınırlı). Rol değişimi geçmiş sezonlarda böyle
    oyuncularda hatayı %8–14 düşürüyor; dakikası sabit olanda etkisiz (README §13.59). Bayat düzeltilen ve doldurulan
    oyuncu (``skip``) hariç; 1 olanlar dönmez."""
    if logs is None or logs.empty or q <= 0:
        return {}
    from fdo.inseason.roles import match_ids
    g = logs[(logs["game_date"] < data.as_of) & (logs["minutes"] > 0)]
    if g.empty:
        return {}
    g = g.assign(player_id=match_ids(g, data.players).values).dropna(subset=["player_id"]).sort_values("game_date")
    out: dict[str, float] = {}
    lo, hi = MINUTES_CLIP
    for pid, pl in g.groupby("player_id"):
        if pid in skip or len(pl) < min_games:
            continue
        season, last = float(pl["minutes"].mean()), float(pl["minutes"].iloc[-recent:].mean())
        if season <= 0:
            continue
        f = min(hi, max(lo, ((1 - q) * season + q * last) / season))
        if abs(f - 1) > 1e-9:
            out[str(pid)] = f
    return out


def _fill_missing_ros(data: TradeData, stats: dict, games: dict, prior_games: float) -> list[str]:
    """Yahoo'nun kalan sezon projeksiyonu 0 maç (ya da hiç satır) verdiği oyuncu aksi hâlde hiç modellenmez ve değeri
    0 görünür. Doldurulanlar: CBS'te dönüş tarihi bilinen sakat (ör. birkaç hafta yok) ve kadrodaki oyunculardan günlük
    sakat (CBS ``day_to_day``) ya da CBS kaydı olmayan, Yahoo'da aktif durumdaki (``NA`` değil) oyuncu (ör. projeksiyon
    sayfalarında satırı çıkmayan rotasyon oyuncusu). Maç başı değer = bu sezon ile sezon öncesi projeksiyonun
    ``prior_games`` maçlık önselle ağırlıklı ortalaması, maç = önsel oynama oranı × dönüşten (yoksa bugünden) sonraki
    takım maçı (``stats`` yerinde güncellenir). Sezon boyu yok, dönüşü bilinmeyen uzun sakatlık ya da sezon öncesi
    projeksiyonu olmayan oyuncuya dokunulmaz. Doldurulanların kimlikleri döner."""
    inj = data.injuries if data.injuries is not None else pd.DataFrame(columns=["kind", "return_date"])
    ros, pre, season = stats[ROS], stats["preseason"], stats["season_total"]
    owned = {p for lg in data.leagues.values() for r in lg.rosters.values() for p in r}
    starts: dict[str, dt.date] = {}
    for pid, row in inj.iterrows():
        if row["kind"] == "out_until" and not pd.isna(row["return_date"]):
            starts[pid] = max(data.as_of, pd.Timestamp(row["return_date"]).date())
        elif row["kind"] == "day_to_day" and pid in owned:
            starts[pid] = data.as_of
    for pid in owned - set(inj.index):
        if str(data.players.loc[pid, "injury_status"] or "") not in ("NA", "O", "INJ", "SUSP"):
            starts[pid] = data.as_of
    filled = []
    for pid, start in starts.items():
        if pid not in ros.index:
            continue
        gp = float(ros.loc[pid, "gp"]) if pd.notna(ros.loc[pid, "gp"]) else 0.0
        pre_gp = float(pre.loc[pid, "gp"]) if pid in pre.index and pd.notna(pre.loc[pid, "gp"]) else np.nan
        if gp > 0 or not (np.isfinite(pre_gp) and pre_gp > 0):
            continue
        pre_pg = pre.loc[pid, list(STATS)].astype(float) / pre_gp
        if not np.isfinite(pre_pg.to_numpy()).all():
            continue
        seen = float(season.loc[pid, "gp"]) if pid in season.index and pd.notna(season.loc[pid, "gp"]) else 0.0
        cur = season.loc[pid, list(STATS)].astype(float) / seen if seen > 0 else pre_pg
        if not np.isfinite(cur.to_numpy()).all():
            cur, seen = pre_pg, 0.0
        w = seen / (seen + prior_games) if seen + prior_games > 0 else 0.0
        per_game = w * cur + (1 - w) * pre_pg
        left = sum(d >= start for d in games.get(normalize_team(data.players.loc[pid, "nba_team"] or ""), []))
        new_gp = min(1.0, pre_gp / SEASON_GAMES) * left
        if new_gp <= 0:
            continue
        ros.loc[pid, list(STATS)] = (per_game * new_gp).to_numpy()
        ros.loc[pid, "gp"] = new_gp
        for col in ros.columns.difference(["gp", *STATS]):
            if pd.api.types.is_float_dtype(ros[col]):
                ros.loc[pid, col] = np.nan          # kaynaktaki yüzde vb. artık bu satırı anlatmaz
        filled.append(pid)
    return filled
