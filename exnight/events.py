"""Corporate-action event objects and the ledger they live in."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Label = Literal["DOCUMENTED", "OBSERVED", "ASSUMED"]
CashDividendBasis = Literal["GROSS", "NET", "UNRESOLVED"]
EventStatus = Literal["pending", "ongoing", "completed", "paid", "unknown"]


class EventType(StrEnum):
    CASH_DIV = "CASH_DIV"
    STOCK_DIV = "STOCK_DIV"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    OTHER = "OTHER"


class CorporateAction(BaseModel):
    """One ledger row with source values and unresolved states represented explicitly."""

    event_id: str
    symbol: str                      # API-returned Reality baseCoin identifier
    underlying: str                  # API-returned Reality code
    spot_symbol: str | None          # API-returned spot symbol, if listed
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
    weekend_list_2026_07_17: bool | None
    source_key: str
    source_url: str
    label: Label
    notes: list[str] = Field(default_factory=list)

    # Fields returned by the live corporate-action APIs. Defaults keep old saved rows
    # readable while a rebuild fills the fields for newly fetched events.
    ex_date_timezone: str = "UNVERIFIED"
    cash_dividend_per_share: Decimal | None = None
    cash_dividend_basis: CashDividendBasis = "UNRESOLVED"
    cash_dividend_timestamp: dt.datetime | None = None
    adjustment_ratio: Decimal | None = None
    trading_halt_start: dt.datetime | None = None
    trading_halt_end: dt.datetime | None = None
    status: EventStatus = "unknown"
    source_endpoint: str | None = None
    source_fetched_at: dt.datetime | None = None

    @property
    def ex_dividend_date(self) -> dt.date:
        """Spec-facing name for the existing exchange ex-date field."""
        return self.exchange_ex_date

    @model_validator(mode="after")
    def _validate_fields(self):
        for name in ("cash_dividend_per_share", "gross_dividend_per_share",
                     "net_dividend_per_share", "withholding_rate", "adjustment_ratio"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError(f"{self.event_id}: {name} must be finite and non-negative")
        if self.withholding_rate is not None and self.withholding_rate > 1:
            raise ValueError(f"{self.event_id}: withholding_rate must be between 0 and 1")
        if self.event_type is EventType.CASH_DIV:
            # Migrate the original notice schema without inventing an amount.
            if self.cash_dividend_per_share is None and self.gross_dividend_per_share is not None:
                self.cash_dividend_per_share = self.gross_dividend_per_share
            if self.cash_dividend_basis == "UNRESOLVED" and self.gross_dividend_per_share is not None:
                self.cash_dividend_basis = "GROSS"
            if self.cash_dividend_per_share is None:
                raise ValueError(f"{self.event_id}: cash dividend without source amount")
            if self.cash_dividend_basis == "GROSS":
                if self.gross_dividend_per_share is None or self.withholding_rate is None:
                    raise ValueError(f"{self.event_id}: gross cash dividend without withholding")
                if self.cash_dividend_per_share != self.gross_dividend_per_share:
                    raise ValueError(f"{self.event_id}: source amount does not match gross amount")
                expect = self.gross_dividend_per_share * (1 - self.withholding_rate)
                if self.net_dividend_per_share != expect:
                    raise ValueError(f"{self.event_id}: net {self.net_dividend_per_share} != {expect}")
            elif self.cash_dividend_basis == "NET":
                if self.net_dividend_per_share is None:
                    self.net_dividend_per_share = self.cash_dividend_per_share
                elif self.net_dividend_per_share != self.cash_dividend_per_share:
                    raise ValueError(f"{self.event_id}: source amount does not match net amount")
        if self.event_type in (EventType.SPLIT, EventType.REVERSE_SPLIT):
            if self.adjustment_ratio is None or not self.adjustment_ratio.is_finite() or self.adjustment_ratio <= 0:
                raise ValueError(f"{self.event_id}: split requires a positive adjustment ratio")
            if self.event_type is EventType.SPLIT and self.adjustment_ratio <= 1:
                raise ValueError(f"{self.event_id}: split ratio must be greater than one")
            if self.event_type is EventType.REVERSE_SPLIT and self.adjustment_ratio >= 1:
                raise ValueError(f"{self.event_id}: reverse split ratio must be less than one")
        for name in ("bitget_snapshot_time", "cash_dividend_timestamp", "trading_halt_start",
                     "trading_halt_end", "source_fetched_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{self.event_id}: {name} must be timezone-aware")
        if self.trading_halt_start is not None and self.trading_halt_end is not None:
            if self.trading_halt_start >= self.trading_halt_end:
                raise ValueError(f"{self.event_id}: trading halt end must follow start")
        elif self.trading_halt_start is not None or self.trading_halt_end is not None:
            raise ValueError(f"{self.event_id}: both trading halt timestamps are required")
        if self.eligibility_verified and self.bitget_snapshot_time is None:
            raise ValueError(f"{self.event_id}: eligibility marked verified without a snapshot time")
        return self
