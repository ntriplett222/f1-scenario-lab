#!/usr/bin/env python3
"""Refresh data/season-2026.json from completed OpenF1 sessions.

Stdlib-only so it runs on GitHub Actions without installing packages.
The updater is incremental: existing wins/podiums and old race results are kept,
and only newly completed GP/Sprint sessions are fetched in detail.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SEASON = 2026
API = "https://api.openf1.org/v1"
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / f"season-{SEASON}.json"
RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SPRINT_POINTS = [8, 7, 6, 5, 4, 3, 2, 1]
USER_AGENT = "f1-scenario-lab-github-updater/1.0"


def fetch_json(endpoint: str, params: dict | None = None, retries: int = 3):
    query = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{API}/{endpoint}" + (f"?{query}" if query else "")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OpenF1 request failed: {url}: {last}")


def parse_time(value: str | None):
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_team(name: str | None) -> str:
    n = (name or "").strip()
    return {
        "Red Bull": "Red Bull Racing",
        "Haas": "Haas F1 Team",
        "McLaren Mercedes": "McLaren",
        "Aston Martin Aramco": "Aston Martin",
    }.get(n, n)


def short_name(name: str | None, location: str | None) -> str:
    n = (name or "").replace(" Grand Prix", " GP")
    if "Bahrain" in n and (location or "") in {"Kuala Lumpur", "Sepang"}:
        return "Bahrain GP in Malaysia"
    if n == "Barcelona GP":
        return "Barcelona-Catalunya GP"
    return n


def local_date(iso: str, offset: str | None):
    d = parse_time(iso)
    if not d:
        return None
    off = offset or "+00:00:00"
    sign = -1 if off.startswith("-") else 1
    h, m, *_ = off.lstrip("+-").split(":")
    return d + dt.timedelta(minutes=sign * (int(h) * 60 + int(m)))


def format_dates(meeting: dict) -> str:
    a = local_date(meeting.get("date_start"), meeting.get("gmt_offset"))
    b = local_date(meeting.get("date_end"), meeting.get("gmt_offset"))
    if not a or not b:
        return ""
    if a.strftime("%b") == b.strftime("%b"):
        return f"{a.strftime('%b')} {a.day}–{b.day}"
    return f"{a.strftime('%b')} {a.day}–{b.strftime('%b')} {b.day}"


def is_gp_meeting(m: dict) -> bool:
    return not m.get("is_cancelled") and "Grand Prix" in (m.get("meeting_name") or "") and "Testing" not in (m.get("meeting_name") or "")


def session_name(s: dict) -> str:
    return (s.get("session_name") or "").strip().lower()


def points_for(pos: int, sprint: bool = False) -> int:
    arr = SPRINT_POINTS if sprint else RACE_POINTS
    return arr[pos - 1] if 1 <= pos <= len(arr) else 0


def substantive(obj: dict) -> dict:
    x = copy.deepcopy(obj)
    x.pop("updatedAt", None)
    return x


def main() -> int:
    old = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)

    meetings = fetch_json("meetings", {"year": SEASON})
    sessions = fetch_json("sessions", {"year": SEASON})
    gp_meetings = sorted([m for m in meetings if is_gp_meeting(m)], key=lambda m: m["date_start"])
    round_by_meeting = {int(m["meeting_key"]): i + 1 for i, m in enumerate(gp_meetings)}
    active_meetings = set(round_by_meeting)
    rel_sessions = [s for s in sessions if int(s.get("meeting_key", -1)) in active_meetings]
    races = [s for s in rel_sessions if session_name(s) == "race"]
    sprints = [s for s in rel_sessions if session_name(s) == "sprint"]

    completed_races = sorted(
        [s for s in races if parse_time(s.get("date_end")) and parse_time(s["date_end"]) <= now],
        key=lambda s: s["date_end"], reverse=True,
    )

    official = None
    for rs in completed_races[:4]:
        try:
            dc = fetch_json("championship_drivers", {"session_key": rs["session_key"]})
            tc = fetch_json("championship_teams", {"session_key": rs["session_key"]})
            top = fetch_json("session_result", {"session_key": rs["session_key"], "position<": 4})
            if dc and tc and top:
                official = (rs, dc, tc)
                break
        except Exception:
            continue
    if not official:
        raise RuntimeError("No completed race with published championship standings was found.")

    official_race, driver_champ, team_champ = official
    official_round = round_by_meeting[int(official_race["meeting_key"])]
    old_last_round = int(old.get("lastRaceRound") or 0)

    # Latest completed session roster tracks substitutions/team changes as soon as a session is historical.
    completed_sessions = sorted(
        [s for s in rel_sessions if parse_time(s.get("date_end")) and parse_time(s["date_end"]) <= now],
        key=lambda s: s["date_end"], reverse=True,
    )
    latest_roster = []
    for s in completed_sessions[:5]:
        try:
            latest_roster = fetch_json("drivers", {"session_key": s["session_key"]})
            if latest_roster:
                break
        except Exception:
            pass
    if not latest_roster:
        latest_roster = fetch_json("drivers", {"session_key": official_race["session_key"]})

    drivers = copy.deepcopy(old["drivers"])
    constructors = copy.deepcopy(old["constructors"])
    old_calendar_by_meeting = {int(r["meetingKey"]): copy.deepcopy(r) for r in old["calendar"]}
    d_by_num = {int(d["number"]): d for d in drivers}
    d_by_id = {d["id"]: d for d in drivers}
    c_by_name = {canonical_team(c["name"]): c for c in constructors}

    roster_by_num = {int(r["driver_number"]): r for r in latest_roster}
    for d in drivers:
        d["active"] = False
    for row in driver_champ:
        n = int(row["driver_number"])
        d = d_by_num.get(n)
        if not d:
            rr = roster_by_num.get(n, {})
            acronym = (rr.get("name_acronym") or f"#{n}").upper()
            d = {"id": acronym, "number": n, "name": rr.get("full_name") or acronym, "team": canonical_team(rr.get("team_name")), "points": 0, "wins": 0, "podiums": 0, "active": False}
            drivers.append(d); d_by_num[n] = d; d_by_id[d["id"]] = d
        d["points"] = int(row.get("points_current") or 0)
        rr = roster_by_num.get(n)
        if rr:
            d["id"] = (rr.get("name_acronym") or d["id"]).upper()
            d["team"] = canonical_team(rr.get("team_name")) or d["team"]
    for n, rr in roster_by_num.items():
        d = d_by_num.get(n)
        if d:
            d["active"] = True
            d["team"] = canonical_team(rr.get("team_name")) or d["team"]

    for row in team_champ:
        name = canonical_team(row.get("team_name"))
        c = c_by_name.get(name)
        if c:
            c["points"] = int(row.get("points_current") or 0)

    # Rebuild calendar from the current revised meetings list while retaining known results.
    calendar = []
    race_by_meeting = {int(s["meeting_key"]): s for s in races}
    sprint_by_meeting = {int(s["meeting_key"]): s for s in sprints}
    for i, m in enumerate(gp_meetings, start=1):
        mk = int(m["meeting_key"])
        prior = old_calendar_by_meeting.get(mk, {})
        ss = sprint_by_meeting.get(mk)
        calendar.append({
            **prior,
            "round": i,
            "meetingKey": mk,
            "name": short_name(m.get("meeting_name"), m.get("location")),
            "place": "Sepang" if "Bahrain" in (m.get("meeting_name") or "") and m.get("location") == "Kuala Lumpur" else (m.get("location") or prior.get("place", "")),
            "date": format_dates(m) or prior.get("date", ""),
            "completed": i <= official_round,
            "sprint": bool(ss) or bool(prior.get("sprint")),
            "sprintCompleted": bool(prior.get("sprintCompleted")),
            "current": parse_time(m.get("date_start")) <= now <= parse_time(m.get("date_end")),
        })
    cal_by_round = {r["round"]: r for r in calendar}

    # New GP(s): add podium, win and podium counters incrementally.
    for round_no in range(old_last_round + 1, official_round + 1):
        m = gp_meetings[round_no - 1]
        rs = race_by_meeting.get(int(m["meeting_key"]))
        if not rs:
            continue
        results = fetch_json("session_result", {"session_key": rs["session_key"]})
        roster = fetch_json("drivers", {"session_key": rs["session_key"]})
        rb = {int(x["driver_number"]): x for x in roster}
        podium = []
        for result in sorted(results, key=lambda x: int(x.get("position") or 999)):
            pos = int(result.get("position") or 999)
            if pos > 3:
                continue
            rr = rb.get(int(result["driver_number"]), {})
            did = (rr.get("name_acronym") or d_by_num.get(int(result["driver_number"]), {}).get("id"))
            if not did:
                continue
            did = did.upper()
            podium.append(did)
            d = next((x for x in drivers if x["id"] == did), None)
            if d:
                if pos == 1: d["wins"] = int(d.get("wins", 0)) + 1
                d["podiums"] = int(d.get("podiums", 0)) + 1
            team = canonical_team(rr.get("team_name") or (d or {}).get("team"))
            c = c_by_name.get(team)
            if c:
                if pos == 1: c["wins"] = int(c.get("wins", 0)) + 1
                c["podiums"] = int(c.get("podiums", 0)) + 1
        cal_by_round[round_no]["podium"] = podium

    # Sprints: lock completed ones. If a Sprint is newer than the latest completed GP,
    # add its points to the prior GP championship baseline until Sunday's race supersedes them.
    latest_sprint_after_gp = None
    for ss in sorted(sprints, key=lambda s: s.get("date_end") or ""):
        end = parse_time(ss.get("date_end"))
        if not end or end > now:
            continue
        round_no = round_by_meeting[int(ss["meeting_key"])]
        r = cal_by_round[round_no]
        prior = old_calendar_by_meeting.get(int(ss["meeting_key"]), {})
        if prior.get("sprintCompleted") and prior.get("sprintWinner"):
            r["sprintCompleted"] = True
            r["sprintWinner"] = prior["sprintWinner"]
        else:
            results = fetch_json("session_result", {"session_key": ss["session_key"]})
            roster = fetch_json("drivers", {"session_key": ss["session_key"]})
            rb = {int(x["driver_number"]): x for x in roster}
            for result in results:
                pos = int(result.get("position") or 999)
                rr = rb.get(int(result["driver_number"]), {})
                did = (rr.get("name_acronym") or d_by_num.get(int(result["driver_number"]), {}).get("id"))
                if pos == 1 and did:
                    r["sprintWinner"] = did.upper()
                if round_no > official_round:
                    pts = points_for(pos, sprint=True)
                    if pts and did:
                        d = next((x for x in drivers if x["id"] == did.upper()), None)
                        if d: d["points"] += pts
                        team = canonical_team(rr.get("team_name") or (d or {}).get("team"))
                        c = c_by_name.get(team)
                        if c: c["points"] += pts
            r["sprintCompleted"] = True
        if round_no > official_round:
            latest_sprint_after_gp = r

    official_meeting = gp_meetings[official_round - 1]
    last_race_name = short_name(official_meeting.get("meeting_name"), official_meeting.get("location"))
    baseline_label = f"After {latest_sprint_after_gp['name']} Sprint" if latest_sprint_after_gp else f"After {last_race_name}"

    new = {
        "schemaVersion": 3,
        "season": SEASON,
        "updatedAt": old.get("updatedAt"),
        "baselineLabel": baseline_label,
        "lastRaceRound": official_round,
        "lastRaceName": last_race_name,
        "lastSessionName": "Sprint" if latest_sprint_after_gp else "Race",
        "drivers": drivers,
        "constructors": constructors,
        "calendar": calendar,
    }

    if substantive(new) == substantive(old):
        print("No championship/session change detected; snapshot unchanged.")
        return 0

    new["updatedAt"] = now.isoformat().replace("+00:00", "Z")
    DATA_PATH.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {DATA_PATH}: {baseline_label}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
