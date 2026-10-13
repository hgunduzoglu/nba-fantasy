"""Arka plan analiz işçisi (README §13.10): draft ilerledikçe advisor'ı kendiliğinden çalıştırır.

Draft sayfası (mock ya da canlı) her durumda ``publish`` eder; işçi iş parçacığı en son durumu işler.
Yeni bir pick gelince süren iş iptal edilir (ilerleme geri çağrısında) ve yeni durumdan başlanır.
Öncelik sırası:

1. rakip strateji modeli (canlı draft) ve kategori panosu — saniyenin altında;
2. sıra kullanıcıdaysa hızlı mod advisor, ardından tam mod (rakip modeli ile);
3. boş kalan sürede punt planı karşılaştırması (kullanıcının kadrosu + ağırlıklar değiştiğinde).

Streamlit'e bağımlı değildir; arayüz sonuçları ``snapshot()`` ile okur.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field, replace

from fdo.advisor.board import CategoryBoard, category_board
from fdo.advisor.pairs import AdvisorError, AdvisorResult, recommend
from fdo.advisor.scenarios import PlanResult, compare_punt_plans
from fdo.advisor.simulate import AdvisorContext
from fdo.bots.inference import ProfileTracker
from fdo.draft.events import DraftLog


class Cancelled(Exception):
    """Daha yeni bir draft durumu geldi."""


@dataclass(frozen=True)
class Job:
    ctx: AdvisorContext
    log: DraftLog
    live: bool
    weights: tuple[tuple[str, float], ...]
    seat_names: tuple[tuple[int, str], ...] = ()
    source: str = ""

    @property
    def key(self) -> tuple:
        return (id(self.ctx), tuple(p.player_id for p in self.log.picks), self.live, self.weights)

    @property
    def weight_dict(self) -> dict[str, float] | None:
        w = dict(self.weights)
        return w if w and any(abs(v - 1.0) > 1e-9 for v in w.values()) else None

    @property
    def roster_key(self) -> tuple:
        user = self.ctx.config.league.my_seat
        return (id(self.ctx), tuple(p.player_id for p in self.log.picks if p.seat == user), self.weights,
                self.live)


@dataclass
class Snapshot:
    """İşçinin son durumu (arayüz okur; kopyadır)."""

    rev: int = 0                                   # her sonuç güncellemesinde artar
    job: Job | None = None
    board: CategoryBoard | None = None
    fast: AdvisorResult | None = None
    full: AdvisorResult | None = None
    punt: PlanResult | None = None
    punt_pick: int | None = None                   # punt planının hesaplandığı pick
    opponents: object | None = None                # OpponentModel
    step: str = ""                                 # sürmekte olan iş
    progress: tuple[int, int] = (0, 0)
    busy: bool = False
    errors: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def advice(self) -> AdvisorResult | None:
        """En iyi mevcut öneri (tam mod varsa o)."""
        return self.full or self.fast


class AnalysisWorker:
    """``full``/``punt_sims``/``board_sims`` verilmezse işin config'indeki ``advisor.background_*`` kullanılır."""

    def __init__(self, *, full: bool | None = None, punt_sims: int | None = None, board_sims: int | None = None):
        self.full_mode = full
        self.punt_sims = punt_sims
        self.board_sims = board_sims
        self._cond = threading.Condition()
        self._pending: Job | None = None
        self._snap = Snapshot()
        self._punt_key: tuple | None = None
        self._tracker: ProfileTracker | None = None
        self._tracker_ctx: int | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- arayüz tarafı
    def publish(self, ctx: AdvisorContext, log: DraftLog, *, live: bool, weights: dict[str, float] | None = None,
                seat_names: dict[int, str] | None = None, source: str = "") -> None:
        job = Job(ctx=ctx, log=log, live=live, weights=tuple(sorted((weights or {}).items())),
                  seat_names=tuple(sorted((seat_names or {}).items())), source=source)
        with self._cond:
            current = self._pending or self._snap.job
            if current is not None and current.key == job.key:
                if current.seat_names != job.seat_names and self._pending is None:
                    self._snap.job = replace(self._snap.job, seat_names=job.seat_names)
                    self._snap.rev += 1
                return
            self._pending = job
            self._cond.notify_all()
        self._ensure_thread()

    def set_weights(self, weights: dict[str, float] | None) -> None:
        """Strateji ağırlıklarını değiştirip son durumu yeniden işler."""
        with self._cond:
            base = self._pending or self._snap.job
        if base is not None:
            self.publish(base.ctx, base.log, live=base.live, weights=weights, seat_names=dict(base.seat_names),
                         source=base.source)

    def snapshot(self) -> Snapshot:
        with self._cond:
            s = self._snap
            return replace(s, errors=list(s.errors), timings=dict(s.timings))

    @property
    def weights(self) -> dict[str, float] | None:
        with self._cond:
            job = self._pending or self._snap.job
        return job.weight_dict if job else None

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Testler için: bekleyen iş kalmayana kadar bekler."""
        end = time.monotonic() + timeout
        with self._cond:
            while self._pending is not None or self._snap.busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

    # ------------------------------------------------------------- iş parçacığı
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="fdo-analysis", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while self._pending is None:
                    self._cond.wait()
                job, self._pending = self._pending, None
                new_state = self._snap.job is None or self._snap.job.key != job.key
                self._snap.job = job
                self._snap.busy = True
                if new_state:
                    self._snap.board = self._snap.fast = self._snap.full = None
                    self._snap.errors = []
                    self._snap.timings = {}
                self._snap.rev += 1
            try:
                self._process(job)
            except Cancelled:
                pass
            except Exception as e:                       # noqa: BLE001 — işçi ölmemeli
                self._set(errors=[*self._snap.errors, f"{type(e).__name__}: {e}"])
                traceback.print_exc()
            with self._cond:
                self._snap.busy = self._pending is not None
                self._snap.step = ""
                self._snap.progress = (0, 0)
                self._snap.rev += 1
                self._cond.notify_all()

    def _set(self, **kw) -> None:
        with self._cond:
            for k, v in kw.items():
                setattr(self._snap, k, v)
            self._snap.rev += 1

    def _check(self) -> None:
        if self._pending is not None:
            raise Cancelled

    def _progress(self, step: str):
        def cb(*args):
            self._check()
            i, n = (args[-2], args[-1]) if len(args) >= 2 else (0, 0)
            with self._cond:
                self._snap.step = step
                self._snap.progress = (int(i), int(n))
        return cb

    def _timed(self, name: str, fn):
        t0 = time.perf_counter()
        self._set(step=name, progress=(0, 0))
        out = fn()
        with self._cond:
            self._snap.timings[name] = time.perf_counter() - t0
        return out

    def _process(self, job: Job) -> None:
        ctx, log = job.ctx, job.log
        cfg = ctx.config
        user = cfg.league.my_seat
        if log.is_complete:
            return
        snap = self._snap
        adv = cfg.model.advisor
        full_mode = adv.background_full if self.full_mode is None else self.full_mode
        punt_sims = adv.background_punt_sims if self.punt_sims is None else self.punt_sims
        board_sims = adv.background_board_sims if self.board_sims is None else self.board_sims

        opp_probs = None
        if job.live:
            if self._tracker is None or self._tracker_ctx != id(ctx):
                self._tracker = ProfileTracker(ctx.universe, cfg, n_draws=200, seed=ctx.seed)
                self._tracker_ctx = id(ctx)
            model = self._timed("Rakip stratejileri", lambda: self._tracker.update(log))
            self._set(opponents=model)
            opp_probs = model.seat_probs()
        else:
            self._set(opponents=None)
        self._check()

        if snap.board is None:
            b = self._timed("Oyuncu panosu", lambda: category_board(
                ctx, log, category_weights=job.weight_dict, n_sims=board_sims, opponent_probs=opp_probs))
            self._set(board=b)
        self._check()

        if log.next_seat == user:
            modes = ["fast", "full"] if full_mode else ["fast"]
            for mode in modes:
                if getattr(snap, mode) is not None:
                    continue
                label = {"fast": "Advisor (hızlı mod)", "full": "Advisor (tam mod)"}[mode]
                try:
                    res = self._timed(label, lambda m=mode, lb=label: recommend(
                        ctx, log, mode=m, conditional_fill=True, opponent_probs=opp_probs,
                        category_weights=job.weight_dict, progress=self._progress(lb)))
                except AdvisorError as e:
                    self._set(errors=[*snap.errors, str(e)])
                    break
                self._set(**{mode: res})
                self._check()

        if punt_sims > 0 and self._punt_key != job.roster_key:
            try:
                plans = self._timed("Punt planları", lambda: compare_punt_plans(
                    ctx, log, n_sims=punt_sims, custom_weights=job.weight_dict,
                    progress=self._progress("Punt planları")))
            except AdvisorError:
                plans = None
            self._punt_key = job.roster_key
            self._set(punt=plans, punt_pick=log.next_pick)
