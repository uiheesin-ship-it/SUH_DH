"""Incremental harvester: budget cap, resume, skip-collected, empty handling.

Uses a fake provider that counts calls so we can prove already-collected
tickers are NOT re-fetched, and that an interrupted run resumes next time
(spec §22). Also an end-to-end pass with the real Alpha Vantage adapter (HTTP
mocked) to confirm collected files are readable back by the directory provider.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.eai import harvest
from app.eai.providers.transcript.base import RawTranscript, TranscriptRef


class FakeProvider:
    name = "fake"

    def __init__(self, quarters, empty=(), fail=()):
        self.quarters = quarters          # {ticker: [(year, q), ...]}
        self.empty = set(empty)
        self.fail = set(fail)
        self.list_calls: list[str] = []
        self.fetch_calls: list[str] = []

    def list_available(self, ticker, since=None):
        self.list_calls.append(ticker)
        return [TranscriptRef(ticker=ticker, fiscal_year=y, fiscal_quarter=q,
                              source="fake", source_identifier=f"{y}Q{q}")
                for (y, q) in self.quarters.get(ticker, [])]

    def fetch(self, ref):
        key = f"{ref.ticker}_{ref.fiscal_year}Q{ref.fiscal_quarter}"
        self.fetch_calls.append(key)
        if key in self.fail:
            raise RuntimeError("transient network error")
        if key in self.empty:
            raise ValueError("no transcript for this quarter")
        return RawTranscript(
            ticker=ref.ticker, fiscal_year=ref.fiscal_year, fiscal_quarter=ref.fiscal_quarter,
            source="fake",
            structured={"sections": [{"section_type": "prepared_remarks", "turns": [
                {"speaker_name": "CEO", "speaker_role": "ceo", "text": "AI demand was strong."}]}]})


QUARTERS = {"AAA": [(2026, 2), (2026, 1)], "BBB": [(2026, 2), (2026, 1)],
            "CCC": [(2026, 2), (2026, 1)]}


def _paths(tmp_path):
    return tmp_path / "transcripts", tmp_path / "harvest_state.json"


def test_budget_cap_stops_mid_worklist(tmp_path):
    out, ledger = _paths(tmp_path)
    prov = FakeProvider(QUARTERS)
    res = harvest.run_harvest(prov, ["AAA", "BBB", "CCC"], out_dir=out, ledger_path=ledger,
                              daily_budget=4, quarters_per_ticker=2, now="run1")
    assert res.requests_used == 4              # never exceeds the daily budget
    assert res.budget_exhausted is True
    # AAA: 1 list + 2 fetch = 3; BBB: 1 list = 4 → stop before BBB fetches
    assert res.collected == ["AAA_2026Q2", "AAA_2026Q1"]
    assert (out / "AAA_2026Q2.json").exists() and (out / "AAA_2026Q1.json").exists()
    assert not (out / "BBB_2026Q2.json").exists()
    assert ledger.exists()


def test_resume_skips_collected_without_refetch(tmp_path):
    out, ledger = _paths(tmp_path)
    prov = FakeProvider(QUARTERS)
    harvest.run_harvest(prov, ["AAA", "BBB", "CCC"], out_dir=out, ledger_path=ledger,
                        daily_budget=4, quarters_per_ticker=2, now="run1")
    prov.fetch_calls.clear()
    prov.list_calls.clear()

    res2 = harvest.run_harvest(prov, ["AAA", "BBB", "CCC"], out_dir=out, ledger_path=ledger,
                               daily_budget=4, quarters_per_ticker=2, now="run2")
    # AAA already collected → NOT re-fetched, NOT re-listed
    assert "AAA" not in prov.list_calls
    assert not any(k.startswith("AAA_") for k in prov.fetch_calls)
    # continues where it left off: BBB fetched, CCC listed + started
    assert "BBB_2026Q2" in res2.collected and "BBB_2026Q1" in res2.collected
    assert (out / "BBB_2026Q2.json").exists()


def test_full_completion_over_multiple_runs(tmp_path):
    out, ledger = _paths(tmp_path)
    prov = FakeProvider(QUARTERS)
    total = 0
    for i in range(5):
        r = harvest.run_harvest(prov, ["AAA", "BBB", "CCC"], out_dir=out, ledger_path=ledger,
                                daily_budget=4, quarters_per_ticker=2, now=f"run{i}")
        total += r.requests_used
        if r.worklist_done:
            break
    # every ticker/quarter collected exactly once, no duplicate fetches
    assert sorted(prov.fetch_calls) == sorted(prov.fetch_calls) and len(set(prov.fetch_calls)) == 6
    for t in ("AAA", "BBB", "CCC"):
        assert (out / f"{t}_2026Q2.json").exists() and (out / f"{t}_2026Q1.json").exists()


def test_empty_quarter_marked_and_not_refetched(tmp_path):
    out, ledger = _paths(tmp_path)
    prov = FakeProvider(QUARTERS, empty={"AAA_2026Q1"})
    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=2, now="run1")
    assert not (out / "AAA_2026Q1.json").exists()      # empty → no file
    state = json.loads(ledger.read_text())
    assert state["tickers"]["AAA"]["collected"]["2026Q1"] == "empty"
    prov.fetch_calls.clear()
    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=2, now="run2")
    assert "AAA_2026Q1" not in prov.fetch_calls        # known-empty not retried


def test_self_heal_refetches_when_file_missing(tmp_path):
    """Ledger says 'collected' but the file is gone (cache evicted) → re-fetch."""
    out, ledger = _paths(tmp_path)
    prov = FakeProvider({"AAA": [(2026, 2)]})
    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=1, now="run1")
    assert (out / "AAA_2026Q2.json").exists()
    (out / "AAA_2026Q2.json").unlink()          # simulate cache eviction
    prov.fetch_calls.clear()

    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=1, now="run2")
    assert "AAA_2026Q2" in prov.fetch_calls      # re-fetched to self-heal
    assert (out / "AAA_2026Q2.json").exists()


def test_empty_quarter_list_is_retried_next_run(tmp_path):
    """A throttled listing (empty quarters) must be retried, not cached forever."""
    out, ledger = _paths(tmp_path)
    prov = FakeProvider({})                      # AAA lists nothing (throttled)
    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=2, now="run1")
    prov.quarters = {"AAA": [(2026, 2)]}         # now available next run
    r2 = harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                             daily_budget=10, quarters_per_ticker=2, now="run2")
    assert "AAA_2026Q2" in r2.collected          # re-listed and collected


def test_existing_file_is_skipped(tmp_path):
    out, ledger = _paths(tmp_path)
    out.mkdir(parents=True)
    (out / "AAA_2026Q2.json").write_text('{"sections": []}', encoding="utf-8")
    prov = FakeProvider({"AAA": [(2026, 2)]})
    harvest.run_harvest(prov, ["AAA"], out_dir=out, ledger_path=ledger,
                        daily_budget=10, quarters_per_ticker=1, now="run1")
    assert prov.fetch_calls == []                       # file present → no API call


def test_quarter_backfill_priority_and_budget(tmp_path):
    """Backfill fills quarter-by-quarter in priority order, capped by budget."""
    out, ledger = _paths(tmp_path)
    prov = FakeProvider({})  # quarters not used in explicit mode
    tickers = ["AAA", "BBB", "CCC"]
    quarters = ["2026Q1", "2025Q4"]
    # budget 4 → 2026Q1 for AAA,BBB,CCC (3) + 2025Q4 for AAA (1) = 4
    r = harvest.run_harvest_quarters(prov, tickers, quarters, [], out_dir=out,
                                     ledger_path=ledger, daily_budget=4, now="run1")
    assert r.requests_used == 4
    assert r.collected == ["AAA_2026Q1", "BBB_2026Q1", "CCC_2026Q1", "AAA_2025Q4"]
    assert r.budget_exhausted is True


def test_quarter_backfill_resumes_next_run(tmp_path):
    out, ledger = _paths(tmp_path)
    prov = FakeProvider({})
    tickers = ["AAA", "BBB", "CCC"]
    quarters = ["2026Q1", "2025Q4"]
    harvest.run_harvest_quarters(prov, tickers, quarters, [], out_dir=out,
                                 ledger_path=ledger, daily_budget=4, now="run1")
    prov.fetch_calls.clear()
    r2 = harvest.run_harvest_quarters(prov, tickers, quarters, [], out_dir=out,
                                      ledger_path=ledger, daily_budget=10, now="run2")
    # already-collected not re-fetched; remaining backfill completed
    assert not any(k in ("AAA_2026Q1", "BBB_2026Q1", "CCC_2026Q1", "AAA_2025Q4")
                   for k in prov.fetch_calls)
    for t in tickers:
        assert (out / f"{t}_2026Q1.json").exists() and (out / f"{t}_2025Q4.json").exists()


def test_frontier_recheck_retries_empty_but_backfill_does_not(tmp_path):
    """Frontier (2026Q2) empties are retried each run; backfill empties are not."""
    out, ledger = _paths(tmp_path)
    # 2025Q4 (backfill) empty AND 2026Q2 (frontier) empty on first run
    prov = FakeProvider({}, empty={"AAA_2025Q4", "AAA_2026Q2"})
    harvest.run_harvest_quarters(prov, ["AAA"], ["2025Q4"], ["2026Q2"], out_dir=out,
                                 ledger_path=ledger, daily_budget=10, now="run1")
    prov.fetch_calls.clear()
    prov.empty = set()  # both now have data available
    r2 = harvest.run_harvest_quarters(prov, ["AAA"], ["2025Q4"], ["2026Q2"], out_dir=out,
                                      ledger_path=ledger, daily_budget=10, now="run2")
    assert "AAA_2026Q2" in prov.fetch_calls        # frontier retried → now collected
    assert "AAA_2025Q4" not in prov.fetch_calls     # backfill empty left alone
    assert "AAA_2026Q2" in r2.collected


def test_harvest_with_alpha_vantage_then_directory_reads_it(tmp_path, monkeypatch):
    """End-to-end: harvest via the real AV adapter (HTTP mocked) → directory reads."""
    from app.eai.providers.transcript.alphavantage import AlphaVantageTranscriptProvider
    from app.eai.providers.transcript.directory import DirectoryTranscriptProvider

    av = AlphaVantageTranscriptProvider(api_key="k", base="https://av.test")
    earnings = {"quarterlyEarnings": [{"fiscalDateEnding": "2026-06-30"}]}
    transcript = {"transcript": [
        {"speaker": "Operator", "title": "", "content": "Welcome."},
        {"speaker": "Jane Doe", "title": "CEO", "content": "AI demand was strong."},
        {"speaker": "Analyst A", "title": "Bank - Analyst", "content": "Question about demand?"},
        {"speaker": "Jane Doe", "title": "CEO", "content": "Demand remains robust."}]}
    av._get = lambda params: earnings if params["function"] == "EARNINGS" else transcript

    out, ledger = _paths(tmp_path)
    res = harvest.run_harvest(av, ["NVDA"], out_dir=out, ledger_path=ledger,
                              daily_budget=10, quarters_per_ticker=1, now="run1")
    assert res.collected == ["NVDA_2026Q2"]
    assert (out / "NVDA_2026Q2.json").exists()

    # the directory provider (used by the analysis step) can read it back
    dprov = DirectoryTranscriptProvider(out)
    refs = dprov.list_available("NVDA")
    assert len(refs) == 1
    raw = dprov.fetch(refs[0])
    assert raw.structured and raw.structured["sections"][0]["section_type"] == "prepared_remarks"
