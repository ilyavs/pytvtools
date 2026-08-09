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
import json
import urllib.error
import urllib.request
from typing import Iterator

_SCANNER_URL = "https://scanner.tradingview.com/{market}/scan"
_PAGE_SIZE = 100


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

# ---------------------------------------------------------------------------
# S&P 500 constituents (lazy-loaded from Wikipedia)
# ---------------------------------------------------------------------------

_SP500_CACHE: Watchlist | None = None


def get_sp500(*, force_refetch: bool = False) -> Watchlist:
    """Return the current S&P 500 constituents.

    Fetches from Wikipedia on first call (or when ``force_refetch=True``).
    Falls back to a static snapshot if the HTTP request fails.

    Result is cached in memory for the lifetime of the process.
    """
    global _SP500_CACHE
    if _SP500_CACHE is not None and not force_refetch:
        return _SP500_CACHE

    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        symbols = tuple(str(s).replace(".", "-") for s in df["Symbol"].tolist())
        _SP500_CACHE = Watchlist(name="S&P 500", symbols=symbols)
    except Exception:
        _SP500_CACHE = _SP500_STATIC

    return _SP500_CACHE


_SP500_TICKERS = (
    "A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM",
    "ADP", "ADSK", "AEE", "AEP", "AES", "AFG", "AFL", "AGCO", "AGR", "AIG",
    "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD",
    "AME", "AMGN", "AMH", "AMP", "AMT", "AMZN", "ANET", "ANSS", "AON", "AOS",
    "APA", "APD", "APO", "APP", "APTV", "ARE", "ATO", "ATUS", "AVB", "AVGO",
    "AVY", "AWK", "AXON", "AXP", "AZO", "AZPN", "BA", "BAC", "BALL", "BAX",
    "BBY", "BDX", "BEKE", "BEN", "BF_B", "BG", "BIIB", "BIO", "BK", "BKNG",
    "BKR", "BLK", "BLL", "BMY", "BR", "BRK_B", "BRO", "BSX", "BWA", "BXP",
    "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCL", "CDNS",
    "CDW", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CINF",
    "CL", "CLX", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF",
    "COIN", "COO", "COP", "COR", "COST", "COTY", "CPB", "CPRT", "CPT", "CRL",
    "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTLT", "CTRA", "CTSH", "CTVA",
    "CVS", "CVX", "CZR", "D", "DAL", "DAY", "DD", "DE", "DECK", "DELL",
    "DFS", "DG", "DGX", "DHI", "DHR", "DIS", "DISCA", "DISH", "DLR", "DLTR",
    "DOV", "DOW", "DPZ", "DRI", "DRVN", "DVA", "DVN", "DXCM", "EA", "EBAY",
    "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELS", "EMN", "EMR", "ENPH",
    "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS", "ETN", "ETR",
    "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXR", "F", "FANG", "FAST", "FCX",
    "FDS", "FDX", "FE", "FFIV", "FI", "FICO", "FIS", "FITB", "FMC", "FOX",
    "FOXA", "FRT", "FSLR", "FTNT", "FTV", "GD", "GE", "GEHC", "GEN", "GILD",
    "GIS", "GL", "GLW", "GM", "GNRC", "GOLD", "GOOG", "GOOGL", "GPC", "GPN",
    "GPS", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HES",
    "HIG", "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC", "HST",
    "HSY", "HUBB", "HUM", "HWM", "IBM", "ICE", "IDXX", "IEX", "IFF", "ILMN",
    "INCY", "INTC", "INTU", "INVH", "IOT", "IP", "IPG", "IQV", "IR", "IRM",
    "ISRG", "IT", "ITW", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ",
    "JNPR", "JPM", "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR", "KLAC",
    "KMB", "KMI", "KMX", "KO", "KR", "L", "LDOS", "LEN", "LH", "LHX",
    "LIN", "LKQ", "LLY", "LMT", "LNT", "LOW", "LPLA", "LRCX", "LSXMA", "LSXMK",
    "LULU", "LUV", "LVS", "LW", "LYB", "LYV", "M", "MA", "MAA", "MANH",
    "MAR", "MAS", "MASI", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET",
    "META", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST", "MO",
    "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRO", "MS", "MSCI", "MSFT",
    "MSI", "MSTR", "MTB", "MTCH", "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE",
    "NEM", "NET", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP",
    "NTRS", "NUE", "NVDA", "NVR", "NWS", "NWSA", "NXPI", "O", "ODFL", "OKE",
    "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PANW", "PARA", "PAYC", "PAYX",
    "PCAR", "PCG", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM",
    "PKG", "PLD", "PLTR", "PM", "PNC", "PNR", "PNW", "PODD", "POOL", "PPG",
    "PPL", "PRU", "PSA", "PSX", "PTC", "PWR", "PYPL", "QCOM", "QRVO", "RCL",
    "REGN", "RF", "RJF", "RL", "RMD", "ROK", "ROKU", "ROL", "ROP", "ROST",
    "RS", "RSG", "RTX", "RVTY", "S", "SBAC", "SBUX", "SCHW", "SCI", "SHW",
    "SIRI", "SJM", "SLB", "SLG", "SMCI", "SNA", "SNOW", "SNPS", "SO", "SOLV",
    "SPG", "SPGI", "SQ", "SRE", "STE", "STLD", "STT", "STX", "STZ", "SWK",
    "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG", "TDY", "TECH", "TEL",
    "TER", "TFC", "TFX", "TGT", "TJX", "TMO", "TMUS", "TPR", "TRGP", "TRMB",
    "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT", "TTD", "TTWO", "TXN", "TXT",
    "TYL", "UAL", "UBER", "UDR", "UHS", "ULTA", "UNH", "UNM", "UNP", "UPS",
    "URI", "USB", "V", "VICI", "VLO", "VLTO", "VMC", "VRSK", "VRSN", "VRT",
    "VRTX", "VST", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA", "WBD", "WDAY",
    "WDC", "WEC", "WELL", "WFC", "WHR", "WM", "WMB", "WMT", "WRB", "WRK",
    "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL", "YUM", "ZBH",
    "ZBRA", "ZION", "ZTS",
)

