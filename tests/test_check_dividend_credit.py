import json
import shutil
import sys
from pathlib import Path

from exnight import backtest_report

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_dividend_credit as checker  # noqa: E402

SNAPSHOT = sorted((backtest_report.ROOT / "data" / "raw" / "paper").glob("*_rTOWN_position"))[0]


def _files(extra_rows=()):
    files = {p.name: p.read_text() for p in SNAPSHOT.glob("0*.json")}
    other = {"data": {"list": [
        {"coin": "USDT", "type": "TRANSFER_IN", "amount": "7", "ts": "1790187561079"},  # the deposit before the buy
        *extra_rows]}}
    files["06_ledger_other_USDT.json"] = json.dumps(other)
    return files


def test_deposit_before_the_buy_is_not_a_credit():
    assert checker.credit_rows(_files()) == []


def test_a_later_credit_is_found():
    row = {"coin": "USDT", "type": "DIVIDEND", "amount": "0.0545", "ts": "1791500000000"}
    assert checker.credit_rows(_files([row])) == [row]


def test_report_shows_the_credit_and_the_withholding(tmp_path):
    folder = tmp_path / "20261008T161500Z_rTOWN_position"
    shutil.copytree(SNAPSHOT, folder)
    (folder / "07_credit.json").write_text(json.dumps({
        "detected_at": "2026-10-08T16:15:00+00:00", "usdt_change_since_buy": "0.0545", "credited_usdt": "0.0545",
        "ledger_rows": [{"coin": "USDT", "type": "DIVIDEND", "amount": "0.0545"}]}))
    pos = backtest_report.position_check(backtest_report.live_order(), paper=tmp_path)
    assert pos["dividend_credited"] and abs(pos["implied_withholding"] - (1 - 0.0545 / (0.2783 * 0.28))) < 1e-9
    lines = "\n".join(backtest_report._position_lines(pos))
    assert "0.054500 USDT" in lines and "30.1%" in lines and "not yet" not in lines
