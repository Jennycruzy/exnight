"""Load the V3 forward schedule: one or more planned rounds, merged into one plan.

Round 1 is data/forward/v3_schedule.json (planned 23 Sep, ex-dates 25 Sep to 8 Oct). Each later
round is its own file, data/forward/v3_schedule_r<N>.json, written by plan_v3_forward.py before
any of its events is recorded. Planned files are never edited; a new round is a new file.

Every target and group carries its round number and the ledger it was selected from, so a
scorer can read each event from the ledger it was planned with.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORWARD = ROOT / "data" / "forward"


def round_of(path: Path) -> int:
    match = re.fullmatch(r"v3_schedule(?:_r(\d+))?\.json", path.name)
    if not match:
        raise ValueError(f"not a schedule file: {path.name}")
    return int(match.group(1) or 1)


def files(location: Path = FORWARD) -> list[Path]:
    """Schedule files at `location` (a directory of rounds, or one file), in round order."""
    if location.is_file():
        return [location]
    found = [p for p in location.glob("v3_schedule*.json") if re.fullmatch(r"v3_schedule(_r\d+)?\.json", p.name)]
    return sorted(found, key=round_of)


def load(location: Path = FORWARD) -> dict:
    """All rounds merged. Raises if two rounds share a group label or an event."""
    paths = files(location)
    # One file named explicitly is a single round, whatever it is called.
    plans = [(round_of(p) if location.is_dir() else 1, json.loads(p.read_text())) for p in paths]
    if not plans:
        raise FileNotFoundError(f"no V3 schedule at {location}")
    targets, groups, rounds = [], [], []
    seen_events, seen_labels = set(), set()
    for number, plan in plans:
        for t in plan.get("targets", []):
            if t["event_id"] in seen_events:
                raise ValueError(f"event {t['event_id']} is planned in two rounds")
            seen_events.add(t["event_id"])
            targets.append({**t, "round": number, "ledger": plan.get("ledger")})
        for g in plan["groups"]:
            label = g.get("label")
            if label is not None and label in seen_labels:
                raise ValueError(f"group {label} is planned in two rounds")
            seen_labels.add(label)
            groups.append({**g, "round": number, "ledger": plan.get("ledger")})
        rounds.append(dict(round=number, plan_date=plan.get("plan_date"), planned_at=plan.get("planned_at"),
                           events=len(plan.get("targets", [])),
                           first_ex_date=min((t["ex_date"] for t in plan.get("targets", [])), default=None),
                           last_ex_date=max((t["ex_date"] for t in plan.get("targets", [])), default=None)))
    first = plans[0][1]
    return dict(rule_id=first.get("rule_id"), min_gross_yield_bp=first.get("min_gross_yield_bp"),
                targets=targets, groups=groups, rounds=rounds)
