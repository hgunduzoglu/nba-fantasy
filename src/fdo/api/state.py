"""API sunucusunun önbellekli durumu: veri, lig motorları, haftalık model ve sezon simülasyonu.

Veri dosyaları değişince (``file_signature``) her şey yeniden kurulur. Önbellek boyutu sınırlıdır.
Uvicorn istekleri iş parçacıklarında çalıştırdığı için kurulum bir kilitle korunur.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

import pandas as pd

from fdo.config import REPO_ROOT
from fdo.inseason.fixtures import load_fixtures
from fdo.inseason.injuries import latest_file, with_injuries
from fdo.inseason.season import SeasonResult, SeasonSim
from fdo.inseason.standings import league_standings, load_standings
from fdo.inseason.weekly import WeekModel
from fdo.inseason.weeks import LeagueWeeks, league_weeks
from fdo.trade import TradeData, TradeEngine, load_trade_data
from fdo.trade.data import file_signature
from fdo.trade.strategy import CATEGORIES, Strategy
from fdo.types import STATS
from fdo.valuation import value_players

DEFAULT_DATA = REPO_ROOT / "data" / "real"
SOURCES = {"ros": "remaining_games_projection", "season": "season_total", "preseason": "preseason"}


class AppState:
    def __init__(self, data_dir: str | Path | None = None, *, max_items: int = 48):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA
        self._lock = threading.RLock()
        self._cache: OrderedDict[tuple, object] = OrderedDict()
        self.max_items = max_items

    def _get(self, key: tuple, build: Callable[[], object]):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            value = build()
            self._cache[key] = value
            while len(self._cache) > self.max_items:
                self._cache.popitem(last=False)
            return value

    # ------------------------------------------------------------- veri ve motorlar
    def signature(self) -> str:
        return file_signature(self.data_dir)

    def injury_file(self) -> Path | None:
        return latest_file(self.data_dir)

    def data(self, injuries: bool = True) -> TradeData:
        sig = self.signature()
        base = self._get(("data", sig), lambda: load_trade_data(self.data_dir))
        if not injuries:
            return base
        return self._get(("data_inj", sig), lambda: with_injuries(base, self.data_dir))

    def engine(self, league_id: str, injuries: bool = True) -> TradeEngine:
        data = self.data(injuries)
        if str(league_id) not in data.leagues:
            raise KeyError(f"Lig yok: {league_id}")
        return self._get(("engine", data.fingerprint, str(league_id)), lambda: TradeEngine(data, str(league_id)))

    def weeks(self, league_id: str, injuries: bool = True) -> LeagueWeeks:
        eng = self.engine(league_id, injuries)
        return self._get(("weeks", eng.data.fingerprint, str(league_id)),
                         lambda: league_weeks(eng.data.schedule, eng.league.settings, eng.config))

    def week_model(self, league_id: str, injuries: bool = True, strategy: Strategy | None = None,
                   out_statuses: tuple[str, ...] | None = None) -> WeekModel:
        eng = self.engine(league_id, injuries)
        s = strategy or Strategy()
        kwargs = {} if out_statuses is None else {"out_statuses": out_statuses}
        return self._get(("week_model", eng.data.fingerprint, str(league_id), s, out_statuses),
                         lambda: WeekModel(eng, strategy=s, **kwargs))

    def fixtures(self) -> pd.DataFrame:
        return self._get(("fixtures", self.signature()), lambda: load_fixtures(self.data_dir))

    def season_sim(self, league_id: str, injuries: bool = True) -> SeasonSim | None:
        eng = self.engine(league_id, injuries)

        def build():
            fx = self.fixtures()
            if not (fx["league_id"] == str(league_id)).any():
                return None
            standings = league_standings(load_standings(self.data_dir), league_id, eng.league.teams)
            return SeasonSim(self.week_model(league_id, injuries), self.weeks(league_id, injuries), fx, standings,
                             eng.data.as_of)
        return self._get(("season_sim", eng.data.fingerprint, str(league_id)), build)

    def season_base(self, league_id: str, injuries: bool, n_sims: int, sd: float, seed: int = 1) -> SeasonResult | None:
        sim = self.season_sim(league_id, injuries)
        if sim is None:
            return None
        eng = self.engine(league_id, injuries)
        return self._get(("season_base", eng.data.fingerprint, str(league_id), n_sims, round(sd, 4), seed),
                         lambda: sim.run(n_sims=n_sims, seed=seed, strength_sd=sd))

    def per_game_z(self, league_id: str, source: str, injuries: bool = True) -> pd.DataFrame:
        """Seçilen kaynağın maç başı dengeli z'si (renklendirme için), ``player_id`` × kategori."""
        eng = self.engine(league_id, injuries)
        mode = SOURCES[source]

        def build():
            f = eng.data.stats[mode]
            ok = (f["gp"] > 0) & f[list(STATS)].notna().all(axis=1)
            proj = f.loc[ok, list(STATS)].div(f.loc[ok, "gp"], axis=0)
            proj = proj.assign(player_id=proj.index, projected_gp=f.loc[ok, "gp"])
            if proj.empty:
                return pd.DataFrame(columns=list(CATEGORIES))
            return value_players(proj, eng.config, basis="per_game", method="z").scores
        return self._get(("z", eng.data.fingerprint, str(league_id), source), build)
