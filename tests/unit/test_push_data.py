"""Veriyi sunucuya gönderme: hangi dosyalar gider, arşiv sunucuda güvenle ve yerinde açılır (ağ yok)."""
import io
import os
import tarfile

import pytest

import push_data
import receive_data


def test_keep_skips_snapshots_contacts_and_notes():
    assert push_data.keep("data/real/rosters.json") and push_data.keep("data/real/injuries_cbs_2026-11-09.csv")
    assert not push_data.keep("data/real/snapshots/2026-11-08/rosters.json")
    assert not push_data.keep("data/real/managers.json") and not push_data.keep("data/real/ROSTERS_README.txt")
    assert not push_data.keep("data/real/standings_week1_capture.json") and not push_data.keep("data/real/x.json.tmp")
    # yerel arşiv nesneleri, karar günlüğü ve referans vaka ölçümleri gitmez; elle kimlik düzeltmeleri gider
    assert not push_data.keep("data/real/snapshots/objects/ab/abcd.gz")
    assert not push_data.keep("data/real/decisions/2026-11.jsonl")
    assert not push_data.keep("data/real/evaluation/cases_x.json") and not push_data.keep("data/real/cases.json")
    assert push_data.keep("data/real/id_overrides.csv")


def test_archive_round_trip_replaces_files_and_keeps_mtime(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "data" / "real").mkdir(parents=True)
    (src / "data" / "real" / "rosters.json").write_text('{"v": 2}', encoding="utf-8")
    os.utime(src / "data" / "real" / "rosters.json", (1_700_000_000, 1_700_000_000))
    (dst / "data" / "real").mkdir(parents=True)
    (dst / "data" / "real" / "rosters.json").write_text('{"v": 1}', encoding="utf-8")
    (dst / "data" / "real" / "keep.csv").write_text("a", encoding="utf-8")
    blob = push_data.archive(["data/real/rosters.json"], src)
    assert receive_data.receive(blob, dst) == ["data/real/rosters.json"]
    out = dst / "data" / "real" / "rosters.json"
    assert out.read_text(encoding="utf-8") == '{"v": 2}' and int(out.stat().st_mtime) == 1_700_000_000
    assert (dst / "data" / "real" / "keep.csv").exists()
    assert not [p for p in (dst / "data").iterdir() if p.name.startswith(".incoming-")]


@pytest.mark.parametrize("name", ["../evil.json", "/etc/passwd", "data/other/x.json", "src/fdo/app.py", "data/real"])
def test_receive_rejects_paths_outside_data_real(tmp_path, name):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError):
        receive_data.receive(buf.getvalue(), tmp_path)
    assert list((tmp_path / "data" / "real").iterdir()) == []
