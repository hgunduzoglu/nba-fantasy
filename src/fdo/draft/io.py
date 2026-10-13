"""Draft log CSV/JSON import/export (README §5.3, §6.3.2).

Export, kullanılan manifest'lerin kaynak kaydını ve seed bilgisini taşır.
CSV'de bu bilgi ``#`` ile başlayan başlık satırlarında saklanır.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path

import pandas as pd

from fdo.config import Config
from fdo.draft.events import DraftError, DraftLog, DraftPick
from fdo.ingest import schema

COLUMNS = schema.column_names("draft_log")


def log_to_frame(log: DraftLog) -> pd.DataFrame:
    return pd.DataFrame([p.to_dict() for p in log.picks], columns=COLUMNS)


def export_json(log: DraftLog, meta: dict | None = None) -> str:
    payload = {
        "meta": {"teams": log.teams, "rounds": log.rounds,
                 "third_round_reversal": log.third_round_reversal, **(meta or {})},
        "picks": [p.to_dict() for p in log.picks],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def export_csv(log: DraftLog, meta: dict | None = None) -> str:
    buf = io.StringIO()
    m = {"teams": log.teams, "rounds": log.rounds,
         "third_round_reversal": log.third_round_reversal, **(meta or {})}
    for k, v in m.items():
        buf.write(f"# {k}: {json.dumps(v, ensure_ascii=False, default=str)}\n")
    log_to_frame(log).to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def _parse_time(v) -> dt.datetime:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return dt.datetime(1970, 1, 1)
    return pd.Timestamp(v).to_pydatetime()


def _picks_from_records(records) -> list[DraftPick]:
    out = []
    for r in records:
        try:
            out.append(DraftPick(
                overall_pick=int(r["overall_pick"]), round=int(r["round"]), seat=int(r["seat"]),
                player_id=str(r["player_id"]), source=str(r.get("source") or "import"),
                observed_at=_parse_time(r.get("observed_at")),
            ))
        except (KeyError, ValueError, TypeError) as e:
            raise DraftError(f"Geçersiz pick satırı {r}: {e}") from e
    return sorted(out, key=lambda p: p.overall_pick)


def import_log(text: str, config: Config, fmt: str | None = None) -> tuple[DraftLog, dict]:
    """CSV ya da JSON metninden ``DraftLog``. Seat tutarsızlığı ve tekrar seçim hatadır."""
    fmt = fmt or ("json" if text.lstrip().startswith("{") else "csv")
    if fmt == "json":
        data = json.loads(text)
        meta = data.get("meta", {})
        records = data.get("picks", [])
    else:
        meta = {}
        body = []
        for line in text.splitlines():
            if line.startswith("#"):
                k, _, v = line[1:].partition(":")
                try:
                    meta[k.strip()] = json.loads(v.strip())
                except json.JSONDecodeError:
                    meta[k.strip()] = v.strip()
            else:
                body.append(line)
        df = pd.read_csv(io.StringIO("\n".join(body)), dtype=str)
        records = df.to_dict("records")
    lg = config.league
    for key, expect in (("teams", lg.teams), ("rounds", lg.rounds),
                        ("third_round_reversal", lg.third_round_reversal)):
        if key in meta and meta[key] != expect:
            raise DraftError(f"Log {key}={meta[key]!r}, config {expect!r}")
    log = DraftLog.replay(lg.teams, lg.rounds, lg.third_round_reversal, _picks_from_records(records))
    return log, meta


def save(log: DraftLog, path: str | Path, meta: dict | None = None) -> None:
    path = Path(path)
    text = export_json(log, meta) if path.suffix == ".json" else export_csv(log, meta)
    path.write_text(text, encoding="utf-8")


def load(path: str | Path, config: Config) -> tuple[DraftLog, dict]:
    path = Path(path)
    return import_log(path.read_text(encoding="utf-8"), config,
                      "json" if path.suffix == ".json" else "csv")


#: İsimli draft sonucu kolonları (küçük harf, eş anlamlılar).
NAME_COLUMNS = {
    "pick": ("pick", "overall", "overall_pick", "#", "no"),
    "player": ("player", "name", "player_name", "oyuncu"),
    "auto": ("auto", "autopick", "auto_pick", "otomatik"),
}
_TRUE = {"1", "true", "yes", "y", "evet", "x", "auto"}


def import_names(text: str, players: pd.DataFrame, config: Config) -> tuple[DraftLog, list[str]]:
    """İsimli draft sonucu (CSV/TSV: pick, oyuncu adı, opsiyonel auto) → ``DraftLog``.

    Koltuk pick numarasından snake sırasıyla türetilir (``config.league``; farklı lig büyüklüğü için
    ``fdo.calibration.bots.league_config``). Adlar ``players`` dosyasına ad/alias ile eşlenir; eşleşmeyen
    ya da belirsiz ad hatadır (öneriler mesajda). Otomatik seçilen pick'ler ``import:auto`` kaynağı alır.
    """
    from fdo.ingest.load import resolve_player_ids
    from fdo.ingest.validate import ValidationReport

    sep = "\t" if text.count("\t") > text.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    cols = {c.strip().lower(): c for c in df.columns}
    found = {k: next((cols[a] for a in alias if a in cols), None) for k, alias in NAME_COLUMNS.items()}
    if found["player"] is None:
        raise DraftError(f"Oyuncu adı kolonu yok (beklenen: {NAME_COLUMNS['player']}); kolonlar: {list(df.columns)}")
    if found["pick"] is not None:
        df = df.assign(_pick=pd.to_numeric(df[found["pick"]], errors="coerce")).sort_values("_pick", kind="mergesort")
    names = df[found["player"]].astype(str).str.strip()
    rep = ValidationReport()
    resolved = resolve_player_ids(pd.DataFrame({"name": names.to_numpy()}), players, "draft", rep)
    if not rep.ok:
        raise DraftError("; ".join(rep.errors[:10]))
    auto = (df[found["auto"]].astype(str).str.strip().str.lower().isin(_TRUE).to_numpy()
            if found["auto"] is not None else [False] * len(df))
    lg = config.league
    log = DraftLog.new(config)
    for pid, a in zip(resolved["player_id"], auto):
        log = log.make_pick(str(pid), "import:auto" if a else "import",
                            observed_at=dt.datetime(1970, 1, 1))
    notes = [f"{len(log)} pick ({lg.teams} takım, {lg.rounds} tur), {int(sum(auto))} otomatik"]
    return log, notes
