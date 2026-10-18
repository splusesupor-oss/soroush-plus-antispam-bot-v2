"""Keep pre-existing feature-behavior tests on the full plan.

Those tests validate the original paid implementations. New free-tier tests
explicitly select the free policy, so the old feature regressions remain
meaningful without silently turning the production default back on.
"""
import pytest


@pytest.fixture(autouse=True)
def legacy_features_use_premium_plan(monkeypatch):
    from modules import free_tier
    monkeypatch.setattr(free_tier, "PLAN", "premium")
    # Propagate the same plan into the subprocesses used by storage regressions.
    monkeypatch.setenv("SOROUSH_BOT_PLAN", "premium")