_SP500_STATIC = Watchlist(
    name="S&P 500 (static snapshot)",
    symbols=_SP500_TICKERS,
)

# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------

CRYPTO = Watchlist(
    name="Top Crypto",
    symbols=(
        "BITSTAMP:BTCUSD",
        "BITSTAMP:ETHUSD",
    ),
)

# ---------------------------------------------------------------------------
# Metals & Miners
# ---------------------------------------------------------------------------

METALS_MINERS = Watchlist(
    name="Metals & Miners",
    symbols=(
        # Precious spot
        "OANDA:XAUUSD", "TVC:GOLD", "OANDA:XAGUSD", "TVC:SILVER",
        "OANDA:XPTUSD", "TVC:PLATINUM", "OANDA:XPDUSD", "TVC:PALLADIUM",
        "OANDA:XCUUSD", "CAPITALCOM:COPPER",
        # Gold miners ETF
        "AMEX:GDX", "AMEX:GDXJ",
        # Silver miners ETF
        "AMEX:SIL", "AMEX:SILJ",
        # Gold ETFs
        "AMEX:GLD", "AMEX:IAU",
        # Platinum/Palladium
        "AMEX:PPLT", "AMEX:PALL", "AMEX:PLG",
        # Copper
        "AMEX:COPX", "AMEX:CPER", "LSE:COPA",
        # Individual miners
        "NEM", "FCX", "SCCO", "AA", "RIO", "BHP", "HBM", "TECK", "VALE",
    ),
)

# ---------------------------------------------------------------------------
# Index Futures
# ---------------------------------------------------------------------------

INDEX_FUTURES = Watchlist(
    name="Index Futures",
    symbols=(
        "CME_MINI:ES1!",
        "CME_MINI:NQ1!",
        "CBOT_MINI:YM1!",
        "CME_MINI:RTY1!",
        "EUREX:FDAX1!",
        "EUREX:FESX1!",
    ),
)

# ---------------------------------------------------------------------------
# Index CFDs
# ---------------------------------------------------------------------------

INDEX_CFDS = Watchlist(
    name="Index CFDs",
    symbols=(
        "SPCFD:SPX",
        "TVC:NDQ",
        "TVC:DJI",
        "TVC:RUT",
        "TVC:DAX",
        "TVC:UKX",
        "EURONEXT:PX1",
        "TVC:NI225",
        "TVC:HSI",
        "TVC:VIX",
    ),
)

# ---------------------------------------------------------------------------
# Index ETFs
# ---------------------------------------------------------------------------

