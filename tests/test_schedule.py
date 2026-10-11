import json

import pytest

from exnight import schedule


def _plan(plan_date, ledger, events):
    targets = [dict(event_id=e, symbol=e.split("-")[0], spot_symbol=e.split("-")[0].upper() + "USDT",
                    ex_date=ex, gross_dividend=0.5, reference_price=50.0, gross_yield_bp=100.0)
               for e, ex in events]
    groups = [dict(label=f"v3_{ex.replace('-', '')}_{e.split('-')[0].upper()}", ex_date=ex,
                   symbols=[e.split("-")[0].upper() + "USDT"], event_ids=[e],
                   sell_cutoff=f"{ex}T00:00:00-04:00", rung_0400=f"{ex}T04:00:00-04:00",
                   start=f"{ex}T00:00:00+00:00", end=f"{ex}T14:30:00+00:00") for e, ex in events]
    return dict(rule_id="exnight-strategy-v3", planned_at=f"{plan_date}T16:00:00+00:00", plan_date=plan_date,
                min_gross_yield_bp=66.7, horizon_days=21, selection="", reference_prices="", ledger=ledger,
                targets=targets, groups=groups)


def test_rounds_merge_in_order_and_keep_their_own_ledger(tmp_path):
    (tmp_path / "v3_schedule_r2.json").write_text(json.dumps(_plan("2026-10-11", "l2.jsonl", [("rB-2026-10-14-1", "2026-10-14")])))
    (tmp_path / "v3_schedule.json").write_text(json.dumps(_plan("2026-09-23", "l1.jsonl", [("rA-2026-09-25-1", "2026-09-25")])))
    (tmp_path / "v3_schedule_backup.json").write_text("{}")  # not a round; ignored
    plan = schedule.load(tmp_path)
    assert [t["round"] for t in plan["targets"]] == [1, 2]
    assert [g["ledger"] for g in plan["groups"]] == ["l1.jsonl", "l2.jsonl"]
    assert [(r["round"], r["first_ex_date"], r["last_ex_date"]) for r in plan["rounds"]] == [
        (1, "2026-09-25", "2026-09-25"), (2, "2026-10-14", "2026-10-14")]


def test_one_file_still_loads_on_its_own(tmp_path):
    path = tmp_path / "v3_schedule.json"
    path.write_text(json.dumps(_plan("2026-09-23", "l1.jsonl", [("rA-2026-09-25-1", "2026-09-25")])))
    assert schedule.load(path)["rounds"][0]["round"] == 1


def test_an_event_planned_twice_is_refused(tmp_path):
    (tmp_path / "v3_schedule.json").write_text(json.dumps(_plan("2026-09-23", "l1.jsonl", [("rA-2026-10-14-1", "2026-10-14")])))
    (tmp_path / "v3_schedule_r2.json").write_text(json.dumps(_plan("2026-10-11", "l2.jsonl", [("rA-2026-10-14-1", "2026-10-14")])))
    with pytest.raises(ValueError):
        schedule.load(tmp_path)


def test_real_round_one_is_unchanged():
    plan = schedule.load(schedule.FORWARD / "v3_schedule.json")
    assert len(plan["targets"]) == 16 and plan["rounds"][0]["last_ex_date"] == "2026-10-08"
