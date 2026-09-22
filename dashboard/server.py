"""Small dependency-free, read-only EXNIGHT dashboard server.

The server intentionally exposes only derived evidence and never reads `.env`, account
credentials, balances, or order endpoints. It is bound to localhost by default.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import mimetypes
import sys
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

UTC = dt.timezone.utc
DEFAULT_SYMBOLS = ("RAPHUSDT", "RSATAUSDT", "RSTMUSDT")
STATIC_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = STATIC_ROOT.parent
DOWNLOAD_NAMES = {
    "signals_v1.csv": "Frozen forward signals",
    "health_20260922.json": "Latest scheduler health",
    "run_manifest_v1.json": "Strategy run manifest",
    "forward_score_20260922.json": "September 22 forward score",
    "competition_scorecard.json": "Walk-forward scorecard",
    "competition_backtest_manifest.json": "Backtest manifest",
}


def _json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _age_seconds(value: dt.datetime | None, now: dt.datetime) -> float | None:
    return max(0.0, (now - value).total_seconds()) if value else None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _display_age(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def _recorder_paths(data_root: Path) -> list[Path]:
    recorder_root = data_root / "raw" / "recorder"
    if not recorder_root.exists():
        return []
    paths = list(recorder_root.glob("**/*.jsonl"))
    if not paths:
        return []
    by_run: dict[Path, list[Path]] = {}
    for path in paths:
        by_run.setdefault(path.parent, []).append(path)
    latest_run = max(by_run, key=lambda parent: max(path.stat().st_mtime for path in by_run[parent]))
    return sorted(by_run[latest_run])


def recorder_summary(data_root: Path, now: dt.datetime | None = None,
                     expected_symbols: tuple[str, ...] = DEFAULT_SYMBOLS) -> dict[str, Any]:
    """Read recorder JSONL files and derive current cadence/book coverage."""
    now = now or dt.datetime.now(UTC)
    by_symbol: dict[str, list[tuple[dt.datetime, dict[str, Any]]]] = {symbol: [] for symbol in expected_symbols}
    parse_errors = 0
    for path in _recorder_paths(data_root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                timestamp = _timestamp(row.get("ts"))
                symbol = row.get("symbol")
                if timestamp is None or not isinstance(symbol, str):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                parse_errors += 1
                continue
            by_symbol.setdefault(symbol, []).append((timestamp, row))

    symbols: dict[str, Any] = {}
    failures: list[str] = []
    for symbol in sorted(set(expected_symbols) | set(by_symbol)):
        rows = sorted(by_symbol.get(symbol, []), key=lambda item: item[0])
        timestamps = [timestamp for timestamp, _ in rows]
        gaps = [(right - left).total_seconds() for left, right in zip(timestamps, timestamps[1:])]
        latest = timestamps[-1] if timestamps else None
        books = sum(bool((row.get("orderbook") or {}).get("bids") and
                         (row.get("orderbook") or {}).get("asks")) for _, row in rows)
        ticker = sum(bool(row.get("ticker")) for _, row in rows)
        max_gap = max(gaps, default=None)
        age = _age_seconds(latest, now)
        if not rows:
            failures.append(f"{symbol}: no samples")
        if max_gap is not None and max_gap > 180:
            failures.append(f"{symbol}: gap {max_gap:.0f}s")
        if age is None or age > 7200:
            failures.append(f"{symbol}: stale recorder")
        symbols[symbol] = {
            "rows": len(rows), "first_ts": _iso(timestamps[0]) if timestamps else None,
            "last_ts": _iso(latest), "last_age_seconds": age,
            "last_age_display": _display_age(age), "max_gap_seconds": max_gap,
            "nonempty_book_rows": books, "ticker_rows": ticker,
            "book_coverage": (books / len(rows)) if rows else 0.0,
            "series": [
                {"ts": _iso(timestamp),
                 "price": _number((row.get("ticker") or {}).get("lastPrice")),
                 "book": bool((row.get("orderbook") or {}).get("bids") and
                              (row.get("orderbook") or {}).get("asks"))}
                for timestamp, row in rows[-240:]
            ],
        }
    if parse_errors:
        failures.append(f"{parse_errors} malformed recorder rows")
    return {
        "status": "PASS" if not failures else "FAIL", "checked_at": _iso(now),
        "symbols": symbols, "errors": failures,
        "sample_count": sum(item["rows"] for item in symbols.values()),
    }


def _signals(data_root: Path, now: dt.datetime, requested_date: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = data_root / "results" / "signals_v1.csv"
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return [], {"status": "MISSING", "path": "data/results/signals_v1.csv"}
    dates = sorted({row.get("ex_date", "") for row in rows if row.get("ex_date")})
    today = now.date().isoformat()
    upcoming = [value for value in dates if value >= today]
    selected_date = requested_date if requested_date in dates else (upcoming[0] if upcoming else (dates[-1] if dates else None))
    selected = [row for row in rows if row.get("ex_date") == selected_date]
    selected.sort(key=lambda row: (row.get("symbol", ""), int(row.get("notional_usd", 0) or 0)))
    counts = Counter(row.get("verdict", "UNKNOWN") for row in selected)
    events = sorted({row.get("event_id") for row in selected if row.get("event_id")})
    return selected, {
        "status": "PASS", "path": "data/results/signals_v1.csv", "event_date": selected_date,
        "rows": len(selected), "events": len(events), "event_ids": events,
        "verdict_counts": dict(sorted(counts.items())), "all_rows": len(rows),
        "available_dates": dates,
    }


def _signal_row(row: dict[str, Any]) -> dict[str, Any]:
    def numeric(name: str) -> float | None:
        return _number(row.get(name))
    return {
        "event_id": row.get("event_id"), "symbol": row.get("symbol"),
        "spot_symbol": row.get("spot_symbol"), "ex_date": row.get("ex_date"),
        "notional_usd": int(float(row["notional_usd"])) if row.get("notional_usd") else None,
        "verdict": row.get("verdict"), "reason": row.get("reason") or None,
        "buy": row.get("buy") or None, "gross_dividend": numeric("gross_dividend"),
        "net_dividend": numeric("net_dividend"), "price": numeric("price"),
        "cost_per_share": numeric("cost_per_share"), "exit_edge_lower": numeric("exit_edge_lower"),
        "drop_ratio": numeric("drop_ratio"), "basis_tier": numeric("basis_tier"),
        "sell_book_source": row.get("sell_book_source"), "buy_book_source": row.get("buy_book_source"),
    }


def _symbol_aliases(row: dict[str, Any]) -> set[str]:
    """Return the common ways a user may type a Reality token symbol."""
    symbol = "".join(character for character in (row.get("symbol") or "").upper()
                     if character.isalnum())
    spot = "".join(character for character in (row.get("spot_symbol") or "").upper()
                   if character.isalnum())
    aliases = {value for value in (symbol, spot) if value}
    if spot.endswith("USDT"):
        base = spot[:-4]
        aliases.add(base)
        if base.startswith("R") and len(base) > 1:
            aliases.add(base[1:])
    return aliases


def decision_lookup(data_root: Path, query: str,
                    now: dt.datetime | None = None) -> dict[str, Any]:
    """Find the nearest saved decision for a user-supplied token symbol."""
    cleaned = "".join(character for character in query.upper() if character.isalnum())
    if not cleaned:
        return {"status": "INVALID", "query": query, "message": "Enter a token symbol."}
    path = data_root / "results" / "signals_v1.csv"
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return {"status": "UNAVAILABLE", "query": query,
                "message": "Saved decisions are not available."}
    matches = [row for row in rows if cleaned in _symbol_aliases(row)]
    if not matches:
        return {"status": "NOT_EVALUATED", "query": query,
                "message": "This token has no saved Exnight decision."}
    now = now or dt.datetime.now(UTC)
    dates = sorted({row.get("ex_date", "") for row in matches if row.get("ex_date")})
    if not dates:
        return {"status": "NOT_EVALUATED", "query": query,
                "message": "This token has no dated Exnight decision."}
    today = now.date().isoformat()
    upcoming = [value for value in dates if value >= today]
    selected_date = upcoming[0] if upcoming else dates[-1]
    selected = [row for row in matches if row.get("ex_date") == selected_date]
    selected.sort(key=lambda row: int(float(row.get("notional_usd", 0) or 0)))
    return {
        "status": "FOUND", "query": query, "event_date": selected_date,
        "symbol": selected[0].get("symbol"), "spot_symbol": selected[0].get("spot_symbol"),
        "available_dates": dates,
        "rows": [_signal_row(row) for row in selected],
    }


def dashboard_data(project_root: Path = PROJECT_ROOT, now: dt.datetime | None = None,
                   signal_date: str | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(UTC)
    data_root = project_root / "data"
    selected, signal_meta = _signals(data_root, now, requested_date=signal_date)
    manifest = _json(data_root / "results" / "run_manifest_v1.json")
    forward = _json(data_root / "results" / "forward_score_20260922.json")
    health = _json(data_root / "results" / "health_20260922.json")
    competition_scorecard = _json(data_root / "results" / "competition_scorecard.json") or {}
    competition_manifest = _json(data_root / "results" / "competition_backtest_manifest.json") or {}
    recorder = recorder_summary(data_root, now=now)
    event_ids = set(signal_meta.get("event_ids", []))
    manifest_events = set((manifest or {}).get("forward_events_decided", {}))
    provenance = {
        "status": "PASS" if event_ids and event_ids.issubset(manifest_events) else "WARN",
        "manifest_present": manifest is not None,
        "manifest_run_at": (manifest or {}).get("run_at_utc") or (manifest or {}).get("generated_at"),
        "code_commit": (manifest or {}).get("code_commit") or (manifest or {}).get("commit"),
        "signal_events": len(event_ids), "manifest_events": len(manifest_events),
        "missing_events": sorted(event_ids - manifest_events),
    }
    if forward is None:
        score = {"status": "PENDING", "message": "Available after the September 22 observation window closes."}
        observation_message = "Recorder is collecting evidence; forward score is intentionally deferred."
    else:
        score = {"status": forward.get("status", "UNKNOWN"), "message": "Forward score loaded.",
                 "path": "data/results/forward_score_20260922.json", "report": forward}
        observation_message = ("Forward score loaded; recorder remains active for the scheduled "
                              "observation window.")
    downloads = [
        {"name": name, "label": label, "href": f"/download?file={name}"}
        for name, label in DOWNLOAD_NAMES.items() if (data_root / "results" / name).is_file()
    ]
    oos = competition_scorecard.get("oos_concatenated_non_overlapping_folds", {})
    competition = {
        "status": "AVAILABLE" if competition_scorecard else "UNAVAILABLE",
        "name": competition_scorecard.get("name"),
        "sample": competition_scorecard.get("sample", {}),
        "oos": oos,
        "folds": competition_scorecard.get("folds", []),
        "oos_days": competition_manifest.get("oos_calendar_days"),
        "cost_grid_bps": competition_manifest.get("slippage_sensitivity_bps", []),
        "withholding_range": [0, 15, 25, 30],
        "modeled_execution": True,
        "playbook": {
            "status": "LOCAL_VALIDATION_PASSED",
            "kind": "NON_TRADING_SELECTION_BASKET",
            "cloud_status": "AWAITING_MANUAL_SIGN_IN",
            "published": False,
        },
    }
    return {
        "project": "EXNIGHT", "mode": "READ_ONLY", "generated_at": _iso(now),
        "observation": {"status": "ACTIVE", "event_date": signal_meta.get("event_date"),
                         "message": observation_message},
        "recorder": recorder,
        "depth": (health or {}).get("depth", {"status": "UNKNOWN", "message": "No health report yet."}),
        "signals": {"meta": signal_meta, "rows": [_signal_row(row) for row in selected]},
        "provenance": provenance, "forward_score": score, "competition": competition,
        "downloads": downloads,
        "limits": [
            "BUY is suppressed because the Bitget eligibility snapshot time is unpublished.",
            "Current order books are observed-now evidence, not historical event-time fills.",
            "The current September 22 symbols have ticker-only liquidity rather than a two-sided public book.",
            "A mainnet order has not been placed; this dashboard exposes no execution controls.",
        ],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "EXNIGHTDashboard/1.0"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        """Support link preflights without exposing any additional routes."""
        parsed = urlparse(self.path)
        if parsed.path == "/download":
            root = Path(getattr(self.server, "project_root", PROJECT_ROOT))
            name = parse_qs(parsed.query).get("file", [""])[0]
            file_path = root / "data" / "results" / name
            if name not in DOWNLOAD_NAMES or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "evidence file not available")
                return
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", (STATIC_ROOT / "index.html").read_bytes())
        elif path == "/app.js":
            self._send(HTTPStatus.OK, "text/javascript; charset=utf-8", (STATIC_ROOT / "app.js").read_bytes())
        elif path == "/style.css":
            self._send(HTTPStatus.OK, "text/css; charset=utf-8", (STATIC_ROOT / "style.css").read_bytes())
        elif path == "/download":
            root = Path(getattr(self.server, "project_root", PROJECT_ROOT))
            name = parse_qs(parsed.query).get("file", [""])[0]
            if name not in DOWNLOAD_NAMES:
                self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"evidence file not available\n")
                return
            file_path = root / "data" / "results" / name
            try:
                body = file_path.read_bytes()
            except OSError:
                self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"evidence file not available\n")
                return
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/decision":
            root = Path(getattr(self.server, "project_root", PROJECT_ROOT))
            symbol = parse_qs(parsed.query).get("symbol", [""])[0]
            payload = decision_lookup(root / "data", symbol)
            self._send(HTTPStatus.OK, "application/json; charset=utf-8",
                       json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        elif path in ("/api/summary", "/healthz"):
            root = Path(getattr(self.server, "project_root", PROJECT_ROOT))
            requested_date = parse_qs(parsed.query).get("date", [None])[0]
            payload = dashboard_data(root, signal_date=requested_date)
            if path == "/healthz":
                payload = {"status": "ok", "recorder": payload["recorder"]["status"],
                           "generated_at": payload["generated_at"]}
            self._send(HTTPStatus.OK, "application/json; charset=utf-8",
                       json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        else:
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("dashboard: " + (format % args) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only EXNIGHT dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT,
                        help="project root containing data/")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    server.project_root = args.root.resolve()  # type: ignore[attr-defined]
    print(f"EXNIGHT dashboard: http://{args.host}:{args.port}/ (read-only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
