"""Tests for pytvtools_core.measures — absorption ratio."""
import numpy as np
import pytest

from pytvtools_core.measures import absorption_ratio, rolling_absorption_ratio


def test_absorption_ratio_frds_example():
    """Reproduce frds.io documented example (3 assets, 6 days, frac 0.2)."""
    data = np.array([
        [0.015, 0.031, 0.007, 0.034, 0.014, 0.011],
        [0.012, 0.063, 0.027, 0.023, 0.073, 0.055],
        [0.072, 0.043, 0.097, 0.078, 0.036, 0.083],
    ])  # (n_assets, n_days); pass as (T, N) = (days, assets)
    returns = data.T
    ar = absorption_ratio(returns, n_eigenvectors=0.2)
    assert ar == pytest.approx(0.7746543307660259, abs=1e-9)


def test_absorption_ratio_top1_equals_fraction_for_small_N():
    """For N=3, frac 0.2 resolves to 1 eigenvector — same AR as n=1."""
    data = np.array([
        [0.015, 0.031, 0.007, 0.034, 0.014, 0.011],
        [0.012, 0.063, 0.027, 0.023, 0.073, 0.055],
        [0.072, 0.043, 0.097, 0.078, 0.036, 0.083],
    ])
    a_frac = absorption_ratio(data.T, n_eigenvectors=0.2)
    a_one = absorption_ratio(data.T, n_eigenvectors=1)
    assert a_frac == pytest.approx(a_one)


def test_absorption_ratio_perfect_correlation_is_one():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(500)
    returns = np.column_stack([x, x])  # asset 2 = asset 1 exactly
    assert absorption_ratio(returns, n_eigenvectors=1) == pytest.approx(1.0)


def test_absorption_ratio_monotonic_in_eigenvectors():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(500)
    z = rng.standard_normal(500)
    returns = np.column_stack([x, 0.8 * x + 0.2 * z])  # correlated pair
    ar1 = absorption_ratio(returns, n_eigenvectors=1)
    ar2 = absorption_ratio(returns, n_eigenvectors=2)
    assert 0.8 < ar1 < ar2 <= 1.0


def test_absorption_ratio_raises_on_zero_variance():
    returns = np.ones((10, 3))
    try:
        absorption_ratio(returns, n_eigenvectors=1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on zero-total-variance input")


def test_absorption_ratio_raises_on_nan():
    rng = np.random.default_rng(2)
    returns = rng.standard_normal((10, 3))
    returns[3, 1] = np.nan
    try:
        absorption_ratio(returns, n_eigenvectors=1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on NaN input")


def test_rolling_computes_windowed_ar():
    # 2 assets, 100 closes; one tracks the other with tiny noise.
    rng = np.random.default_rng(3)
    drift = np.linspace(1.0, 2.0, 100)
    noise = rng.standard_normal(100) * 0.0001
    closes = np.column_stack([drift, drift + noise])
    win_ts, ar = rolling_absorption_ratio(closes, window=30, n_eigenvectors=1)
    assert win_ts.shape == ar.shape
    assert len(ar) == 100 - 30 + 1  # window over closes ends at idx 29..99
    assert win_ts[0] == 29 and win_ts[-1] == 99
    assert np.nanmax(ar) <= 1.0 + 1e-9
    assert np.nanmean(ar) > 0.95  # near-perfect correlation


def test_rolling_step():
    rng = np.random.default_rng(4)
    closes = np.cumsum(rng.standard_normal((150, 3)), axis=0) + 100.0
    end, ar = rolling_absorption_ratio(closes, window=20, step=5, n_eigenvectors=1)
    # windows end at close indices 19, 24, 29, ... => count:
    assert len(ar) == 1 + (150 - 20) // 5
    assert end[0] == 19 and end[1] == 24
    assert end[-1] == 149


def test_rolling_asserts_no_nan_in_window():
    rng = np.random.default_rng(5)
    closes = np.cumsum(rng.standard_normal((50, 3)), axis=0) + 100.0
    closes[25, 0] = np.nan
    try:
        rolling_absorption_ratio(closes, window=10, n_eigenvectors=1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on NaN in window")


def test_absorption_ratio_exponential_matches_manual_weighted_cov():
    """Exponential weighting (half-life) must equal a hand-computed
    exponentially-weighted covariance eigendecomposition."""
    rng = np.random.default_rng(8)
    returns = rng.standard_normal((40, 3))
    half_life = 10.0

    T = returns.shape[0]
    ages = np.arange(T - 1, -1, -1)  # oldest row has the largest age
    w = 0.5 ** (ages / half_life)
    w = w / w.sum()
    mu = np.sum(returns * w[:, None], axis=0)
    dc = returns - mu
    cov = (dc * w[:, None]).T @ dc
    eig = np.linalg.eigvalsh(cov)
    expected = float(eig[-1:].sum() / eig.sum())

    got = absorption_ratio(returns, n_eigenvectors=1, half_life=half_life)
    assert got == pytest.approx(expected, abs=1e-9)


def test_absorption_ratio_long_half_life_equals_equal_weight():
    """A very long half-life makes weights ~uniform, recovering np.cov."""
    rng = np.random.default_rng(9)
    returns = rng.standard_normal((60, 4))
    ar_short = absorption_ratio(returns, n_eigenvectors=2, half_life=5)
    ar_long = absorption_ratio(returns, n_eigenvectors=2, half_life=1e6)
    ar_eq = absorption_ratio(returns, n_eigenvectors=2)
    assert ar_long == pytest.approx(ar_eq, abs=1e-4)
    # recent correlation dominates with a short half-life -> different value
    assert not np.isclose(ar_short, ar_eq)


def test_absorption_ratio_exponential_captures_recent_correlation():
    """A recent correlation spike should raise AR more under a short half-life
    than under equal weighting."""
    rng = np.random.default_rng(10)
    n = 300
    x = rng.standard_normal(n)
    z = rng.standard_normal(n)
    y = np.where(np.arange(n) < n - 60, z, x)  # uncorrelated, then = x
    returns = np.column_stack([x, y])
    ar_short = absorption_ratio(returns, n_eigenvectors=1, half_life=10)
    ar_eq = absorption_ratio(returns, n_eigenvectors=1)
    assert ar_short > ar_eq


def test_rolling_exponential_half_life():
    rng = np.random.default_rng(11)
    closes = np.cumsum(rng.standard_normal((120, 3)), axis=0) + 100.0
    end, ar = rolling_absorption_ratio(
        closes, window=20, n_eigenvectors=1, half_life=10
    )
    assert len(ar) == 1 + (120 - 20)
    assert np.nanmax(ar) <= 1.0 + 1e-9