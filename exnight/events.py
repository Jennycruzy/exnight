"""Corporate-action event objects and the ledger they live in."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Label = Literal["DOCUMENTED", "OBSERVED", "ASSUMED"]


class EventType(StrEnum):
    CASH_DIV = "CASH_DIV"
    STOCK_DIV = "STOCK_DIV"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    OTHER = "OTHER"


class CorporateAction(BaseModel):
    """One row of the ledger. Every field is explicit; nothing is defaulted from literature."""

    event_id: str
    symbol: str                      # rMU
    underlying: str                  # MU
    spot_symbol: str | None          # RMUUSDT, resolved from the live symbol list; None if absent
    event_type: EventType
    announcement_date: dt.date | None
    exchange_ex_date: dt.date
    exchange_record_date: dt.date | None
    bitget_snapshot_time: dt.datetime | None
    payment_date: dt.date | None
    gross_dividend_per_share: Decimal | None
    withholding_rate: Decimal | None
    net_dividend_per_share: Decimal | None
    eligibility_verified: bool
    weekend_list_2026_07_17: bool | None     # on Bitget's weekend-trading list published 2026-07-17; not the list at event time
    source_key: str
    source_url: str
    label: Label
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _arithmetic(self):
        if self.event_type is EventType.CASH_DIV:
            if self.gross_dividend_per_share is None or self.withholding_rate is None:
                raise ValueError(f"{self.event_id}: cash dividend without amount or withholding")
            expect = self.gross_dividend_per_share * (1 - self.withholding_rate)
            if self.net_dividend_per_share != expect:
                raise ValueError(f"{self.event_id}: net {self.net_dividend_per_share} != {expect}")
        if self.eligibility_verified and self.bitget_snapshot_time is None:
            raise ValueError(f"{self.event_id}: eligibility marked verified without a snapshot time")
        return self
