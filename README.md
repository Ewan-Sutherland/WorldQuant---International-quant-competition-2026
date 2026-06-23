**Automated Alpha Research Engine**

The goal of this project was to build an engine that researches quantitative alpha signals end to end on the WorldQuant BRAIN platform - it generates candidate expressions, simulates them through the BRAIN API, filters them on risk-adjusted performance, tunes the ones that nearly pass, and stages the most uncorrelated survivors for submission. I built and iterated on it across roughly 25 versions during a quant competition, and most of what is actually interesting here came out of watching what tens of thousands of simulations did, rather than the plumbing itself.

It is a research tool and not financial advice, and it only does anything against an account that has BRAIN API access.

**How it works**

The core of it is a funnel that runs on a loop. Each tick it:

1. Generates a batch of candidate expressions from the template library, weighted toward families that have been producing eligible alphas recently.
2. Simulates them concurrently through the BRAIN API.
3. Filters on Sharpe, fitness and turnover.
4. Takes anything that nearly passes and sweeps its settings - universe, neutralisation, decay, truncation - with Optuna to try and find a configuration that gets it over the line.
5. Stages the alphas that survive and aren't too correlated with what has already gone in, ranked by how much they actually add.

State is saved every tick, so if I kill it with Ctrl+C it saves the in-flight work and picks up exactly where it left off on the next start.

**The generation engines**

There are a few different ways the engine comes up with candidates, and a good chunk of the project was working out which of them were actually worth the compute:

- Template library - parameterised families of expressions (templates.py, research_templates.py, delay0_v727_templates.py) assembled against the available data fields by generator.py.
- LLM generation (llm_generator.py) - an LLM proposes novel expressions from a prompt describing the valid operators and fields.
- Evolutionary mutation (alpha_evolver.py) - takes the strongest performers and mutates them: swap a field, change an operator, or cross two good expressions from different categories.
- Signal combination (signal_combiner.py) - blends multiple signals into composites.
- Field-gap mining (field_gap_miner.py) - deliberately goes after data fields that are barely used, on the idea that an unused field is more likely to be uncorrelated with everything already submitted.

**The key results**

The interesting part was what the run data said about where alpha actually lives. The main things I took from it:

1. Decorrelation beats individual quality. The biggest score gains came from untapped data categories - financial-statement fields, supply chain, options-implied vol - not because those alphas were individually strong but because they were uncorrelated with everything already in. Some fn_ financial fields gave score changes of +175 and +198 almost entirely from being different to the rest of the portfolio.
2. Self-correlation is the real constraint. Past a certain point the limit isn't finding alphas, it's finding ones that aren't structurally the same as ones already submitted. I use a structural-similarity score as a proxy for PnL correlation (structural sim above ~0.5 tended to mean PnL correlation above ~0.7) and cap how many variants of one core signal can go in, because 4 variants of the same core all correlate and just burn the self-correlation budget.
3. Empirical penalties beat theoretical boosts. An early version boosted families that looked decorrelated on paper, and the data showed that just funnelled compute into families with a sub-0.1% eligible rate. Replacing it with a saturation penalty driven by actual submission counts worked far better - the allocation wants to be driven by measured EV per simulation, not by what looks good in theory.
4. Evolution out-generated everything else. Mutating strong performers had a 27% positive-score hit rate, against 11% for blindly combining signals (which mostly produced noise near zero). The best-scoring in-sample alpha in the whole run came out of the mutation engine.
5. Gap mining had the highest hit rate per sim. Targeting unused fields gave a 55% positive-score hit rate - low absolute volume, but very high value per simulation, which is why it earns its compute.
6. Some whole regimes just don't work. I ran a dedicated delay-0 fork overnight and it produced 0 eligible alphas across 2125 simulations, so delay-0 is kept as a small side budget rather than a main search direction.

**Allocation**

The family and template weighting is a Thompson-sampling bandit - compute gets steered toward families that produce eligible alphas, while under-tested families keep a floor of exploration so nothing gets permanently starved. On top of that, a saturation penalty pulls compute away from families that already dominate the submitted portfolio, and a dead-core cache (48h TTL) skips re-refining cores that have already burned their Optuna budget without producing anything - so good cores get the full search and I don't keep paying for the losers.

**Submission**

submit_pipeline.py does the self-correlation and before/after score checks and picks the best variant per core signal. coordinated_submit.py coordinates submission across several owner-scoped accounts so they don't all crowd the same part of the space. A shared Supabase store lets the accounts pool their performance stats so the search doesn't repeat itself across machines.

**The Files**

main.py - entry point, with the graceful shutdown / resume.

bot.py - the core orchestration loop.

config.py - every tunable setting and all the family/template weights.

generator.py - candidate generation from templates and fields.

templates.py, research_templates.py, delay0_v727_templates.py - the template library.

llm_generator.py - LLM-guided generation.

alpha_evolver.py - evolutionary mutation of the top performers.

signal_combiner.py - combines signals into composites.

field_gap_miner.py - targets under-used data fields.

brain_client.py - the BRAIN API client (auth, simulation, scoring).

scheduler.py - bounded concurrency for the simulation slots.

evaluator.py - the eligibility gates.

settings_optimizer.py - Optuna search over simulation settings.

universe_sweeper.py - universe / neutralisation sweeps for near-passers.

similarity.py, canonicalize.py - structural similarity, used as the correlation proxy.

submit_pipeline.py - submission with the self-correlation checks.

coordinated_submit.py - multi-account submission coordination.

storage_supabase.py - shared Postgres store via Supabase.

storage.py - local SQLite fallback.

storage_factory.py - picks the storage backend.

team_weights.py - publishes and reads cross-account stats.

datasets.py - dynamic data-field loader.

dead_cores.py - the dead-core cache.

dashboard.py - run stats.

**Running it**

Requires Python 3 with requests, python-dotenv, optuna, pandas and openpyxl. Copy .env.example to .env and fill in your own BRAIN credentials (plus Supabase and LLM keys if you want the shared store and LLM generation). Then run python main.py. AUTO_SUBMIT is off by default - eligible alphas get staged for review rather than submitted automatically.

**The limitations and extra notes**

1. The tuned values in config.py are what worked on one set of accounts in one competition window. They reflect that specific run and are kept as-is - they aren't meant to be optimal anywhere else.
2. The structural-similarity correlation proxy is exactly that, a proxy. It's cheap and it works well enough to gate submissions, but it isn't a real PnL correlation.
3. A lot of the dead-family and dead-template flags are empirical calls from this account's data - on a different universe or dataset the live/dead split would move.
4. It was built for a fixed-length competition and isn't actively run now. It's up as a reference for anyone working on the same platform.
