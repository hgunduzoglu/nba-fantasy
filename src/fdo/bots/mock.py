"""Tek draft arayüzleri: ``BotLeague`` (README §6.4.4) ve mock draft denetleyicisi.

``MockDraft`` event log'u (``DraftLog``) ile tek simülasyonlu ``BatchDraft``'ı
senkron tutar. Undo/truncate sonrası motor log'dan yeniden kurulur; titreşim
``(seed, s, k)``'dan türediği için aynı pick aynı rastgele sayıları görür.
"""

from __future__ import annotations

import numpy as np

from fdo.bots.thurstone import BatchDraft
from fdo.bots.universe import BotUniverse, build_universe
from fdo.config import Config
from fdo.draft.events import DraftError, DraftLog
from fdo.draft.rules import check_pick, validate_log
from fdo.draft.state import DraftState
from fdo.ingest.load import Dataset
from fdo.roster.assignment import RosterModel


def replay_into(engine: BatchDraft, player_ids_in_order) -> None:
    engine.reset()
    for pid in player_ids_in_order:
        if pid not in engine.u.index:
            raise DraftError(f"{pid} draft havuzunda yok")
        engine.force(engine.u.index[pid])


class BotLeague:
    """15 rakibin kalıcı algılanan sıraları ve profilleri (tek draft)."""

    def __init__(self, engine: BatchDraft):
        self.engine = engine

    @classmethod
    def sample(cls, dataset: Dataset, config: Config, rng: np.random.Generator,
               universe: BotUniverse | None = None) -> "BotLeague":
        universe = universe or build_universe(dataset, config)
        seed = int(rng.integers(0, 2**63 - 1))
        return cls(BatchDraft(universe, config, 1, seed))

    @property
    def profiles(self) -> list[str]:
        return self.engine.profile_names(0)

    def choose(self, seat: int, state: DraftState, rng: np.random.Generator | None = None) -> str:
        """``state``'teki sıradaki koltuk için seçilen ``player_id`` (state değişmez)."""
        if state.next_seat != seat:
            raise DraftError(f"Sıra {state.next_seat} koltuğunda, {seat} değil")
        order = sorted(state.pick_owner.items(), key=lambda kv: kv[1][1])
        replay_into(self.engine, [pid for pid, _ in order])
        score, ok = self.engine.scores()
        i = int(np.argmin(np.where(ok, score, np.inf)[0]))
        return str(self.engine.u.ids[i])


class MockDraft:
    """Mock draft: bot oynatma, manuel seçim, undo/truncate, log yükleme."""

    def __init__(self, dataset: Dataset, config: Config, seed: int,
                 universe: BotUniverse | None = None):
        self.dataset = dataset
        self.config = config
        self.seed = int(seed)
        self.universe = universe or build_universe(dataset, config)
        self.engine = BatchDraft(self.universe, config, 1, self.seed)
        self.log = DraftLog.new(config)
        self._positions = dataset.positions().to_dict()
        self._roster_model = RosterModel(config)

    @property
    def profiles(self) -> list[str]:
        return self.engine.profile_names(0)

    @property
    def my_seat(self) -> int:
        return self.config.league.my_seat

    def _sync(self) -> None:
        replay_into(self.engine, [p.player_id for p in self.log.picks])

    def set_log(self, log: DraftLog) -> None:
        """Log'u yükler; pozisyon kuralı açıksa her pick denetlenir (§3.2)."""
        validate_log(log, self._positions, self.config)
        self.log = log
        self._sync()

    def pick(self, player_id: str, source: str = "user") -> None:
        if player_id not in self.universe.index:
            raise DraftError(f"{player_id} draft havuzunda yok")
        check_pick(self.log, player_id, self._positions, self.config, self._roster_model)
        new_log = self.log.make_pick(player_id, source)
        self.engine.force(self.universe.index[player_id])
        self.log = new_log

    def play_next(self) -> str:
        seat = self.log.next_seat
        if seat is None:
            raise DraftError("Draft tamamlandı")
        choice = int(self.engine.bot_step()[0])
        pid = str(self.universe.ids[choice])
        self.log = self.log.make_pick(pid, f"bot:{self.profiles[seat - 1]}")
        return pid

    def play_until_user(self) -> None:
        while not self.log.is_complete and self.log.next_seat != self.my_seat:
            self.play_next()

    def play_to_end(self) -> None:
        while not self.log.is_complete:
            self.play_next()

    def undo(self) -> None:
        self.log = self.log.undo()
        self._sync()

    def truncate(self, overall_pick: int) -> None:
        self.log = self.log.truncate(overall_pick)
        self._sync()

    def is_allowed(self, player_id: str) -> bool:
        """Sıradaki pick için pozisyon kuralına uygun mu?"""
        try:
            check_pick(self.log, player_id, self._positions, self.config, self._roster_model)
        except DraftError:
            return False
        return True
