"""AI confounder analyst: reads the documents available at decision time and says whether
an event window is contaminated. It never computes a number and never issues a verdict;
`exnight.strategy` decides, and `exnight.confounders` keeps its deterministic flags.

Why a model at all: the deterministic flags are arithmetic on structured fields. The
reasons an ex-date window can be contaminated are often only in prose — a notice saying
weekend prices are market-maker reference quotes anchored to Friday's close, a perp
settlement scheduled two days before the spot ex-date, a re-listing, a halt window, a
distribution described as special. The analyst reads that prose and returns evidence.

As-of discipline. For every event the decision time is 19:55 ET on the last trading day
before the ex-date (five minutes before the EXIT cutoff). The analyst is given only
documents whose publication or fetch time is at or before that instant:

  disk mode (default)  the checksummed Bitget notices under data/sources/ with their
                       printed publication dates; the symbol's Reality corporate-action
                       rows and stock-info as fetched (fetch time recorded); the ledger
                       row itself. Every input is on disk, so a run is replayable.
  web mode             adds Anthropic's web_search tool. Search results carry no reliable
                       publication timestamp, so this mode is permitted only when the
                       decision time is in the future (the event has not happened); any
                       page that exists now was published before the decision. The run
                       records `as_of_guaranteed` accordingly.

Every call is logged under data/raw/ai_confounder/<event_id>/<run>.json with the model
id, the full request text, sha256 of each input, the raw response, usage and stop reason,
so a reviewer can replay the exact prompt. Results go to data/results/ai_confounders.csv.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from .calendar import read_ledger
from .events import CorporateAction
from .sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "ai_confounder"
RESULTS = ROOT / "data" / "results"
REALITY_RAW = ROOT / "data" / "raw" / "corporate_actions" / "reality"
ET = ZoneInfo("America/New_York")
DECISION_TIME = dt.time(19, 55)


# ---- output contract --------------------------------------------------------------

Status = Literal["CLEAN", "CONTAMINATED", "UNKNOWN"]
ContaminantType = Literal["earnings", "guidance_or_news", "split_or_reverse_split", "relisting", "trading_halt",
                          "other_dividend_in_window", "special_distribution", "weekend_or_holiday_session",
                          "perp_settlement", "index_or_fund_rebalance", "macro_or_market_wide", "other"]


class Evidence(BaseModel):
    source: str = Field(description="document id exactly as given in the input, e.g. 'bitget_notice:perp_dividend_2026_09_16' or 'reality_row:rAVGO-2026-09-21-1'")
    published_at: str = Field(description="publication or fetch timestamp of that document, copied from the input")
    quote: str = Field(description="short verbatim excerpt (<= 200 chars) the finding rests on")
    relevant: bool
    note: str


class Contaminant(BaseModel):
    type: ContaminantType
    description: str
    affects: Literal["pre_price", "post_price", "both", "dividend_amount"]
    published_at: str


class Analysis(BaseModel):
    status: Status
    abstain: bool = Field(description="true when the documents do not allow a judgement either way")
    confidence: Literal["low", "medium", "high"]
    contaminants: list[Contaminant]
    evidence: list[Evidence]
    rationale: str = Field(description="two to five sentences; cite sources by id")


SYSTEM = """You are the confounder analyst for a dividend event study on Bitget Reality rTokens
(tokenized US stocks and ETFs trading 24/5 in USDT). The study measures how much the rToken's
price drops between the last pre-event bar and fixed session rungs (20:00 ET, 04:00 ET, 09:30 ET)
around the ex-dividend date, relative to the gross dividend. An event is CONTAMINATED when
something other than the dividend itself is likely to move the price inside that window or to
make the dividend amount unreliable. You decide only that; you do not trade, forecast, or compute.

Rules:
- Use only the documents supplied. Do not rely on anything you believe you know about the
  company, the market, or later events. Every claim must cite a supplied document by its id and
  quote it.
- The decision time is given. Treat any information not in the supplied documents as unknown.
- If the documents say nothing relevant either way, return status UNKNOWN with abstain=true.
  Do not guess CLEAN from silence.
- CLEAN means the documents actively describe an ordinary cash dividend with no other action,
  session anomaly, or amount ambiguity in the window.
- Return the structured object only."""


# ---- inputs ------------------------------------------------------------------------

def decision_time(e: CorporateAction) -> dt.datetime:
    """19:55 ET on the calendar day before the ex-date (weekend/holiday handling is the
    event study's job; the analyst only needs the as-of instant)."""
    d = e.exchange_ex_date - dt.timedelta(days=1)
    return dt.datetime.combine(d, DECISION_TIME, ET)


def _published(src) -> dt.datetime:
    return dt.datetime.strptime(src.published, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))


def _strip(html_text: str) -> str:
    from .calendar import _text_lines
    return "\n".join(_text_lines(html_text))


