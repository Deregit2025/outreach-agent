PYTHON := python

# ── Quick health check (no API key needed, ~10s) ──────────────────────────────
.PHONY: check
check:
	$(PYTHON) scripts/build_report.py

# ── τ²-Bench smoke test (2 tasks, 1 trial — cheapest possible run) ────────────
.PHONY: bench-smoke
bench-smoke:
	$(PYTHON) eval/harness.py --mode dev --max-tasks 2 --trials 1 --run-name smoke_$(shell date +%Y%m%dT%H%M%S)

# ── τ²-Bench dev baseline (30 tasks, 2 trials — interim submission) ───────────
.PHONY: bench
bench:
	$(PYTHON) eval/harness.py --mode dev --trials 2 --run-name dev_baseline_v1

# ── τ²-Bench held-out (20 tasks, 5 trials — final submission) ────────────────
.PHONY: bench-final
bench-final:
	$(PYTHON) eval/harness.py --mode held_out --trials 5 --run-name held_out_final_v1

# ── Full report: health check + score log summary ─────────────────────────────
.PHONY: report
report: check
	@echo ""
	@echo "Score log history:"
	@$(PYTHON) -c "\
import json, pathlib; \
log = json.loads(pathlib.Path('eval/score_log.json').read_text()); \
[print(f\"  {e['run_name']:30s}  pass@1={e['pass_at_1']:.1%}  tasks={e['num_tasks']}  trials={e['num_trials']}  cost=\$${e['total_agent_cost_usd']:.4f}\") for e in log] if log else print('  (no runs yet)')"

# ── Start the API server ──────────────────────────────────────────────────────
.PHONY: serve
serve:
	uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

# ── Install dependencies ──────────────────────────────────────────────────────
.PHONY: install
install:
	pip install -r requirements.txt
	pip install -e ./tau2-bench
