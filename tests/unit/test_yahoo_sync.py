"""Yahoo sayfa ayrıştırıcıları ve senkronizasyon: sentetik HTML (gerçek lig verisi depoya girmez)."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from fdo.ingest import archive
from fdo.ingest import yahoo_html as Y
from fdo.ingest.yahoo_sync import is_live, sync

LID = "500"


def _player(pid, name, team_pos, status=None, game=""):
    st = (f'<span class="ysf-player-status Nowrap F-injury Fz-xxs"><span class="Pstart-sm" title="Out">{status}'
          f'</span></span>') if status else ""
    return (f'<div class="ysf-player-name"><a class="Nowrap name F-link playernote" data-ys-playerid="{pid}" '
            f'href="https://sports.yahoo.com/nba/players/{pid}">{name}</a>{st}'
            f'<span class="player-status D-ib"><span>Player Note</span></span>'
            f'<span class="D-b"><span class="Fz-xxs">{team_pos}</span> </span></div>'
            f'<div class="ysf-player-detail"><span class="ysf-game-status ">{game}</span></div>')


def _home(week=3, pairs=(("1", "2"),), me="1"):
    rows = "".join(f'<tr><td>{i + 1}</td><td><a href="/nba/{LID}/{t}">Team {t}</a></td><td>{w}-{18 - w}-0</td>'
                   f'<td>.5</td><td>-</td><td>4-5-0</td><td>$90</td><td>{i + 1}</td><td>3</td></tr>'
                   for i, (t, w) in enumerate((("1", 10), ("2", 8))))
    links = "".join(f'<a href="/nba/{LID}/matchup?week={week}&amp;mid1={a}&amp;mid2={b}">x</a>' for a, b in pairs)
    return (f'<html><body><a href="/nba/{LID}/{me}/editteaminfo">edit</a>{links}<table id="standingstable"><thead>'
            '<tr><th>Rank</th><th>Team</th><th>W-L-T</th><th>Pct</th><th>GB</th><th>Last Week</th>'
            f'<th>Waiver Bdgt</th><th>Waiver</th><th>Moves</th></tr></thead><tbody>{rows}</tbody></table>'
            '<script>var x = "<table>";</script></body></html>')


def _rosters():
    team = lambda t, players: (
        f'<p class="W-100 Fz-med"><a href="/nba/{LID}/{t}">Team {t}</a></p>'
        f'<table id="Tst-team-{t}"><thead><tr><th>Pos</th><th>Player</th></tr></thead><tbody>'
        + "".join(f'<tr><td class="pos">{slot}</td><td class="player">{cell}</td></tr>' for slot, cell in players)
        + "</tbody></table>")
    empty = '<div class="emptyplayer"><span>(Empty)</span></div>'
    return ("<html><body>"
            + team("1", [("PG", _player("11", "Ann A", "LAL - PG,SG", game="7:00 pm vs ATL")),
                         ("BN", _player("12", "Bob B", "BOS - C")), ("IL", _player("13", "Cy C", "NYK - SF", "O")),
                         ("C", empty)])
            + team("2", [("PG", _player("21", "Dee D", "DEN - PG"))]) + "</body></html>")


def _matchup(a="1", b="2", wa=5, wb=3):
    row = lambda t, fg, w: (f'<tr><td><a href="/nba/{LID}/{t}">Team {t}</a></td><td>{fg}</td><td>.5</td>'
                            f'<td>10/12</td><td>.83</td><td>5</td><td>1,050</td><td>40</td><td>20</td><td>7</td>'
                            f'<td>3</td><td>11</td><td><div>{w}</div></td></tr>')
    return ('<table class="Table Datatable"><thead><tr><th>Team</th><th>FGM/A*</th><th>FG%</th><th>FTM/A*</th>'
            '<th>FT%</th><th>3PTM</th><th>PTS</th><th>REB</th><th>AST</th><th>ST</th><th>BLK</th><th>TO</th><th></th>'
            f'</tr></thead><tbody>{row(a, "40/80", wa)}{row(b, "1,001/2,000", wb)}</tbody></table>')


def _players(rows):
    head = ["", "", "Players", "Opp", "Roster Status", "GP*", "Pre-Season", "Current", "% Ros", "MPG", "FGM/A*",
            "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO", ""]
    body = ""
    for pid, name, owner in rows:
        own = f'<a href="/nba/{LID}/{owner}">Team {owner}</a>' if owner.isdigit() else owner
        nums = ["70", "1", "2", "90%", "-", "500/1,000", ".500", "100/125", ".800", "100", "1500", "400", "300",
                "80", "40", "120", ""]
        body += (f'<tr><td></td><td></td><td>{_player(pid, name, "LAL - PG,SG", "GTD")}</td><td></td><td>{own}</td>'
                 + "".join(f"<td><div>{x}</div></td>" for x in nums) + "</tr>")
    return ('<table><thead><tr><th colspan="5">Rankings</th></tr><tr>' + "".join(f"<th>{h}</th>" for h in head)
            + f"</tr></thead><tbody>{body}</tbody></table>")


# ------------------------------------------------------------------ ayrıştırıcılar
def test_league_home_reads_standings_week_and_my_team():
    home = Y.parse_league_home(_home(pairs=(("1", "2"), ("3", "4"))), LID)
    assert home["week"] == 3 and home["my_team"] == "1"
    assert home["matchups"] == [("1", "2"), ("3", "4")]
    assert home["standings"][0] == {"team_id": "1", "team_name": "Team 1", "wins": 10, "losses": 8, "ties": 0,
                                    "rank": 1, "waiver_priority": 1, "moves": 3, "fab": 90}
    assert home["standings"][1]["team_id"] == "2"


def test_starting_rosters_keep_slots_status_and_skip_empty():
    teams = Y.parse_starting_rosters(_rosters(), LID)
    assert [(t["team_id"], t["team_name"], len(t["slots"])) for t in teams] == [("1", "Team 1", 3), ("2", "Team 2", 1)]
    pg, bn, il = teams[0]["slots"]
    assert (pg["player_id"], pg["nba_team"], pg["eligible_positions"], pg["game"]) == ("11", "LAL", ["PG", "SG"],
                                                                                         "7:00 pm vs ATL")
    assert bn["is_bench"] and not bn["is_injury_slot"]
    assert il["is_injury_slot"] and il["status"] == "O" and il["status_description"] == "Out"
    assert "\nLAL - PG,SG" in pg["raw_text"]


def test_matchup_totals_parse_counts_with_thousands():
    rows = Y.parse_matchup(_matchup(), LID)
    assert [r["team_id"] for r in rows] == ["1", "2"]
    assert rows[0]["totals"] == {"fgm": 40, "fga": 80, "ftm": 10, "fta": 12, "fg3m": 5, "pts": 1050, "reb": 40,
                                 "ast": 20, "stl": 7, "blk": 3, "tov": 11}
    assert rows[1]["totals"]["fgm"] == 1001 and rows[1]["totals"]["fga"] == 2000
    assert (rows[0]["category_wins"], rows[1]["category_wins"]) == (5, 3)


def test_team_page_reads_adds_il_and_budget():
    html = ("<div>You have used 2 of your 4 player adds for this week.</div><div>You have used 3 of 4 IL positions on"
            " your roster.</div><span>Waiver Budget: $87</span>")
    assert Y.parse_team_page(html) == {"adds_used": 2, "adds_limit": 4, "il_used": 3, "il_slots": 4, "fab": 87}


def test_player_table_matches_stat_page_format_and_loader_regex():
    table = Y.parse_player_table(_players([("11", "Ann A", "1"), ("31", "Fay F", "W (Nov 9)"), ("32", "Gus G", "FA")]),
                                 LID)
    h = table["headers"][-1]
    assert h[h.index("GP*")] == "GP*" and "Roster Status" in h
    first = table["rows"][0]
    assert first["cells"][h.index("FGM/A*")] == "500/1,000"
    assert "\nLAL - PG,SG" in first["cells"][2]                    # load_trade_data adı/takımı buradan okur
    assert (first["owner_team_id"], first["status"], first["positions"]) == ("1", "GTD", ["PG", "SG"])
    assert [r["roster_status"] for r in table["rows"][1:]] == ["W (Nov 9)", "FA"]


def test_waiver_date_rolls_year():
    assert Y.waiver_date("W (Nov 9)", dt.date(2026, 11, 7)) == dt.date(2026, 11, 9)
    assert Y.waiver_date("W (Jan 2)", dt.date(2026, 12, 31)) == dt.date(2027, 1, 2)
    assert Y.waiver_date("FA", dt.date(2026, 11, 7)) is None


def test_live_window():
    assert not is_live(pd.Timestamp("2026-11-07 09:00", tz="America/New_York"))
    assert is_live(pd.Timestamp("2026-11-07 20:00", tz="America/New_York"))
    assert is_live(pd.Timestamp("2026-11-08 01:00", tz="America/New_York"))


# ------------------------------------------------------------------ senkronizasyon
@pytest.fixture
def real_dir(tmp_path):
    rosters = {"schema_version": "1.0", "season": "2026-27", "roster_date": "2026-10-31", "leagues": [
        {"league_id": LID, "league_name": "Test", "teams": [{"team_id": "1", "slots": []}, {"team_id": "2", "slots": []}]}]}
    matchups = {"complete": True, "matchups": [
        {"league_id": LID, "week": w, "team_a_id": "1", "team_b_id": "2", "result_status": "not_collected"}
        for w in (1, 2, 3)]}
    (tmp_path / "rosters.json").write_text(json.dumps(rosters), encoding="utf-8")
    (tmp_path / "matchups.json").write_text(json.dumps(matchups), encoding="utf-8")
    return tmp_path


def _site(week=3):
    pages = {f"/nba/{LID}": _home(week), f"/nba/{LID}/startingrosters": _rosters(),
             f"/nba/{LID}/1": "<p>You have used 1 of your 4 player adds for this week.</p><p>Waiver Budget: $90</p>",
             f"/nba/{LID}/players?status=W&pos=P&stat1=S_PSR&sort=AR&sdir=1&count=0":
                 _players([("31", "Fay F", "W (Nov 9)")])}
    for w in range(1, week + 1):
        pages[f"/nba/{LID}/matchup?date=totals&week={w}&mid1=1&mid2=2"] = _matchup(wa=4 + w % 2, wb=4)
    asked = []

    def fetch(path):
        asked.append(path)
        return pages[path]
    return fetch, asked


def test_sync_writes_snapshots_and_fills_finished_weeks(real_dir):
    fetch, asked = _site()
    now = pd.Timestamp("2026-11-07 09:00", tz="America/New_York")
    res = sync(real_dir, fetch, players=False, now=now)
    assert res.as_of == dt.date(2026, 11, 7) and not res.live
    # eski dosya üzerine yazılmadan önce arşivlendi; yeni hâl ayrı parti
    before, after = archive.batches(real_dir)
    assert after["batch_id"] == res.batch_id and after["previous_batch_id"] == before["batch_id"]
    assert before["files"]["rosters.json"]["source_as_of"] == "2026-10-31" and "yahoo_live.json" not in before["files"]
    assert after["files"]["rosters.json"]["source_as_of"] == "2026-11-07" and "yahoo_live.json" in after["files"]
    rosters = json.loads((real_dir / "rosters.json").read_text(encoding="utf-8"))
    assert rosters["roster_date"] == "2026-11-07" and len(rosters["leagues"][0]["teams"]) == 2
    m = json.loads((real_dir / "matchups.json").read_text(encoding="utf-8"))
    done = {x["week"]: x for x in m["matchups"]}
    assert done[1]["result_status"] == "final" and done[1]["team_a_category_wins"] == 5
    assert done[1]["winner_team_id"] == "1" and done[2]["tied_categories"] == 1
    assert done[3]["result_status"] == "not_collected"            # süren hafta matchups.json'a yazılmaz
    live = json.loads((real_dir / "yahoo_live.json").read_text(encoding="utf-8"))["leagues"][LID]
    assert (live["week"], live["my_team"], live["adds_used"], live["fab"]) == (3, "1", 1, 90)
    assert live["matchups"][0]["team_a_totals"]["pts"] == 1050
    assert live["waivers"] == [{"player_id": "31", "player_name": "Fay F", "until": "2026-11-09"}]
    st = pd.read_csv(real_dir / "standings_live.csv", dtype=str)
    assert st[["team_id", "wins"]].values.tolist() == [["1", "10"], ["2", "8"]]
    # ikinci çalıştırma biten haftaları yeniden çekmez
    fetch2, asked2 = _site()
    sync(real_dir, fetch2, players=False, now=now)
    assert not any("week=1&" in p or "week=2&" in p for p in asked2)


def test_sync_stops_without_writing_when_a_page_breaks(real_dir):
    fetch, _ = _site()
    broken = lambda p: "<html>bakım</html>" if p.endswith("startingrosters") else fetch(p)
    with pytest.raises(RuntimeError):
        sync(real_dir, broken, players=False, now=pd.Timestamp("2026-11-07 09:00", tz="America/New_York"))
    assert json.loads((real_dir / "rosters.json").read_text(encoding="utf-8"))["roster_date"] == "2026-10-31"
    assert not (real_dir / "yahoo_live.json").exists()
