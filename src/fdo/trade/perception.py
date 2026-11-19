"""Algılanan değer ve yanlış fiyatlama: sat-yüksek / al-düşük (README §13.15).

Menajerler oyuncuya genelde bu sezonun rakamlarıyla (ya da sezon öncesi isim değeriyle) bakar; bizim
karar ölçümüz kalan sezon projeksiyonudur (ROS). İkisini aynı ölçeğe koymak için:

1. Algılanan sıra: ``season_total`` bu sezonun maç başı dengeli z değerine göre (en az ``min_gp`` maç; daha azı
   sezon öncesi sırasına düşer). ``preseason`` isim değeridir: menajerlerin sezon öncesi fiyatlaması, yani ligin
   kendi draftı (açık artırmada ödenen fiyat, yılan draftta seçim sırası) ile Yahoo ADP'sinin ortalama sırası
   (README §13.30); draft edilmeyenler arkada, sezon öncesi projeksiyon sırasıyla. Draft verisi yoksa sezon öncesi
   projeksiyonun z sırası. ``blend`` iki sıranın ortalamasıdır.
2. Algılanan fiyat: o sıradaki oyuncunun ROS piyasa değeri (``engine.market`` sıralı dizisi). Böylece
   "bu sezon 25. görünen oyuncu" piyasada ROS'un 25. oyuncusu kadar değer görür.
3. ``edge = algılanan fiyat − ROS değeri`` (piyasa birimi): pozitif = sat-yüksek adayı (olduğundan iyi
   görünüyor), negatif = al-düşük hedefi. Oran kullanılmaz: yedek seviyesindeki oyuncularda (ROS ≈ 0.1)
   anlamsız büyür.

``market`` (varsayılan) menajerin takas ekranında gördüğüdür (README §13.56): Yahoo'nun güncel sırası (bu sezonun
toplamları; sakat kaldığı maçlar sırayı düşürür) ve Yahoo genelinde kadroda olma oranı (isim değeri ve güncel algı).
İkisinin sıralarının ortalaması; Yahoo sütunları olmayan oyuncu ``blend`` sırasına düşer. Sakat (Yahoo O/INJ/D ya da
dönüş tarihli sakatlık) ya da takımının maçlarının ``MISSED_SHARE``'inden azında oynamış ama hâlâ yaygın kadroda olan
oyuncunun güncel sırası kaçırdığı maçlarla düşer; menajer ona sağlıklı isim değeriyle bakar, bu yüzden fiyatı ``market``
ve ``blend`` fiyatlarının büyüğüdür (sıralar değişmez, diğer oyuncuların fiyatı kaymaz).

Rakibin gözünde oran (``opponent_view``) toplamların oranıdır, iki düzeltmeyle: aldığı oyuncu sayısı verdiğinden
fazlaysa kadrosundaki en düşük algılanan değerli oyuncular (gelenler dahil) bırakılır ve aldığından düşülür (dolgu
oyuncu değer sayılmaz); her oyuncu yalnız yedek seviyesinin (ligdeki ``REPLACEMENT_FA``. en iyi sağlıklı serbest
oyuncunun algılanan fiyatı) üstündeki değeriyle sayılır, tabanı piyasa ölçeğinin tabanı ``FLOOR`` (serbestten
alınabilecek oyuncu pakete değer katmaz); takasın en değerli oyuncusunu veren taraf için ``gives_best`` (bkz.
``counterpart``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from fdo.types import STATS
from fdo.valuation import value_players

PERCEPTIONS = {"market": "Yahoo'da görünen (güncel sıra + kadroda olma oranı)", "season_total": "Bu sezonun rakamları",
               "preseason": "Sezon öncesi isim değeri (draft sırası)", "blend": "Bu sezon + sezon öncesi ortalaması"}
DEFAULT_PERCEPTION = "market"
ABSENT_STATUS = {"O", "INJ", "D"}      # sakat görünen Yahoo durumları (OFS/NA sezon dışı: isim değeri korunmaz)
MISSED_SHARE = .75                      # takımının maçlarının bundan azında oynamış ...
HELD_PCT = 50.0                         # ... ve Yahoo'da en az bu oranda kadroda (isim değeri korunuyor)
REPLACEMENT_FA = 3                      # yedek seviyesi: ligdeki kaçıncı en iyi sağlıklı serbest oyuncu
FLOOR = .1                              # yedek seviyesindeki oyuncunun değeri (``engine.market`` tabanı)


def _per_game_rank(engine: TradeEngine, mode: str, ids: list[str], min_gp: float = 0.0) -> pd.Series:
    f = engine.data.stats[mode].reindex(ids)
    ok = f["gp"].fillna(0) > max(min_gp, 0) - 1e-9
    ok &= f[list(STATS)].notna().all(axis=1) & (f["gp"] > 0)
    proj = f.loc[ok, list(STATS)].div(f.loc[ok, "gp"], axis=0)
    if proj.empty:
        return pd.Series(np.nan, index=ids)
    proj = proj.assign(player_id=proj.index, projected_gp=f.loc[ok, "gp"])
    v = value_players(proj, engine.config, basis="per_game", method="z").table["V"]
    return v.rank(ascending=False, method="first").reindex(ids)


def draft_rank(engine: TradeEngine, ids: list[str]) -> pd.Series | None:
    """Sezon öncesi piyasa sırası (küçük = değerli): ligin kendi draftı (fiyat varsa fiyat, yoksa seçim sırası) ve
    Yahoo ADP'si; ikisi de varsa sıraların ortalaması. Draft verisi yoksa ``None``, draft edilmeyen oyuncu NaN."""
    ranks = []
    if engine.data.adp is not None:
        adp = engine.data.adp.reindex(ids).dropna()
        if len(adp):
            ranks.append(adp.rank(method="average"))
    if engine.data.draft is not None:
        d = engine.data.draft
        d = d[d["league_id"] == engine.league.league_id].drop_duplicates("player_id").set_index("player_id")
        d = d.reindex([p for p in ids if p in d.index])
        key = -d["cost"].dropna() if d["cost"].notna().any() else d["pick"].dropna()
        if len(key):
            ranks.append(key.rank(method="average"))
    if not ranks:
        return None
    return pd.concat(ranks, axis=1).mean(axis=1).reindex(ids)