INDEX_ETFS = Watchlist(
    name="Index ETFs",
    symbols=(
        "AMEX:SPY",
        "NASDAQ:QQQ",
        "AMEX:IWM",
        "AMEX:DIA",
        "AMEX:VTI",
        "CBOE:MAGS",
    ),
)

# ---------------------------------------------------------------------------
# Bonds
# ---------------------------------------------------------------------------

BONDS = Watchlist(
    name="Bonds",
    symbols=(
        "TVC:US10Y",
        "TVC:US02Y",
        "TVC:US03M",
        "TVC:TNX",
        "CBOT:TN1!",
        "CBOT:ZT1!",
        "NASDAQ:TLT",
    ),
)

# ---------------------------------------------------------------------------
# Oil
# ---------------------------------------------------------------------------

OIL = Watchlist(
    name="Oil",
    symbols=(
        "TVC:USOIL",
        "TVC:UKOIL",
        "NYMEX:CL1!",
        "OANDA:WTICOUSD",
        "OANDA:BCOUSD",
    ),
)

# ---------------------------------------------------------------------------
# Uranium & Strategic Commodities
# ---------------------------------------------------------------------------

URANIUM_STRATEGIC = Watchlist(
    name="Uranium & Strategic Commodities",
    symbols=(
        "AMEX:URA",
        "AMEX:URNM",
        "AMEX:UEC",
        "NASDAQ:NNE",
        "NASDAQ:USAR",
        "NASDAQ:AREC",
        "NASDAQ:CRML",
        "NYSE:AMR",
        "CCJ",
        "DNN",
        "NXE",
        "GLO",
        "EU",
        "URG",
        "AMEX:REMX",
        "NYSE:MP",
        "NASDAQ:NB",
        "NASDAQ:NIKL",
        "LYC",
        "AMEX:SLX",
        "OTC:AMLIF",
        "NASDAQ:CENX",
    ),
)

# ---------------------------------------------------------------------------
# Registry — map name → Watchlist for job lookup
# ---------------------------------------------------------------------------

WATCHLISTS: dict[str, Watchlist] = {
    "SPDR_SECTORS": SPDR_SECTORS,
    "SPDR_INDUSTRIES": SPDR_INDUSTRIES,
    "SPDR_ALL": SPDR_ALL,
    "CRYPTO": CRYPTO,
    "METALS_MINERS": METALS_MINERS,
    "INDEX_FUTURES": INDEX_FUTURES,
    "INDEX_CFDS": INDEX_CFDS,
    "INDEX_ETFS": INDEX_ETFS,
    "BONDS": BONDS,
    "OIL": OIL,
    "URANIUM_STRATEGIC": URANIUM_STRATEGIC,
}

PINK_LIST_WATCHLISTS: dict[str, Watchlist] = {
    "METALS_MINERS": METALS_MINERS,
    "INDEX_FUTURES": INDEX_FUTURES,
    "INDEX_CFDS": INDEX_CFDS,
    "INDEX_ETFS": INDEX_ETFS,
    "BONDS": BONDS,
    "OIL": OIL,
    "URANIUM_STRATEGIC": URANIUM_STRATEGIC,
}

def get_watchlist(name: str) -> Watchlist:
    """Look up a watchlist by name constant."""
    if name not in WATCHLISTS:
        raise KeyError(f"Unknown watchlist: {name}. Choices: {', '.join(sorted(WATCHLISTS))}")
    return WATCHLISTS[name]


def registry_rows(sp500: Watchlist | None = None) -> list[dict[str, str]]:
    """Build one (symbol, watchlist, source) entry per symbol per watchlist.

    Static ``WATCHLISTS`` entries get ``source="watchlist"``; the S&P 500 gets
    ``source="sp500"`` with ``watchlist="SP500"``.  Pass ``sp500`` explicitly
    to avoid the network/pandas load of ``get_sp500()`` (used in Databricks).
    """
    wl = sp500 if sp500 is not None else get_sp500()
    rows: list[dict[str, str]] = []
    for name, watch in WATCHLISTS.items():
        for sym in watch.symbols:
            rows.append({"symbol": sym, "watchlist": name, "source": "watchlist"})
    for sym in wl.symbols:
        rows.append({"symbol": sym, "watchlist": "SP500", "source": "sp500"})
    return rows


