"""Veri sağlayıcıları (``fdo.ingest.provider``): elle alınan anlık görüntü, arşiv partisi, kapalı Yahoo API."""
import json

import pytest

from fdo.ingest import archive
from fdo.ingest.provider import ArchivedSnapshotProvider, ManualSnapshotProvider, ProviderUnavailable, YahooApiProvider

REQUIRED = {"rosters.json": json.dumps({"roster_date": "2026-11-10", "leagues": []}), "league_info.json": "{}",
            "player_stat_pages.json": "[]", "players_yahoo_2026-10-12.csv": "yahoo_player_id\n1\n",
            "projections_yahoo_2026-10-12.csv": "player_id,as_of\ny_1,2026-10-12\n",
            "schedule_nba_2026-27.csv": "game_date\n2026-10-20\n"}


def _write(d, files):
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")


def test_manual_provider_uses_the_current_files(tmp_path):
    p = ManualSnapshotProvider(tmp_path)
    with pytest.raises(ProviderUnavailable):
        p.directory()
    _write(tmp_path, REQUIRED)
    assert p.directory() == tmp_path
    caps = p.capabilities()
    assert caps["rosters"] and caps["player_stats"] and not caps["live_week"] and caps["write"] is False


def test_archived_provider_restores_a_complete_batch_once(tmp_path):
    _write(tmp_path, REQUIRED)
    full = archive.archive(tmp_path, source="test").batch_id
    (tmp_path / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-11", "leagues": []}), encoding="utf-8")
    p = ArchivedSnapshotProvider(tmp_path, full, tmp_path / "work")
    d = p.directory()
    assert json.loads((d / "rosters.json").read_text(encoding="utf-8"))["roster_date"] == "2026-11-10"
    assert p.directory() == d and p.capabilities()["rosters"]
    partial = archive.archive(tmp_path, source="test", files=[tmp_path / "rosters.json"]).batch_id
    with pytest.raises(ProviderUnavailable, match="eksik"):
        ArchivedSnapshotProvider(tmp_path, partial, tmp_path / "work").directory()


def test_yahoo_api_provider_is_off_until_access_is_granted():
    p = YahooApiProvider()
    assert not any(p.capabilities().values())
    with pytest.raises(ProviderUnavailable, match="onaylanmadı"):
        p.directory()
