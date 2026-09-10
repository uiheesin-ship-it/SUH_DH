"""Which screeners a build rescans, by event and by manual selection.

Worth pinning because both failure directions are expensive and neither is
loud. Too eager: a manual "just deploy this" run spends hours re-reading the
market while the concurrency group blocks every deploy queued behind it — that
is exactly what happened before the `scan` input existed. Too lazy: the
dashboard quietly stops refreshing and nothing fails.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
build = importlib.import_module("build")

EXISTING = ROOT / "build.py"                 # any path that exists
MISSING = ROOT / "data" / "__absent__.json"


def groups(monkeypatch, event, skip_base=False, scan=None):
    monkeypatch.delenv("SUH_DH_SCAN", raising=False)
    if scan is not None:
        monkeypatch.setenv("SUH_DH_SCAN", scan)
    return set(build.scan_groups(event, skip_base))


# ---------------- manual dispatch ----------------

def test_manual_run_scans_nothing_by_default(monkeypatch):
    """The default has to be deploy-only: a manual run is nearly always
    "publish this again", and scanning by default is what blocked deploys."""
    assert groups(monkeypatch, "workflow_dispatch") == set()
    assert groups(monkeypatch, "workflow_dispatch", scan="none") == set()


def test_manual_run_selects_one_market(monkeypatch):
    assert groups(monkeypatch, "workflow_dispatch", scan="kr-only") == {"kr"}
    assert groups(monkeypatch, "workflow_dispatch", scan="us-only") == {"us"}
    assert groups(monkeypatch, "workflow_dispatch", scan="all") == {"us", "kr"}


def test_manual_input_is_case_and_space_tolerant(monkeypatch):
    assert groups(monkeypatch, "workflow_dispatch", scan=" US-Only ") == {"us"}


def test_unknown_selection_scans_nothing(monkeypatch):
    """An unrecognised value must fall back to the cheap side. Defaulting a typo
    to a full scan would be a two-hour surprise."""
    assert groups(monkeypatch, "workflow_dispatch", scan="everything") == set()


# ---------------- scheduled and push runs are unchanged ----------------

def test_heavy_cron_still_scans_everything(monkeypatch):
    assert groups(monkeypatch, "schedule") == {"us", "kr"}


def test_fast_crons_still_skip(monkeypatch):
    assert groups(monkeypatch, "schedule", skip_base=True) == set()


def test_push_and_local_runs_never_scan(monkeypatch):
    assert groups(monkeypatch, "push") == set()
    assert groups(monkeypatch, "") == set()


# ---------------- per-screener gate ----------------

def test_screener_scans_only_when_its_market_is_selected(monkeypatch):
    monkeypatch.delenv("SUH_DH_FORCE_FLAT", raising=False)
    monkeypatch.delenv("SUH_DH_FORCE_KRHIGHS", raising=False)
    kr_only = frozenset({"kr"})
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", EXISTING, kr_only) is False
    assert build.should_scan("kr", "SUH_DH_FORCE_KRHIGHS", EXISTING, kr_only) is True


def test_missing_snapshot_bootstraps_regardless_of_selection(monkeypatch):
    """A newly added screener has no committed snapshot; it must build one even
    on a deploy-only run, or its page ships empty forever."""
    monkeypatch.delenv("SUH_DH_FORCE_FLAT", raising=False)
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", MISSING, frozenset()) is True


def test_per_screener_force_flag_still_wins(monkeypatch):
    monkeypatch.setenv("SUH_DH_FORCE_FLAT", "1")
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", EXISTING, frozenset()) is True
