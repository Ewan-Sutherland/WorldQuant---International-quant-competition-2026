# Alpha Research Engine

An automated alpha-research pipeline for the WorldQuant BRAIN platform. It generates
candidate alpha expressions, simulates them through the BRAIN API, filters them on
risk-adjusted performance, refines the survivors with Bayesian settings optimisation,
and stages the best uncorrelated ones for submission. A shared store lets several
accounts pool what they learn so the search doesn't repeat itself across machines.

This was built and iterated over ~25 versions during a quant competition. It is a
research tool, not financial advice, and it only works against an account that has
BRAIN API access.

## What it does

The core loop is a funnel. Each tick:

1. **Generate** a batch of candidate expressions from the template library, biased
   toward families that have been performing well.
2. **Simulate** them concurrently through the BRAIN API.
3. **Filter** on Sharpe, fitness and turnover gates.
4. **Refine** anything that nearly passes - sweep its settings (universe,
   neutralisation, decay, truncation) with Optuna to find a better configuration.
5. **Stage** eligible alphas that aren't too correlated with what's already been
   submitted, ranked by their marginal contribution.

State is persisted every tick, so a graceful shutdown (Ctrl+C) saves in-flight work
and the next start resumes exactly where it left off.

## Architecture

**Generation**
- `templates.py`, `research_templates.py`, `delay0_v727_templates.py` - the template
  library: parameterised families of alpha expressions.
- `generator.py` - assembles candidates from templates and the available data fields.
- `llm_generator.py` - LLM-guided generation for novel expressions.
- `alpha_evolver.py` - evolutionary mutation of the strongest performers.
- `signal_combiner.py` - combines multiple signals into composite alphas.
- `field_gap_miner.py` - deliberately targets under-used data fields to find
  decorrelated signals.

**Simulation and evaluation**
- `brain_client.py` - the BRAIN API client (auth, simulation, scoring).
- `scheduler.py` - bounded concurrency for simulation slots.
- `evaluator.py` - eligibility gates.
- `settings_optimizer.py` - Optuna search over simulation settings.
- `universe_sweeper.py` - universe/neutralisation sweeps for near-passers.
- `similarity.py`, `canonicalize.py` - structural similarity, used as a proxy for
  PnL correlation to avoid submitting near-duplicates.

**Allocation**
- The family/template weighting is a Thompson-sampling bandit: compute is steered
  toward families that produce eligible alphas, while under-tested families keep a
  floor of exploration so nothing is permanently starved.
- Saturation penalties pull compute away from families that already dominate the
  submitted portfolio.
- A dead-core cache skips refinement on candidates that have already exhausted their
  optimisation budget without producing anything, with a TTL so they can re-enter
  later if the portfolio shifts.

**Submission**
- `submit_pipeline.py` - self-correlation checks, before/after score checks, greedy
  selection of the best variant per signal.
- `coordinated_submit.py` - coordinates submission across multiple owner-scoped
  accounts so they don't crowd the same part of the space.

**Storage**
- `storage_supabase.py` - owner-scoped shared store (Postgres via Supabase) so
  multiple accounts share performance stats.
- `storage.py` - local SQLite fallback.
- `storage_factory.py` - selects the backend.
- `team_weights.py` - publishes and reads cross-account family/template stats.

## What the run data showed

The interesting part of this project wasn't the plumbing, it was what tens of
thousands of simulations said about where alpha actually lives. The headline lessons:

- **Decorrelation beats individual quality.** The biggest positive contributions came
  from untapped data categories - financial-statement fields, supply-chain data,
  options-implied vol - not because those alphas were individually strong, but because
  they were uncorrelated with everything already submitted. Novel data fields produced
  the largest marginal score gains in the whole run.

- **Self-correlation is the binding constraint.** Past a point, the limit on
  submissions isn't finding alphas, it's finding alphas that aren't structurally
  similar to ones already in. The pipeline treats a structural-similarity threshold
  as a stand-in for PnL correlation and caps how many variants of one core signal can
  go in.

- **Options/implied-vol was the portfolio-additive core.** This family kept earning
  its place where saturated mean-reversion and cross-sectional families had stopped
  contributing.

- **Empirical penalties beat theoretical boosts.** An early version boosted families
  that looked decorrelated on paper; the data showed that just funnelled compute into
  families with a sub-0.1% eligible rate. A saturation penalty driven by actual
  portfolio counts worked far better. Measured EV-per-simulation, not intuition,
  drove the allocation.

- **Evolution out-generated combination.** Mutating strong performers had a much
  higher positive-score hit rate than blindly combining signals, which mostly produced
  noise near zero.

- **Some whole regimes underperformed structurally.** A dedicated delay-0 run produced
  zero eligible alphas across thousands of simulations, so delay-0 was kept only as a
  small side-budget rather than a main search direction.

## Tech stack

Python, `requests`, `python-dotenv`, Optuna, pandas, openpyxl, Supabase (Postgres),
SQLite.

## Setup

1. Install dependencies:
   ```bash
   pip install requests python-dotenv optuna pandas openpyxl
   ```
2. Create a `.env` from the template and fill in your own credentials:
   ```
   BRAIN_USERNAME=...
   BRAIN_PASSWORD=...
   GEMINI_API_KEYS=...        # optional, for LLM-guided generation
   SUPABASE_URL=...           # optional, only if using the shared store
   SUPABASE_ANON_KEY=...
   ```
   Credentials are read from the environment - nothing is hardcoded.
3. Run:
   ```bash
   python main.py
   ```
   `AUTO_SUBMIT` is off by default; eligible alphas are staged for review rather than
   submitted automatically.

## Repository layout

```
main.py                 entry point (with graceful shutdown / resume)
bot.py                  core orchestration loop
config.py               all tunable settings and family/template weights
generator.py            candidate generation
templates.py            template library
brain_client.py         BRAIN API client
settings_optimizer.py   Optuna settings search
submit_pipeline.py      submission with self-correlation checks
coordinated_submit.py   multi-account submission coordination
storage_supabase.py     shared Postgres store (Supabase)
storage.py              local SQLite fallback
field_gap_miner.py      under-used-field targeting
similarity.py           structural similarity / correlation proxy
datasets.py             dynamic data-field loader
...
```

## Status

Built for a fixed-length competition and no longer actively run. Published as a
reference - the tuned values in `config.py` reflect what worked on one set of accounts
and are kept as-is for anyone exploring the same platform.
