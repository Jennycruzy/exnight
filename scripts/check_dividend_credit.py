"""Watch the live rTOWN position for its dividend credit, read-only, and record it once.

Run from cron after Bitget's listed payment time (8 Oct 2026 16:00 UTC):

    */15 16-23 8 10 * cd /path/to/exnight && .venv/bin/python scripts/check_dividend_credit.py \
        >> data/raw/paper/dividend_check.log 2>&1

Each run takes a read-only Agent Hub snapshot (holdings, spot and other ledgers, quote) with the
BITGET_READ_* key. Until a credit appears it only logs "not yet" and saves nothing. When one
appears (a ledger row other than the original buy, or a USDT balance above the post-buy
balance) it saves the snapshot with the account UID redacted, rebuilds reports/, commits as
jennycruzy and pushes. After that, later runs exit immediately.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import score_due_v3  # noqa: E402  (identity, push helpers)

PAPER = ROOT / "data" / "raw" / "paper"
SYMBOL, BASE = "RTOWNUSDT", "rTOWN"
BUY_TS = "1790187950042"                 # the 23 Sep fill, in both ledgers
USDT_AFTER_BUY = Decimal("2.89206496")
BUY_TYPES = {"ORDER_DEALT_IN", "ORDER_DEALT_FROZEN_OUT"}
START = str(int(dt.datetime(2026, 9, 23, tzinfo=dt.UTC).timestamp() * 1000))


def _env() -> tuple[dict, list[str]]:
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"'))
    secrets = [env["BITGET_READ_API_KEY"], env["BITGET_READ_SECRET_KEY"], env["BITGET_READ_PASSPHRASE"]]
    env.update(BITGET_API_KEY=secrets[0], BITGET_SECRET_KEY=secrets[1], BITGET_PASSPHRASE=secrets[2])
    binary = env.get("AGENT_HUB_BIN") or str(Path.home() / ".nvm/versions/node/v24.21.0/bin/bgc")
    env["AGENT_HUB_BIN"] = binary
    env["PATH"] = os.path.dirname(binary) + os.pathsep + env.get("PATH", "")
    return env, secrets


def snapshot() -> dict[str, str]:
    """Read-only calls only; returns {file name: redacted response text}."""
    env, secrets = _env()
    calls = {
        "01_account_rTOWN.json": ["account_overview", "--coin", BASE, "--view", "full"],
        "02_account_USDT.json": ["account_overview", "--coin", "USDT", "--view", "full"],
        "03_ledger_USDT.json": ["funds_records", "--action", "financial", "--category", "SPOT", "--coin", "USDT",
                                "--startTime", START, "--view", "full"],
        "04_ledger_rTOWN.json": ["funds_records", "--action", "financial", "--category", "SPOT", "--coin", BASE,
                                 "--startTime", START, "--view", "full"],
        "05_ticker.json": ["market", "--action", "tickers", "--category", "SPOT", "--symbol", SYMBOL],
        "06_ledger_other_USDT.json": ["funds_records", "--action", "financial", "--category", "OTHER", "--coin", "USDT",
                                      "--startTime", START, "--view", "full"],
    }
    out = {}
    for name, args in calls.items():
        run = subprocess.run([env["AGENT_HUB_BIN"], *args], env=env, capture_output=True, text=True, timeout=60)
        text = (run.stdout or run.stderr).strip()
        for secret in secrets:
            text = text.replace(secret, "[redacted]")
        text = re.sub(r'"uid":"\d+"', '"uid":"[redacted]"', text)
        if run.returncode != 0:
            raise RuntimeError(f"{name}: {text[-300:]}")
        out[name] = text + "\n"
    return out


def credit_rows(files: dict[str, str]) -> list[dict]:
    rows = []
    for name in ("03_ledger_USDT.json", "04_ledger_rTOWN.json", "06_ledger_other_USDT.json"):
        for row in json.loads(files[name])["data"].get("list") or []:
            # Only entries after the buy: the 23 Sep deposit that funded it is not a credit.
            if row.get("type") not in BUY_TYPES and int(row.get("ts", 0)) > int(BUY_TS):
                rows.append(row)
    return rows


def usdt_available(files: dict[str, str]) -> Decimal:
    assets = json.loads(files["02_account_USDT.json"])["data"]["assets"]["data"]["assets"]
    return Decimal(next(a["available"] for a in assets if a["coin"] == "USDT"))


def already_recorded() -> bool:
    for folder in PAPER.glob("*_rTOWN_position"):
        marker = folder / "07_credit.json"
        if marker.is_file() and score_due_v3._tracked(marker.relative_to(ROOT).as_posix()):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Record the rTOWN dividend credit once it lands (read-only)")
    ap.add_argument("--dry-run", action="store_true", help="snapshot and report; save and commit nothing")
    args = ap.parse_args()
    now = dt.datetime.now(dt.UTC)
    if already_recorded():
        return 0
    files = snapshot()
    rows, usdt = credit_rows(files), usdt_available(files)
    if not rows and usdt <= USDT_AFTER_BUY:
        print(f"{now.isoformat()} not yet: ledger has only the buy, USDT {usdt}")
        return 0
    usdt_rows = [Decimal(r["amount"]) for r in rows if r.get("coin") == "USDT" and Decimal(r.get("amount", "0")) > 0]
    credit = {"detected_at": now.isoformat(), "ledger_rows": rows, "usdt_available": str(usdt),
              "usdt_change_since_buy": str(usdt - USDT_AFTER_BUY),
              "credited_usdt": str(sum(usdt_rows) if usdt_rows else usdt - USDT_AFTER_BUY)}
    if args.dry_run:
        print(f"{now.isoformat()} CREDIT SEEN (dry run): {json.dumps(credit)}")
        return 0
    if (score_due_v3._git("config", "user.name").stdout.strip(),
            score_due_v3._git("config", "user.email").stdout.strip()) != (score_due_v3.NAME, score_due_v3.EMAIL):
        print("refusing to commit: repository identity is not jennycruzy", file=sys.stderr)
        return 1
    folder = PAPER / f"{now.strftime('%Y%m%dT%H%M%SZ')}_rTOWN_position"
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text)
    (folder / "07_credit.json").write_text(json.dumps(credit, indent=1) + "\n")
    build = subprocess.run([sys.executable, "-m", "exnight.backtest_report"], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
    if build.returncode:
        print(f"{now.isoformat()} credit saved but reports/ not rebuilt: {build.stderr.strip()[-400:]}")
    rel = folder.relative_to(ROOT).as_posix()
    score_due_v3._git("add", "--", rel, "reports")
    commit = score_due_v3._git("commit", "--only", "-q", "-m", "Record the rTOWN dividend credit on the live position",
                               "--", rel, "reports")
    if commit.returncode:
        print(f"{now.isoformat()} commit failed: {commit.stderr.strip()}")
        return 1
    print(f"{now.isoformat()} credit recorded; committed {score_due_v3._git('rev-parse', '--short', 'HEAD').stdout.strip()}")
    env = score_due_v3._push_env()
    publish = subprocess.run(["bash", str(ROOT / "scripts" / "publish_pages.sh")], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=600)
    print(publish.stdout.strip() or publish.stderr.strip()[-400:])
    print(score_due_v3._push("main", env))
    print(score_due_v3._push("gh-pages", env))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
