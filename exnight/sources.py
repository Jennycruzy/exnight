"""Registry of first-party Bitget sources saved under data/sources/.

Each entry is a page we fetched and kept verbatim so that every figure in the ledger can be
traced to bytes on disk, and so the ledger regenerates offline. The sha256 is checked at
load time; a mismatch is an error, not a warning.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

SOURCES_DIR = Path(__file__).resolve().parent.parent / "data" / "sources"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    filename: str
    published: str  # date on the page, as printed
    sha256: str
    note: str

    @property
    def path(self) -> Path:
        return SOURCES_DIR / self.filename

    def read(self) -> str:
        raw = self.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != self.sha256:
            raise RuntimeError(
                f"source {self.key} changed on disk: sha256 {digest} != registered {self.sha256}"
            )
        return raw.decode("utf-8")


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            key="dividends_2026_07_24",
            url="https://www.bitget.com/support/articles/12560603890079",
            filename="bitget_support_12560603890079_dividends_2026-07-24.html",
            published="2026-07-24 01:42",
            sha256="801866c5b0ce01e3a44701798c57eda22e12afa438e6dc83bad80c3d71d756d2",
            note="Dividend Distribution Completed for 63 Stocks Including rMU, rQQQ, and rTSM. "
                 "Table of ticker, ex-dividend date, payment date, dividend per share; 30% withholding.",
        ),
        Source(
            key="weekend_trading_2026_07_17",
            url="https://www.bitget.com/support/articles/12560603889487",
            filename="bitget_support_12560603889487_247_tokens_2026-07-17.html",
            published="2026-07-17 03:40",
            sha256="7580e7402939289b39aacc3b5466c3d6360b4e3fe09a910fb9d65dfeccfa3542",
            note="61 rTokens with weekend (24/7) trading; weekend session open times; "
                 "weekend prices are market-maker reference quotes anchored to Friday close.",
        ),
        Source(
            key="perp_dividend_2026_09_16",
            url="https://www.bitget.com/support/articles/12560603895292",
            filename="bitget_support_12560603895292_perp_dividend_VST_AVGO_2026-09-16.html",
            published="2026-09-16 00:00",
            sha256="fc111121ffee195b9200b7716de9cf75fea0dc4f49e264210172c2d246db21e6",
            note="Cash dividend settlement for VSTUSDT and AVGOUSDT stock perps: dividend per share "
                 "(USD) 0.23 / 0.65, ex-dividend date (ET) 2026-09-21, settlement 2026-09-19 08:00 UTC+8. "
                 "States no tax treatment; amounts 'subject to the official data published on the ex-dividend date'.",
        ),
        Source(
            key="rtoken_faq_2026_06_23",
            url="https://www.bitget.com/support/articles/12560603887176",
            filename="bitget_support_12560603887176_rtoken_faq_2026-06-23.html",
            published="2026-06-23 07:39",
            sha256="34adf88e4f907ff1a47db0c7d8bef4ebf4570763bfc3b6793ea34104014d2be3",
            note="rToken FAQ. Q: 'Does Reality eliminate the 30% U.S. dividend tax?' A: withholding is not "
                 "universally eliminated; if it applies it is deducted before the net dividend is credited; "
                 "the rate depends on product structure, parties, treaties and the user's circumstances.",
        ),
    ]
}
