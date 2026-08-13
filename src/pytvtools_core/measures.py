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


def absorption_ratio(
    returns: Any,
    n_eigenvectors: int | float = 1,
) -> float:
    """AR of a returns matrix.

    Parameters
    ----------
    returns : np.ndarray, shape (T, N)
        Simple (not log) periodic returns, rows = periods, cols = assets.
    n_eigenvectors : int | float
        int = exact count, or float <1 = fraction of assets. Default 1.

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

    cov = np.cov(arr, rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    k = _n_keep(n_eigenvectors, arr.shape[1])
    # eigvalsh returns ascending; top k are the LAST k.
    return float(eigvals[-k:].sum() / eigvals.sum())