class ExnightError(Exception):
    """Base class. Every failure in this codebase is loud; nothing degrades silently."""


class BitgetAPIError(ExnightError):
    """Bitget returned a non-success code or an unparseable body."""

    def __init__(self, endpoint: str, code: str, msg: str):
        self.endpoint, self.code, self.msg = endpoint, code, msg
        super().__init__(f"{endpoint}: code={code} msg={msg!r}")


class DataGapError(ExnightError):
    """A price series is missing bars inside a window that the analysis needs."""


class UnverifiedRuleError(ExnightError):
    """A product rule this path depends on has not been verified against Bitget."""
