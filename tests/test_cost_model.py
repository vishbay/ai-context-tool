"""Tests for cram.cost_model."""
import os
import pytest


def test_orientation_caps_at_repo_tokens():
    from cram.cost_model import orientation_tokens
    # If ORIENT_FILES * avg_file > repo_tokens, cap at repo_tokens.
    # 100 files, 10 tok each = 1000 tok repo; orient = min(1000, 8*10) = 80
    result = orientation_tokens(1000, 100)
    assert result <= 1000
    # With a tiny repo where orient would exceed repo size:
    assert orientation_tokens(10, 100) <= 10


def test_orientation_zero_files():
    from cram.cost_model import orientation_tokens
    assert orientation_tokens(0, 0) == 0
    assert orientation_tokens(1000, 0) == 0
    assert orientation_tokens(0, 10) == 0


def test_daily_saving_never_negative():
    from cram.cost_model import CostInputs, daily_costs
    # Even when frozen_tok is large relative to orient
    inp = CostInputs(repo_tokens=100, repo_files=10, frozen_tok=50_000)
    d = daily_costs(inp, 3.0)
    assert d['daily_saving'] >= 0.0


def test_nocram_scales_linearly_with_orient_files(monkeypatch):
    from cram import cost_model
    monkeypatch.setattr(cost_model, 'ORIENT_FILES', 4)
    from cram.cost_model import CostInputs, daily_costs, orientation_tokens
    inp = CostInputs(repo_tokens=10_000, repo_files=100, frozen_tok=500)
    d4 = daily_costs(inp, 3.0)

    monkeypatch.setattr(cost_model, 'ORIENT_FILES', 8)
    d8 = daily_costs(inp, 3.0)

    # Doubling ORIENT_FILES should double nocram_daily (assuming orient doesn't cap)
    assert abs(d8['nocram_daily'] / d4['nocram_daily'] - 2.0) < 0.01


def test_daily_costs_returns_expected_keys():
    from cram.cost_model import CostInputs, daily_costs
    inp = CostInputs(repo_tokens=50_000, repo_files=50, frozen_tok=2_000)
    d = daily_costs(inp, 3.0)
    assert set(d.keys()) == {'orient_tokens', 'nocram_daily', 'cram_daily', 'daily_saving'}


def test_import_works():
    from cram.cost_model import daily_costs, CostInputs  # noqa: F401
