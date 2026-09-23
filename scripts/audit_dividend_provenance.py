"""Collect Bitget dividend-history leads without changing the frozen scorecard.

The endpoint is a present-day historical view. Its announcement date is useful for
finding primary evidence, but is not proof that the value was available at T0.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "data/results/competition_knowledge_time.csv"
LEDGER = ROOT / "data/ledger/reality_notice59_resolved.jsonl"
PRIMARY_REVIEW = ROOT / "data/sources/dividend_primary_review_20260923.csv"
ENDPOINT = "https://api.bitget.com/api/v3/reality/market/dividends"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _events() -> list[dict]:
    ledger = {row["event_id"]: row for row in map(json.loads, LEDGER.read_text().splitlines())}
    with KNOWLEDGE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return [dict(row, underlying=ledger[row["event_id"]]["underlying"],
                 ledger_announcement_date=ledger[row["event_id"]].get("announcement_date") or "")
            for row in rows if row["exclusion_reason"] == "NO_PRE_DECISION_GROSS_DECLARATION"]


def _date(value: object) -> str:
    if value is None or value == "":
        return ""
    value = str(value)
    if value.isdigit():
        return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.timezone.utc).astimezone(SHANGHAI).date().isoformat()
    return value[:10]


def fetch(path: Path) -> None:
    codes = sorted({row["underlying"] for row in _events()})
    responses = {}
    for index, code in enumerate(codes):
        if index:
            time.sleep(1.1)  # The documented public endpoint allows one request per second/IP.
        url = ENDPOINT + "?" + urllib.parse.urlencode({"code": code, "limit": 100})
        request = urllib.request.Request(url, headers={"User-Agent": "Exnight-evidence-audit/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            responses[code] = payload
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            responses[code] = {"error": str(exc)}
        print(f"{index + 1}/{len(codes)} {code}: {'error' if 'error' in responses[code] else 'received'}", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "endpoint": ENDPOINT, "responses": responses}, indent=2) + "\n")


def audit(raw_path: Path, output: Path) -> Counter:
    raw = json.loads(raw_path.read_text())
    with PRIMARY_REVIEW.open(newline="", encoding="utf-8") as stream:
        reviews = {row["event_id"]: row for row in csv.DictReader(stream)}
    rows = []
    for event in _events():
        payload = raw["responses"].get(event["underlying"], {})
        matches = []
        for record in (payload.get("data") or {}).get("list") or []:
            if record.get("type") != "cash_dividend" or _date(record.get("exrightDate")) != event["ex_date"]:
                continue
            try:
                if abs(Decimal(str(record["dividendPerShare"])) - Decimal(event["gross_dividend"])) > Decimal("0.000001"):
                    continue
            except (InvalidOperation, KeyError):
                continue
            matches.append(record)
        if payload.get("error") or payload.get("code") != "00000":
            status = "API_ERROR"
        elif len(matches) != 1:
            status = "AMBIGUOUS_MATCH" if matches else "NO_EXACT_MATCH"
        else:
            announced = _date(matches[0].get("announcementDate"))
            decision_date = event["decision_ts"][:10]
            status = ("PRE_DECISION_DATE_CANDIDATE" if announced and announced < decision_date else
                      "SAME_DAY_TIME_UNKNOWN" if announced == decision_date else "AFTER_DECISION_OR_UNDATED")
        record = matches[0] if len(matches) == 1 else {}
        review = reviews.get(event["event_id"], {})
        primary_status = "NOT_REVIEWED"
        if review:
            try:
                amount_matches = abs(Decimal(review["declared_amount"]) - Decimal(event["gross_dividend"])) <= Decimal("0.000001")
            except (InvalidOperation, KeyError):
                amount_matches = False
            if not amount_matches:
                primary_status = "PRIMARY_AMOUNT_MISMATCH"
            elif review["source_published_date"] >= event["decision_ts"][:10]:
                primary_status = "PRIMARY_DATE_NOT_EARLIER"
            elif status != "PRE_DECISION_DATE_CANDIDATE":
                primary_status = "API_DATE_NOT_EARLIER"
            else:
                primary_status = "MATCHED_PRE_DECISION_PRIMARY"
        rows.append({
            "event_id": event["event_id"], "symbol": event["symbol"],
            "underlying": event["underlying"], "ex_date": event["ex_date"],
            "decision_ts": event["decision_ts"], "ledger_gross_dividend": event["gross_dividend"],
            "ledger_announcement_date": event["ledger_announcement_date"],
            "api_announcement_date": _date(record.get("announcementDate")),
            "api_gross_dividend": record.get("dividendPerShare", ""),
            "audit_status": status, "primary_review_status": primary_status,
            "source_fetched_at": raw["fetched_at"],
            "predecision_publication_verified": "YES" if primary_status == "MATCHED_PRE_DECISION_PRIMARY" else "NO",
            "primary_source_url": review.get("source_url", ""),
            "primary_source_published_date": review.get("source_published_date", ""),
            "primary_declared_amount": review.get("declared_amount", ""),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return Counter(row["primary_review_status"] for row in rows)


def training_impact(audit_path: Path, output: Path) -> None:
    """Compare training-only fits; never re-score the already-viewed OOS window."""
    import pandas as pd
    from exnight.competition import (EVENT_RESULTS, ET, INITIAL_END, RUNG_ORDER,
                                     _eligible_frame, _estimate, select_rung)

    with audit_path.open(newline="", encoding="utf-8") as stream:
        verified = {row["event_id"] for row in csv.DictReader(stream)
                    if row["predecision_publication_verified"] == "YES"}
    original = _eligible_frame()
    additions = []
    for result in json.loads(EVENT_RESULTS.read_text()):
        if result["event_id"] not in verified:
            continue
        row = {
            "event_id": result["event_id"], "symbol": result["symbol"],
            "ex_date": pd.Timestamp(result["ex_date"]).date(),
            "decision_ts": pd.Timestamp(result["p_pre_ts"]),
            "p_pre": float(result["p_pre"]), "gross": float(result["gross_dividend"]),
            "fee_rate": float(result["fee_rate"]),
        }
        outcome_times = []
        for rung in RUNG_ORDER:
            row[f"p_{rung}"] = (result["p_post"] or {}).get(rung)
            row[f"ts_{rung}"] = (result["p_post_ts"] or {}).get(rung)
            if row[f"ts_{rung}"]:
                outcome_times.append(pd.Timestamp(row[f"ts_{rung}"]))
        row["outcome_observable_ts"] = max(outcome_times)
        additions.append(row)
    expanded = pd.concat([original, pd.DataFrame(additions)], ignore_index=True)
    windows = {
        "initial_development": lambda frame: frame[frame.ex_date <= INITIAL_END],
        "before_august_fold": lambda frame: frame[frame.outcome_observable_ts < pd.Timestamp(dt.datetime(2026, 7, 31, 20, tzinfo=ET))],
        "before_september_fold": lambda frame: frame[frame.outcome_observable_ts < pd.Timestamp(dt.datetime(2026, 8, 31, 20, tzinfo=ET))],
    }
    report = {"label": "TRAINING_ONLY_DIAGNOSTIC_NOT_OOS_VALIDATION",
              "verified_additions": len(additions), "windows": {}}
    for name, select in windows.items():
        report["windows"][name] = {}
        for label, frame in (("frozen_inputs", original), ("primary_verified_additions", expanded)):
            training = select(frame)
            rung, _ = select_rung(training)
            estimate = _estimate(training, rung)
            report["windows"][name][label] = {
                "training_events": len(training), "selected_rung": rung,
                "pdr": estimate["pdr"], "se": estimate["se"],
                "two_se_lower_bound": estimate["pdr"] - 2 * estimate["se"],
            }
    september_training = windows["before_september_fold"](expanded)
    report["leave_one_added_out_before_september"] = []
    for event_id in sorted(verified):
        training = september_training[september_training.event_id != event_id]
        rung, _ = select_rung(training)
        estimate = _estimate(training, rung)
        report["leave_one_added_out_before_september"].append({
            "omitted_event_id": event_id, "selected_rung": rung,
            "pdr": estimate["pdr"], "se": estimate["se"],
            "two_se_lower_bound": estimate["pdr"] - 2 * estimate["se"],
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="refresh the public Bitget snapshot")
    parser.add_argument("--training-impact-output", type=Path,
                        help="write a training-only fit comparison; never scores OOS returns")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.raw)
    print(json.dumps(dict(audit(args.raw, args.output)), indent=2))
    if args.training_impact_output:
        training_impact(args.output, args.training_impact_output)


if __name__ == "__main__":
    main()