def screen(
    market: str = "america",
    exchange: str | None = None,
    types: tuple[str, ...] = ("stock",),
    columns: tuple[str, ...] = ("name",),
    page_size: int = _PAGE_SIZE,
    timeout: float = 30.0,
    sort_by: str | None = "name",
) -> tuple[list[dict[str, object]], int]:
    """Query TradingView's stock-screener endpoint.

    Returns ``(rows, total_count)`` where each row is a dict, e.g.
    ``{"symbol": "NYSE:A", "name": "A", "close": 145.97}``.  Paginates
    internally through the full result set.  A stable sort (default
    ``"name"``) is required for correct pagination — TradingView's default
    order is unstable across page requests, which causes duplicate/missing
    symbols.  ``sort_by=None`` disables the sort only for callers who
    know the server returns a stable order.

    Parameters
    ----------
    market : str
        Scanner market, e.g. ``"america"``, ``"crypto"``, ``"forex"``.
    exchange : str | None
        If given, only return symbols from this exchange (e.g. ``"NYSE"``,
        ``"NASDAQ"``, ``"AMEX"``).  None returns every market symbol.
    types : tuple[str, ...]
        Instrument types to include, e.g. ``("stock",)``.
    columns : tuple[str, ...]
        Screen columns to fetch per row, e.g. ``("name", "close")``.  The
        symbol itself is always present as the ``"symbol"`` key.
    timeout : float
        Seconds to wait for the server response.
    sort_by : str | None
        Column to sort results by (default ``"name"``, ascending) — required
        for correct pagination.  ``None`` omits the sort entirely.
    """
    rows: list[dict[str, object]] = []
    total: int | None = None
    offset = 0
    while True:
        payload: dict[str, object] = {
            "symbols": {"query": {"types": list(types)}},
            "columns": list(columns),
        }
        if sort_by:
            payload["sort"] = {"sortBy": sort_by, "sortOrder": "asc"}
        payload["range"] = [offset, offset + page_size]
        if exchange:
            payload["filter"] = [
                {"left": "exchange", "operation": "equal", "right": exchange}
            ]

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            _SCANNER_URL.format(market=market),
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 "
                "Safari/537.36",
                "Referer": "https://www.tradingview.com/screener/",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            reason = f": {err.reason}" if err.reason else ""
            raise RuntimeError(
                f"screen({market!r}) failed: HTTP {err.code}{reason}"
            ) from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"screen({market!r}) failed: {err.reason}") from err

        total = int(data["totalCount"])
        batch = data.get("data", [])
        for item in batch:
            row: dict[str, object] = {"symbol": item["s"]}
            row.update(zip(columns, item.get("d", [])))
            rows.append(row)
        if not batch or offset + page_size >= total:
            break
        offset += page_size
    return rows, total


US_STOCK_EXCHANGES: tuple[str, ...] = ("NYSE", "NASDAQ", "AMEX")

_US_STOCKS_CACHE: Watchlist | None = None


def us_stock_rows(
    market: str = "america",
    exchanges: tuple[str, ...] = US_STOCK_EXCHANGES,
) -> list[dict[str, str]]:
    """One (symbol, US_STOCKS, screen) entry per listed US stock.

    Queries the TradingView scanner per exchange and unions the results.
    Symbols are already exchange-prefixed (``NYSE:A``), matching the
    format the cache/refresh path consumes.
    """
    rows: list[dict[str, str]] = []
    for exch in exchanges:
        screen_rows, _ = screen(market=market, exchange=exch)
        for r in screen_rows:
            rows.append({
                "symbol": str(r["symbol"]),
                "watchlist": "US_STOCKS",
                "source": "screen",
            })
    return rows


def get_us_stocks(*, force_refetch: bool = False) -> Watchlist:
    """Return a Watchlist of all listed US stocks (mirrors get_sp500).

    Cached in memory for process lifetime.  Raises on failure — unlike
    S&P 500 there is no static fallback snapshot for the whole market.
    """
    global _US_STOCKS_CACHE
    if _US_STOCKS_CACHE is not None and not force_refetch:
        return _US_STOCKS_CACHE
    symbols = tuple(r["symbol"] for r in us_stock_rows())
    _US_STOCKS_CACHE = Watchlist(name="US Stocks", symbols=symbols)
    return _US_STOCKS_CACHE
