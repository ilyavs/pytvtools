"""Tests for pytvtools_core.measures — absorption ratio."""
import numpy as np
import pytest

from pytvtools_core.measures import absorption_ratio


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