"""Absorption ratio (Kritzman, Li, Page & Rigobon 2010) — systemic risk measure.

AR = share of total return variance absorbed by the top principal components
of a universe's covariance matrix. High AR = markets tightly coupled = fragile.

References
----------
- frds.io: default fraction_eigenvectors = 0.2
- portfoliooptimizer.io: recommends retaining 1 eigenvector for simplicity
"""
from __future__ import annotations

from typing import Any


def _n_keep(n_eigenvectors: int | float, n_assets: int) -> int:
    """Resolve eigenvectors-to-keep to an exact count in ``[1, n_assets]``.

    int = exact count; float <1 = fraction of assets (frds 0.2 convention).
    """
    if isinstance(n_eigenvectors, float) and n_eigenvectors < 1.0:
        return max(1, min(n_assets, int(n_eigenvectors * n_assets)))
    return max(1, min(n_assets, int(n_eigenvectors)))


def _ewma_cov(returns: Any, half_life: float) -> Any:
    """Exponentially-weighted covariance matrix (Kritzman et al. 2011, p.116).

    Weights decay as ``0.5**(age / half_life)`` with the most recent row
    (last) carrying the largest weight. The AR ratio is invariant to the
    covariance's overall scale, so weights are normalised to sum to one and
    a biased (divide-by-sum-of-weights) estimator is used.

    Parameters
    ----------
    returns : np.ndarray, shape (T, N)
        Simple periodic returns, rows = periods (oldest first), cols = assets.
    half_life : float
        Number of periods for a weight to halve. The paper sets it to half
        the window (250 days for a 500-day window).
    """
    import numpy as np

    T, N = returns.shape
    ages = np.arange(T - 1, -1, -1, dtype=float)  # last row has age 0
    w = 0.5 ** (ages / half_life)
    w = w / w.sum()
    mu = w @ returns
    dc = returns - mu
    return (dc * w[:, None]).T @ dc


def absorption_ratio(
    returns: Any,
    n_eigenvectors: int | float = 1,
    half_life: float | None = None,
) -> float:
    """AR of a returns matrix.

    Parameters
    ----------
    returns : np.ndarray, shape (T, N)
        Simple (not log) periodic returns, rows = periods, cols = assets.
    n_eigenvectors : int | float
        int = exact count, or float <1 = fraction of assets. Default 1.
    half_life : float | None
        Exponential-weighting half-life for the covariance (periods). If
        ``None``, equal-weighted covariance (``np.cov``) is used. The paper
        (Kritzman et al. 2011) uses exponential weighting with half-life
        equal to half the window.

    Returns
    -------
    float
        Fraction of total variance absorbed by the top ``n`` eigenvectors.
    """
    import numpy as np

    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError("returns must be 2-D (T, N)")
    if np.isnan(arr).any():
        raise ValueError("returns contains NaN values — align/trim inputs first")
    if arr.shape[1] < 1:
        raise ValueError("returns must have at least one asset column")

    if half_life is not None:
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        cov = _ewma_cov(arr, half_life)
    else:
        cov = np.cov(arr, rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    total = float(eigvals.sum())
    if total == 0.0:
        raise ValueError("returns have zero total variance — absorption ratio undefined")
    k = _n_keep(n_eigenvectors, arr.shape[1])
    # eigvalsh returns ascending; top k are the LAST k.
    return float(eigvals[-k:].sum() / total)


def rolling_absorption_ratio(
    closes: Any,
    window: int = 500,
    step: int = 1,
    n_eigenvectors: int | float = 1,
    half_life: float | None = None,
) -> tuple[Any, Any]:
    """Rolling absorption ratio over a close-price matrix.

    Parameters
    ----------
    closes : np.ndarray, shape (T, N)
        Close prices, rows = bars (oldest first), cols = assets.
    window : int
        Rolling window length in bars (500-days or 52-weeks canonical).
    step : int
        Recompute every ``step`` bars (1 = every bar).
    n_eigenvectors : int | float
        Passed through to :func:`absorption_ratio`.
    half_life : float | None
        Exponential-weighting half-life (bars). Passed through to
        :func:`absorption_ratio`; ``None`` = equal-weighted covariance. The
        paper uses half-life = ``window / 2``.

    Returns
    -------
    (windows_ts, ar_series) : tuple[np.ndarray, np.ndarray]
        ``windows_ts[i]`` = bar index (into *closes*) of the last bar of
        window *i*; ``ar_series[i]`` = absorption ratio over that window.
        ``len(windows_ts) = 1 + (T - window) // step``.
    """
    import numpy as np

    arr = np.asarray(closes, dtype=float)
    if arr.ndim != 2:
        raise ValueError("closes must be 2-D (T, N)")
    if arr.shape[0] <= window:
        raise ValueError(f"closes too short: {arr.shape[0]} rows < window {window}")

    returns = np.diff(arr, axis=0) / arr[:-1]
    n_windows = 1 + (arr.shape[0] - window) // step
    ar = np.full(n_windows, np.nan)
    ends = np.full(n_windows, -1, dtype=np.int64)
    for i in range(n_windows):
        last = window - 1 + i * step  # bar index (0-based) ending the window
        # returns[k] = (closes[k+1]-closes[k])/closes[k]; the closes
        # [last-window+1 .. last] span W-1 internal transitions.
        w_returns = returns[last - window + 1 : last]
        if bool(np.isnan(w_returns).any()):
            raise ValueError(
                "NaN in covariance window — align/trim inputs (trim common calendar + ffill) first"
            )
        ar[i] = absorption_ratio(w_returns, n_eigenvectors, half_life)
        ends[i] = last
    return ends, ar