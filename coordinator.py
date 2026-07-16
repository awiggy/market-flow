"""
Coordinator: the harness layer that wraps main.py's pipeline.

Before: main.py runs 5 steps in sequence. If step 2 fails, everything crashes.
After:  each step returns (OK|FAIL) + data. The coordinator checks each result
        and decides what to do next — retry, skip, fallback, or abort.

This is Harness Engineering in practice:
  - We do NOT trust the network.
  - We do NOT trust the data.
  - We do NOT trust that any single step will succeed.
  - Every step has a fallback plan.
"""

from enum import Enum
from datetime import datetime


class Status(Enum):
    OK = "ok"
    FAIL = "fail"
    EMPTY = "empty"
    FALLBACK = "fallback"


class StepResult:
    """Every step returns this. The coordinator reads `.status` to decide what's next."""
    def __init__(self, status, data=None, error=None, note=""):
        self.status = status
        self.data = data
        self.error = error
        self.note = note

    @property
    def ok(self):
        return self.status == Status.OK

    @property
    def degraded(self):
        """OK but with degraded quality (e.g. fallback data was used)"""
        return self.status in (Status.EMPTY, Status.FALLBACK)


class PipelineCoordinator:
    """
    The "conductor" that runs the pipeline and makes decisions between steps.

    Rule 1: After every step, check status.
    Rule 2: If critical step fails → abort with clear reason.
    Rule 3: If non-critical step fails → use fallback, continue.
    Rule 4: Log every decision so we know what happened.
    """

    def __init__(self):
        self.log = []
        self.aborted = False
        self.abort_reason = ""

    # ── Decision helpers ──
    def _ok(self, result, step_name):
        self.log.append(f"[OK] {step_name}")
        return True

    def _fail_abort(self, result, step_name, reason):
        self.log.append(f"[ABORT] {step_name}: {reason} ({result.error})")
        self.aborted = True
        self.abort_reason = reason
        return False

    def _fail_continue(self, result, step_name, fallback_note):
        self.log.append(f"[FALLBACK] {step_name}: {fallback_note}")
        return True

    # ── Pipeline steps ──

    def step_init_db(self):
        try:
            from store import init_db
            init_db()
            return StepResult(Status.OK)
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    def step_fetch_data(self):
        try:
            from fetch import fetch_all
            data = fetch_all()
            if len(data.get("sector_flow", [])) == 0:
                return StepResult(
                    Status.EMPTY, data=data,
                    note="No sector flow data (non-trading day or API down)"
                )
            return StepResult(Status.OK, data=data)
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    def step_save_data(self, data):
        try:
            from store import save_all
            save_all(data)
            return StepResult(Status.OK)
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    def step_read_history(self):
        try:
            from store import get_history
            history = get_history(days=10)
            n_days = len(history["sector"]["date"].unique())
            return StepResult(Status.OK, data={"history": history, "n_days": n_days})
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    def step_analyze(self, data, history):
        try:
            from analyze import (
                analyze_market_temperature, analyze_sector_flow,
                analyze_siphon, analyze_northbound, analyze_margin,
                analyze_etf_position,
            )
            temperature = analyze_market_temperature(
                data.get("market_flow", {}),
                data.get("sector_flow", []),
                data.get("northbound", {}),
            )
            sa = analyze_sector_flow(data["sector_flow"])
            siphon = analyze_siphon(data["sector_flow"], history)
            nb = analyze_northbound(data.get("northbound", {}), history)
            mg = analyze_margin(data.get("margin_change_5d", 0))
            etf = analyze_etf_position(data["sector_flow"], siphon)
            return StepResult(Status.OK, data={
                "temperature": temperature,
                "sector_flow_analysis": sa,
                "siphon_alerts": siphon,
                "northbound_analysis": nb,
                "margin_analysis": mg,
                "etf_position": etf,
            })
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    def step_generate_report(self, data, analysis):
        try:
            from summary import generate
            report = generate(data, analysis)
            return StepResult(Status.OK, data=report)
        except Exception as e:
            return StepResult(Status.FAIL, error=str(e))

    # ── The conductor ──

    def run(self):
        print("=" * 60)
        print(f"  Pipeline Coordinator - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 60)

        # Step 1: Init DB (CRITICAL — can't proceed without it)
        r = self.step_init_db()
        if not self._ok(r, "Init DB"):
            return self._fail_abort(r, "Init DB", "Database initialization failed")

        # Step 2: Fetch data (CRITICAL — but has fallback)
        r = self.step_fetch_data()
        if r.status == Status.EMPTY:
            self._fail_continue(r, "Fetch Data", "No new data, will use history fallback")
            data = r.data
        elif r.ok:
            self._ok(r, f"Fetch Data ({len(r.data.get('sector_flow',[]))} sectors)")
            data = r.data
        else:
            return self._fail_abort(r, "Fetch Data", "Network error, no cached data available")

        # Step 3: Save (NON-CRITICAL — can continue even if save fails)
        r = self.step_save_data(data)
        if r.ok:
            self._ok(r, "Save Data")
        else:
            self._fail_continue(r, "Save Data", "Save failed, continuing with analysis")

        # Step 4: Read history
        r = self.step_read_history()
        if r.ok:
            self._ok(r, f"Read History ({r.data['n_days']} trading days)")
            history = r.data["history"]
        else:
            self._fail_continue(r, "Read History", "No history available, analysis may be limited")
            history = {"sector": [], "northbound": [], "margin": []}

        # Step 4.5: Fallback logic — if today empty, use most recent day
        sector_empty = len(data.get("sector_flow", [])) == 0
        if sector_empty:
            print("      [COORDINATOR] Sector data empty, activating fallback...")
            hist_sector = history.get("sector", [])
            if len(hist_sector) > 0:
                latest_date = hist_sector["date"].max() if hasattr(hist_sector, 'date') else None
                print(f"      [COORDINATOR] Using historical data from {latest_date}")
                data["date"] = latest_date

        # Step 5: Analyze
        r = self.step_analyze(data, history)
        if r.ok:
            self._ok(r, "Analyze")
            analysis = r.data
        else:
            return self._fail_abort(r, "Analyze", "Analysis engine failed")

        # Step 6: Generate report
        r = self.step_generate_report(data, analysis)
        if r.ok:
            self._ok(r, "Generate Report")
        else:
            self._fail_continue(r, "Generate Report", "Report generation failed")

        # ── Summary ──
        print()
        print("─" * 60)
        print("  Coordinator Decision Log:")
        for entry in self.log:
            print(f"    {entry}")

        if self.aborted:
            print(f"\n  Pipeline ABORTED: {self.abort_reason}")
            return None

        print(f"\n  Pipeline completed with {sum(1 for e in self.log if 'FALLBACK' in e)} fallback(s)")
        return r.data if isinstance(r, StepResult) and r.ok else None


if __name__ == "__main__":
    coordinator = PipelineCoordinator()
    result = coordinator.run()
    if result:
        print(result)
    else:
        print("\n  Pipeline failed. Check the decision log above.")
