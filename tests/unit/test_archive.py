"""Değiştirilemez ham veri arşivi (``fdo.ingest.archive``) ve dosya zamanları (``fdo.ingest.timestamps``)."""
import datetime as dt
import gzip
import json

import pytest

from fdo.ingest import archive as A
from fdo.ingest.timestamps import file_times

T0 = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def d(tmp_path):
    (tmp_path / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-09", "captured_at": "2026-11-09T11:55:58Z",
                                                       "leagues": []}), encoding="utf-8")
    (tmp_path / "injuries_cbs_2026-11-09.csv").write_text(
        "name,captured_at\nA,2026-11-09T12:01:02+00:00\nB,2026-11-09T12:01:03+00:00\n", encoding="utf-8")
    (tmp_path / "schedule_nba_2026-27.csv").write_text("game_date,home_team,away_team\n2026-10-20,A,B\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("arşive girmez", encoding="utf-8")
    return tmp_path


def _objects(d):
    return sorted(p.name for p in (d / "snapshots" / "objects").rglob("*.gz"))


def test_same_content_is_stored_once_and_needs_no_new_batch(d):
    first = A.archive(d, source="manual", now=T0)
    assert first.created and first.new_objects == 3 and first.files == 3
    again = A.archive(d, source="manual", now=T0 + dt.timedelta(hours=1))
    assert not again.created and again.batch_id == first.batch_id and len(A.batches(d)) == 1
    assert len(_objects(d)) == 3


def test_change_makes_a_new_batch_and_keeps_the_old_one(d):
    first = A.archive(d, source="yahoo_sync", now=T0)
    old = (d / "rosters.json").read_bytes()
    (d / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-10", "leagues": []}), encoding="utf-8")
    second = A.archive(d, source="yahoo_sync", now=T0 + dt.timedelta(days=1))
    assert second.created and second.new_objects == 1 and len(_objects(d)) == 4
    m = A.get(d, second.batch_id)
    assert m["previous_batch_id"] == first.batch_id and m["timezone"] == "UTC"
    assert m["files"]["rosters.json"]["source_as_of"] == "2026-11-10"
    assert m["files"]["rosters.json"]["captured_at"] is None              # dosyada kayıt yok: uydurulmaz
    assert m["files"]["rosters.json"]["file_modified_at"]                 # disk zamanı ayrı alan
    out = A.restore(d, first.batch_id, d / "replay")
    assert (d / "replay" / "rosters.json").read_bytes() == old and len(out) == 3
    with pytest.raises(ValueError):
        A.restore(d, first.batch_id, d / "replay")                       # boş olmayan hedef
    with pytest.raises(KeyError):
        A.get(d, "yok")


def test_manifest_times_coverage_and_missing_inputs(d):
    m = A.get(d, A.archive(d, source="manual", now=T0).batch_id)
    assert m["schema_version"] == A.SCHEMA_VERSION and m["source"] == "manual"
    assert m["ingested_at"] == "2026-11-09T12:00:00+00:00" and m["batch_id"].startswith("20261109T120000Z-")
    assert set(m["files"]) == {"rosters.json", "injuries_cbs_2026-11-09.csv", "schedule_nba_2026-27.csv"}
    r = m["files"]["rosters.json"]
    assert (r["component"], r["source_as_of"], r["captured_at"]) == ("rosters", "2026-11-09", "2026-11-09T11:55:58Z")
    assert m["files"]["injuries_cbs_2026-11-09.csv"]["captured_at"] == "2026-11-09T12:01:03+00:00"
    assert not m["complete"] and "league_info.json" in m["missing"] and "player_stat_pages.json" in m["missing"]


def test_verify_finds_a_corrupt_object(d):
    bid = A.archive(d, source="manual", now=T0).batch_id
    assert A.verify(d) == []
    obj = next((d / "snapshots" / "objects").rglob("*.gz"))
    obj.write_bytes(gzip.compress(b"bozuk"))
    assert len(A.verify(d, bid)) == 1
    with pytest.raises(ValueError):
        A.restore(d, bid, d / "replay")


def test_failed_archive_leaves_no_batch(d, monkeypatch):
    calls = []

    def boom(directory, digest, path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk dolu")
        return True
    monkeypatch.setattr(A, "_store", boom)
    with pytest.raises(OSError):
        A.archive(d, source="manual", now=T0)
    assert A.batches(d) == [] and A.latest(d) is None


def test_file_times_by_component(tmp_path):
    p = tmp_path / "gamelogs_nba_2026-27.csv"
    p.write_text("name,game_date\nA,2026-11-07\nB,2026-11-08\n", encoding="utf-8")
    assert file_times(p)["source_as_of"] == "2026-11-08" and file_times(p)["component"] == "nba_logs"
    q = tmp_path / "injuries_cbs_2026-10-31.csv"
    q.write_text("name\nA\n", encoding="utf-8")                          # eski biçim: zaman sütunu yok
    t = file_times(q)
    assert t["captured_at"] is None and t["captured_on"] == "2026-10-31"
    bad = tmp_path / "rosters.json"
    bad.write_text("{bozuk", encoding="utf-8")
    assert file_times(bad)["source_as_of"] is None


def test_restored_real_batch_reproduces_the_analysis(tmp_path):
    """Gerçek anlık görüntü (yalnız yerelde): arşivden geri yüklenen girdiler aynı analizi verir."""
    import numpy as np

    from fdo.config import REPO_ROOT
    from fdo.trade import TradeEngine, load_trade_data

    real = REPO_ROOT / "data" / "real"
    if not (real / "rosters.json").exists() or not (real / "player_stat_pages.json").exists():
        pytest.skip("Kişisel Yahoo anlık görüntüleri repoda bulunmak zorunda değil")
    store = tmp_path / "store"
    store.mkdir()
    bid = A.archive(store, source="test", files=A.input_files(real)).batch_id
    assert A.get(store, bid)["complete"]
    A.restore(store, bid, tmp_path / "replay")
    live, replay = load_trade_data(real), load_trade_data(tmp_path / "replay")
    assert live.as_of == replay.as_of and live.issues == replay.issues
    lid = next(iter(live.leagues))
    a, b = TradeEngine(live, lid), TradeEngine(replay, lid)
    np.testing.assert_array_equal(a.market.to_numpy(), b.market.to_numpy())
    np.testing.assert_array_equal(a.league_probabilities().to_numpy(), b.league_probabilities().to_numpy())
