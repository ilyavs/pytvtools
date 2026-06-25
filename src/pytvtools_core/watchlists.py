"""Predefined watchlist library — object-oriented, extensible.

All watchlists are frozen ``Watchlist`` instances with a ``name`` and
immutable ``symbols`` tuple.  Use them directly with ``Collector``::

    from pytvtools_core.watchlists import SPDR_SECTORS
    from pytvtools import Collector, CollectorConfig

    config = CollectorConfig(
        symbols=list(SPDR_SECTORS),
        timeframes=["1D", "60"],
        actions=["ohlcv"],
    )
"""

from __future__ import annotations

import dataclasses
from typing import Iterator


@dataclasses.dataclass(frozen=True)
class Watchlist:
    """A named collection of trading symbols.

    Parameters
    ----------
    name : str
        Human-readable label.
    symbols : tuple[str, ...]
        Ticker symbols as bare strings (no exchange prefix).
    """

    name: str
    symbols: tuple[str, ...]

    # -- convenience -------------------------------------------------------

    def __len__(self) -> int:
        return len(self.symbols)

    def __iter__(self) -> Iterator[str]:
        return iter(self.symbols)

    def __getitem__(self, index: int) -> str:
        return self.symbols[index]

    def __contains__(self, symbol: str) -> bool:
        return symbol in self.symbols

    def __repr__(self) -> str:
        return f"Watchlist({self.name!r}, n={len(self.symbols)})"


# ---------------------------------------------------------------------------
# SPDR Select Sector (S&P 500 sectors — market-cap weighted)
# ---------------------------------------------------------------------------

SPDR_SECTORS = Watchlist(
    name="SPDR S&P 500 Select Sectors",
    symbols=(
        "XLK",   # Technology
        "XLC",   # Communication Services
        "XLY",   # Consumer Discretionary
        "XLP",   # Consumer Staples
        "XLE",   # Energy
        "XLF",   # Financials
        "XLV",   # Health Care
        "XLI",   # Industrials
        "XLB",   # Materials
        "XLRE",  # Real Estate
        "XLU",   # Utilities
    ),
)

# ---------------------------------------------------------------------------
# SPDR Industry ETFs (sub-sector / modified equal-weight)
# ---------------------------------------------------------------------------

SPDR_INDUSTRIES = Watchlist(
    name="SPDR Industry ETFs",
    symbols=(
        "XBI",   # Biotech
        "XPH",   # Pharmaceuticals
        "XHS",   # Health Care Services
        "XHE",   # Health Care Equipment
        "XAR",   # Aerospace & Defense
        "XHB",   # Homebuilders
        "XRT",   # Retail
        "XOP",   # Oil & Gas Exploration & Production
        "XES",   # Oil & Gas Equipment & Services
        "XME",   # Metals & Mining
        "XSD",   # Semiconductor
        "XSW",   # Software & Services
        "XTL",   # Telecom
        "XNTK",  # NYSE Technology
        "XITK",  # FactSet Innovative Technology
        "KBE",   # Banking
        "KRE",   # Regional Banking
        "SLX",   # Steel
        "XWEB",  # Internet
    ),
)

# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

SPDR_ALL = Watchlist(
    name="All SPDR Sector & Industry ETFs",
    symbols=SPDR_SECTORS.symbols + SPDR_INDUSTRIES.symbols,
)