def reality_rows(e: CorporateAction) -> list[dict]:
    """Saved Reality dividend/stock-info responses for the event's asset, with fetch times.
    The dividends request is keyed by the Reality code (underlying), stock-info by the
    spot symbol; both are matched on the saved request string, never on a name pattern."""
    keys = {"dividends": f"'code': '{e.underlying}'", "stock-info": f"'symbol': '{e.spot_symbol}'"}
    out = []
    for kind, key in keys.items():
        d = REALITY_RAW / kind
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                body = json.loads(p.read_text())
            except ValueError:
                continue
            if key not in str(body.get("request", "")):
                continue
            out.append(dict(id=f"reality_{kind}:{p.name}", fetched_at=body.get("fetched_at"),
                            request=body.get("request"), response=body.get("raw_response")))
    return out


def _ms(v) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000, dt.UTC) if v not in (None, "") else None
    except (TypeError, ValueError, OSError):
        return None


def build_documents(e: CorporateAction, as_of: dt.datetime) -> tuple[list[dict], bool]:
    """Documents available at as_of, and whether that availability is guaranteed.

    Bitget notices carry a printed publication time and are included only if it is at or
    before as_of. The Reality feed has no point-in-time archive: it was fetched after most
    events. Its rows are dated (announcementDate), so rows announced at or before as_of are
    included with that date as their published_at, and the result is flagged as not
    guaranteed because the fetch itself was later. Undated stock-info is included only when
    it was fetched before as_of. Duplicate fetches of the same content are collapsed.
    """
    docs, guaranteed, seen = [], True, set()
    for key, src in SOURCES.items():
        pub = _published(src)
        if pub <= as_of:
            docs.append(dict(id=f"bitget_notice:{key}", published_at=pub.isoformat(), url=src.url,
                             sha256=src.sha256, text=_strip(src.read())))
    for r in reality_rows(e):
        try:
            fetched = dt.datetime.fromisoformat(str(r["fetched_at"]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        kind = r["id"].split(":")[0]
        if kind == "reality_stock-info":
            if fetched > as_of:
                continue
            try:
                text = json.dumps(json.loads(r["response"]).get("data"), separators=(",", ":"))
            except (ValueError, AttributeError):
                continue
            published = fetched
        else:
            try:
                rows = json.loads(r["response"])["data"]["list"] or []
            except (ValueError, KeyError, TypeError):
                continue
            kept = [x for x in rows if (_ms(x.get("announcementDate")) or fetched) <= as_of]
            if not kept:
                continue
            dated = [_ms(x.get("announcementDate")) for x in kept if _ms(x.get("announcementDate"))]
            published = max(dated) if dated else fetched
            if fetched > as_of:
                guaranteed = False
            text = json.dumps(kept, separators=(",", ":"))
        h = hashlib.sha256(text.encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        note = "" if fetched <= as_of else " (content dated at or before as-of; fetched later, no point-in-time archive)"
        docs.append(dict(id=r["id"] + note, published_at=published.isoformat(), text=text[:20000]))
    row = e.model_dump(mode="json")
    trimmed = {k: row.get(k) for k in ("event_id", "symbol", "underlying", "spot_symbol", "event_type", "announcement_date",
                                       "exchange_ex_date", "exchange_record_date", "payment_date", "cash_dividend_per_share",
                                       "adjustment_ratio", "trading_halt_start", "trading_halt_end", "weekend_list_2026_07_17")}
    fetched = dt.datetime.fromisoformat(row["source_fetched_at"]) if row.get("source_fetched_at") else as_of
    if fetched > as_of:
        guaranteed = False
    ann = row.get("announcement_date")
    docs.append(dict(id=f"ledger_row:{e.event_id}", published_at=(f"{ann}T00:00:00+08:00" if ann else fetched.isoformat()),
                     text=json.dumps(trimmed, indent=1)))
    return docs, guaranteed


def user_prompt(e: CorporateAction, as_of: dt.datetime, docs: list[dict]) -> str:
    head = (f"Event: {e.event_id}\nrToken: {e.symbol} (underlying {e.underlying}, spot {e.spot_symbol})\n"
            f"Type: {e.event_type}\nEx-date (exchange): {e.exchange_ex_date}\n"
            f"Cash dividend per share as published by Bitget Reality: {e.cash_dividend_per_share}\n"
            f"Decision time (as-of): {as_of.isoformat()}\n\n"
            f"Documents available at decision time ({len(docs)}):\n")
    parts = [head]
    for d in docs:
        parts.append(f"\n=== document id: {d['id']} | published_at: {d['published_at']} ===\n{d['text']}\n")
    parts.append("\nAnalyse whether the event window is contaminated. Cite only these documents.")
    return "".join(parts)


# ---- call --------------------------------------------------------------------------

def analyse(client: httpx.Client, e: CorporateAction, *, api_key: str, base_url: str,
            model: str, mode: str = "disk", now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.UTC)
    as_of = decision_time(e)
    if mode == "web" and as_of <= now:
        raise ValueError(f"{e.event_id}: web mode is only permitted before the decision time ({as_of.isoformat()})")
    docs, guaranteed = build_documents(e, as_of)
    prompt = user_prompt(e, as_of, docs)
    if mode != "disk":
        raise ValueError("Qwen confounder mode is disk-only; web evidence is not enabled")
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": SYSTEM + " Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    response = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    text = message.get("content")
    record = dict(
        event_id=e.event_id, mode=mode, as_of=as_of.isoformat(), as_of_guaranteed=bool(guaranteed and (mode == "disk" or as_of > now)),
        run_at=now.isoformat(), provider="qwen", model=model, served_by=body.get("model"),
        stop_reason=choice.get("finish_reason"), usage=body.get("usage"),
        system_sha256=hashlib.sha256(SYSTEM.encode()).hexdigest(), prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        documents=[dict(id=d["id"], published_at=d["published_at"], sha256=hashlib.sha256(d["text"].encode()).hexdigest()) for d in docs],
        prompt=prompt, raw_response=body, analysis=None, error=None,
    )
    if not isinstance(text, str):
        record["error"] = "no text content in Qwen response"
        return record
    try:
        record["analysis"] = Analysis.model_validate_json(text).model_dump()
    except ValidationError as exc:
        record["error"] = f"schema: {exc}"
    return record


def save(record: dict) -> Path:
    d = RAW / record["event_id"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['run_at'].replace(':', '').replace('+0000', 'Z')}_{record['mode']}.json"
    p.write_text(json.dumps(record, indent=1, default=str))
    return p


def to_row(record: dict) -> dict:
    a = record.get("analysis") or {}
    return dict(event_id=record["event_id"], mode=record["mode"], as_of=record["as_of"],
                as_of_guaranteed=record["as_of_guaranteed"], model=record["model"], served_by=record.get("served_by"),
                status=a.get("status"), abstain=a.get("abstain"), confidence=a.get("confidence"),
                contaminants="; ".join(f"{c['type']}({c['affects']}): {c['description']}" for c in a.get("contaminants", [])),
                n_evidence=len(a.get("evidence", [])), n_documents=len(record["documents"]),
                rationale=a.get("rationale"), error=record.get("error"),
                input_tokens=(record.get("usage") or {}).get("input_tokens"),
                output_tokens=(record.get("usage") or {}).get("output_tokens"))


def main() -> None:
    import csv
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("BITGET_QWEN_API_KEY") or os.environ.get("QWEN_API_KEY")
    base_url = os.environ.get("QWEN_BASE_URL")
    model = os.environ.get("QWEN_MODEL")
    missing = [name for name, value in (("BITGET_QWEN_API_KEY", api_key), ("QWEN_BASE_URL", base_url), ("QWEN_MODEL", model)) if not value]
    if missing:
        raise SystemExit(f"missing {', '.join(missing)} in .env; refusing to call Qwen")
    ap = argparse.ArgumentParser(description="AI confounder analyst over the documents available at decision time")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl")
    ap.add_argument("--events", nargs="*", help="event ids; default: every cash dividend with a resolved basis")
    ap.add_argument("--mode", choices=("disk",), default="disk")
    ap.add_argument("--output", type=Path, default=RESULTS / "ai_confounders.csv")
    ap.add_argument("--limit", type=int, help="stop after this many events")
    args = ap.parse_args()
    events = [e for e in read_ledger(args.ledger) if e.event_type == "CASH_DIV" and e.cash_dividend_basis == "GROSS"]
    if args.events:
        want = set(args.events)
        events = [e for e in events if e.event_id in want]
        missing = want - {e.event_id for e in events}
        if missing:
            raise SystemExit(f"unknown or unresolved events: {sorted(missing)}")
    if args.limit:
        events = events[:args.limit]
    client = httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
    rows = []
    prior = {}
    if args.output.exists():
        with args.output.open() as f:
            prior = {(r["event_id"], r["mode"]): r for r in csv.DictReader(f)}
    for e in events:
        rec = analyse(client, e, api_key=api_key, base_url=base_url, model=model, mode=args.mode)
        p = save(rec)
        row = to_row(rec)
        prior[(row["event_id"], row["mode"])] = row
        rows.append(row)
        a = rec.get("analysis") or {}
        print(f"{e.event_id:24s} {a.get('status', 'ERROR'):13s} abstain={a.get('abstain')} conf={a.get('confidence')} "
              f"contaminants={len(a.get('contaminants', []))} docs={len(rec['documents'])} -> {p.name}"
              + (f"  ERROR {rec['error']}" if rec.get("error") else ""))
    client.close()
    out = sorted(prior.values(), key=lambda r: (r["event_id"], r["mode"]))
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(to_row(dict(event_id="", mode="", as_of="", as_of_guaranteed="", model="", documents=[])).keys()))
        w.writeheader()
        w.writerows(out)
    print(f"{len(rows)} analysed this run; {len(out)} rows in {args.output}")


if __name__ == "__main__":
    main()
