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