def _preseason_rank(engine: TradeEngine, ids: list[str]) -> pd.Series:
    proj = _per_game_rank(engine, "preseason", ids)
    market = draft_rank(engine, ids)
    if market is None or market.isna().all():
        return proj
    drafted = market.notna()
    rest = proj[~drafted].rank(method="first") + int(drafted.sum())
    rest = rest.fillna(float(len(ids)))
    return market[drafted].rank(method="first").reindex(ids).fillna(rest)


def perceived_ranks(engine: TradeEngine, basis: str = "season_total", *, min_gp: int = 3) -> pd.Series:
    """Modellenebilen oyuncu → algılanan sıra (1 = en iyi, boşluksuz)."""
    if basis not in PERCEPTIONS:
        raise ValueError(f"basis: {', '.join(PERCEPTIONS)} ({basis!r})")
    ids = [p for p in engine.ids if engine.modeled[engine.index[p]]]
    pre = _preseason_rank(engine, ids)
    if basis == "preseason":
        rank = pre
    else:
        cur = _per_game_rank(engine, "season_total", ids, min_gp)
        cur = cur.fillna(pre)
        rank = cur if basis == "season_total" else (cur + pre.fillna(cur)) / 2
        if basis == "market":
            rank = _market_rank(engine, ids).fillna(rank.rank(method="first"))
    return rank.rank(method="first")


def absent(engine: TradeEngine, ids: list[str]) -> pd.Series:
    """Sakat görünen (Yahoo durumu ya da dönüş tarihli sakatlık; sezon boyu yok olanlar hariç) ya da takımının
    maçlarının ``MISSED_SHARE``'inden azında oynamış, Yahoo'da en az ``HELD_PCT`` kadroda olan (menajerlerin isim
    değeriyle tuttuğu) oyuncular. Kadroda olma oranı yoksa yalnız sakatlık durumuna bakılır."""
    d = engine.data
    status = d.players["injury_status"].reindex(ids).fillna("").astype(str)
    out = status.isin(ABSENT_STATUS)
    if d.injuries is not None and "kind" in d.injuries.columns:
        kind = d.injuries["kind"].reindex(ids)
        out |= kind.eq("out_until")
        out &= ~kind.eq("season")
    if d.yahoo is not None:
        gp = d.stats["season_total"]["gp"].reindex(ids).fillna(0.0)
        team = d.players["nba_team"].reindex(ids).fillna("")
        played = gp.groupby(team).transform("max")
        out |= (gp < MISSED_SHARE * played) & team.ne("")
        out &= d.yahoo["pct_rostered"].reindex(ids) >= HELD_PCT
    out &= ~status.isin({"OFS", "NA"})
    return out.fillna(False).astype(bool)


def replacement_price(engine: TradeEngine, perceived: pd.Series) -> float:
    """Yedek seviyesi: ligdeki ``REPLACEMENT_FA``. en iyi sağlıklı serbest oyuncunun algılanan fiyatı."""
    pool = list(engine.free_agents)
    if not pool:
        return 0.0
    pool = [p for p, a in absent(engine, pool).items() if not a]
    vals = np.sort(perceived.reindex(pool).dropna().to_numpy(float))[::-1]
    return float(vals[min(REPLACEMENT_FA, len(vals)) - 1]) if len(vals) else 0.0


def _market_rank(engine: TradeEngine, ids: list[str]) -> pd.Series:
    """Yahoo'nun güncel sırası ile kadroda olma oranı sırasının ortalaması (biri eksikse diğeri); ikisi de yoksa NaN."""
    y = engine.data.yahoo
    if y is None:
        return pd.Series(np.nan, index=ids)
    y = y.reindex(ids)
    parts = pd.concat([y["rank_current"].rank(method="average"),
                       (-y["pct_rostered"]).rank(method="average")], axis=1)
    return parts.mean(axis=1)


def opponent_view(engine: TradeEngine, perceived: pd.Series, team: str, receive, give) -> float:
    """``team``'in gözünde aldığı / verdiği algılanan değer. Her oyuncu yedek seviyesinin üstündeki değeriyle sayılır
    (taban ``FLOOR``; modellenemeyen 0). Fazla gelen oyuncu kadar en düşük değerli oyuncusu (IL dışı; gelenler dahil,
    gidenler hariç) bırakılır ve aldığından düşülür. Verdiği değer 0 ise NaN. Yedek seviyesi ``perceived.attrs``
    içindeyse (``perceived_prices``) oradan, yoksa hesaplanır."""
    receive, give = list(receive), list(give)
    repl = perceived.attrs.get("replacement")
    repl = replacement_price(engine, perceived) if repl is None else float(repl)
    above = (perceived - repl).clip(lower=0.0) + FLOOR

    def price(ids):
        return above.reindex(ids).fillna(0.0)
    got, gave = float(price(receive).sum()), float(price(give).sum())
    extra = len(receive) - len(give)
    if extra > 0 and team in engine.league.rosters:
        il = engine.league.injury_rosters.get(team, frozenset())
        after = [p for p in engine.league.rosters[team] if p not in give and p not in il] + receive
        got -= float(np.sort(price(after).to_numpy(float))[:extra].sum())
    return max(got, 0.0) / gave if gave > 0 else float("nan")


def gives_best(perceived: pd.Series, receive, give) -> bool:
    """Takasın algılanan en değerli oyuncusu bu tarafın verdikleri arasında mı."""
    a = perceived.reindex(list(receive)).fillna(0.0)
    b = perceived.reindex(list(give)).fillna(0.0)
    return bool(len(b) and (not len(a) or b.max() > a.max()))


def perceived_prices(engine: TradeEngine, basis: str = "season_total", *, min_gp: int = 3) -> pd.Series:
    """Oyuncu → algılanan fiyat (ROS piyasa ölçeğinde); modellenemeyenler NaN."""
    rank = perceived_ranks(engine, basis, min_gp=min_gp)
    ids = list(rank.index)
    ladder = np.sort(engine.market.loc[ids].to_numpy(float))[::-1]

    def at(r: pd.Series) -> pd.Series:
        return pd.Series(ladder[(r.fillna(len(ladder)).astype(int).clip(1, len(ladder)) - 1).to_numpy()], index=ids)

    out = at(rank)
    if basis == "market":                     # sakat ya da çok maç kaçırmış: sağlıklı isim değerinin altına inmez
        out = out.where(~absent(engine, ids), np.maximum(out, at(perceived_ranks(engine, "blend", min_gp=min_gp))))
    out = out.reindex(engine.ids)
    out.attrs["replacement"] = replacement_price(engine, out)
    return out


def mispricing(engine: TradeEngine, perceived: pd.Series, team_ids=None) -> pd.DataFrame:
    """Kadrolu oyuncular: ROS değeri ve sırası, algılanan fiyat ve sırası, ``edge`` (azalan)."""
    owner = {p: t for t, r in engine.league.rosters.items() for p in r}
    modeled = [p for p in engine.ids if engine.modeled[engine.index[p]]]
    ros_rank = engine.market.loc[modeled].rank(ascending=False, method="first")
    per_rank = perceived.loc[modeled].rank(ascending=False, method="first")
    rows = []
    teams = set(team_ids) if team_ids is not None else set(engine.league.rosters)
    for p, t in owner.items():
        if t not in teams or not engine.modeled[engine.index[p]]:
            continue
        ros, per = float(engine.market[p]), float(perceived.get(p, np.nan))
        rows.append({"player_id": p, "team_id": t, "name": engine.data.players.loc[p, "name"],
                     "ros_value": ros, "perceived": per, "edge": per - ros,
                     "ros_rank": float(ros_rank[p]), "perceived_rank": float(per_rank[p]),
                     "gp_now": float(engine.data.stats["season_total"].loc[p, "gp"])
                     if p in engine.data.stats["season_total"].index else np.nan})
    df = pd.DataFrame(rows)
    return df.sort_values("edge", ascending=False).reset_index(drop=True) if len(df) else df


__all__ = ["DEFAULT_PERCEPTION", "PERCEPTIONS", "absent", "gives_best", "mispricing", "opponent_view", "perceived_prices",
           "perceived_ranks", "replacement_price", "ROS"]
