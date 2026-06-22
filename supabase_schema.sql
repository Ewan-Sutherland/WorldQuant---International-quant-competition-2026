-- WorldQuant alpha bot - Supabase schema
-- paste this into the Supabase SQL editor and click "Run"

-- candidates - every unique expression + settings combination
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    canonical_expression TEXT NOT NULL,
    expression_hash TEXT NOT NULL UNIQUE,
    template_id TEXT NOT NULL,
    family TEXT NOT NULL,
    fields_json JSONB NOT NULL DEFAULT '[]',
    params_json JSONB NOT NULL DEFAULT '{}',
    settings_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- runs - every simulation attempt
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    sim_id TEXT,
    alpha_id TEXT,
    status TEXT NOT NULL,
    submitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    raw_result_json JSONB
);

-- metrics - results for each run
CREATE TABLE IF NOT EXISTS metrics (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    returns REAL,
    margin REAL,
    drawdown REAL,
    checks_passed BOOLEAN,
    submit_eligible BOOLEAN,
    fail_reason TEXT
);

-- submissions - alphas that were submitted to WQ
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submission_status TEXT NOT NULL,
    message TEXT
);

-- refinement queue - candidates queued for refinement
CREATE TABLE IF NOT EXISTS refinement_queue (
    candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    priority REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed BOOLEAN NOT NULL DEFAULT FALSE,
    source_stage TEXT DEFAULT 'unknown',
    base_sharpe REAL,
    base_fitness REAL,
    base_turnover REAL
);

-- indexes for common queries
CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(expression_hash);
CREATE INDEX IF NOT EXISTS idx_candidates_family ON candidates(family);
CREATE INDEX IF NOT EXISTS idx_candidates_template ON candidates(template_id);
CREATE INDEX IF NOT EXISTS idx_runs_candidate ON runs(candidate_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_metrics_sharpe ON metrics(sharpe);
CREATE INDEX IF NOT EXISTS idx_metrics_fitness ON metrics(fitness);
CREATE INDEX IF NOT EXISTS idx_metrics_eligible ON metrics(submit_eligible);
CREATE INDEX IF NOT EXISTS idx_refinement_consumed ON refinement_queue(consumed);
CREATE INDEX IF NOT EXISTS idx_refinement_priority ON refinement_queue(priority DESC);

-- row level security - allow all operations via the anon key
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE refinement_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "allow_all_candidates" ON candidates FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_runs" ON runs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_metrics" ON metrics FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_submissions" ON submissions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_refinement" ON refinement_queue FOR ALL USING (true) WITH CHECK (true);

-- RPC functions for complex aggregate queries

-- family stats (GROUP BY with JOINs)
CREATE OR REPLACE FUNCTION get_family_stats(run_limit INT DEFAULT 500)
RETURNS TABLE (
    family TEXT,
    n_runs BIGINT,
    avg_sharpe DOUBLE PRECISION,
    avg_fitness DOUBLE PRECISION,
    avg_turnover DOUBLE PRECISION,
    submit_rate DOUBLE PRECISION
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.family,
        COUNT(*)::BIGINT AS n_runs,
        AVG(m.sharpe)::DOUBLE PRECISION AS avg_sharpe,
        AVG(m.fitness)::DOUBLE PRECISION AS avg_fitness,
        AVG(m.turnover)::DOUBLE PRECISION AS avg_turnover,
        AVG(CASE WHEN m.submit_eligible THEN 1.0 ELSE 0.0 END)::DOUBLE PRECISION AS submit_rate
    FROM metrics m
    JOIN runs r ON m.run_id = r.run_id
    JOIN candidates c ON r.candidate_id = c.candidate_id
    WHERE r.run_id IN (
        SELECT r2.run_id FROM runs r2
        WHERE r2.status = 'completed'
        ORDER BY r2.completed_at DESC
        LIMIT run_limit
    )
    GROUP BY c.family
    ORDER BY COUNT(*) DESC;
END;
$$ LANGUAGE plpgsql;

-- template stats (GROUP BY with JOINs)
CREATE OR REPLACE FUNCTION get_template_stats(run_limit INT DEFAULT 180)
RETURNS TABLE (
    template_id TEXT,
    family TEXT,
    n_runs BIGINT,
    avg_sharpe DOUBLE PRECISION,
    avg_fitness DOUBLE PRECISION,
    avg_turnover DOUBLE PRECISION
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.template_id,
        c.family,
        COUNT(*)::BIGINT AS n_runs,
        AVG(m.sharpe)::DOUBLE PRECISION AS avg_sharpe,
        AVG(m.fitness)::DOUBLE PRECISION AS avg_fitness,
        AVG(m.turnover)::DOUBLE PRECISION AS avg_turnover
    FROM metrics m
    JOIN runs r ON m.run_id = r.run_id
    JOIN candidates c ON r.candidate_id = c.candidate_id
    WHERE r.run_id IN (
        SELECT r2.run_id FROM runs r2
        WHERE r2.status = 'completed'
        ORDER BY r2.completed_at DESC
        LIMIT run_limit
    )
    GROUP BY c.template_id, c.family
    ORDER BY COUNT(*) DESC;
END;
$$ LANGUAGE plpgsql;

-- submitted candidate rows (multi-table JOIN)
CREATE OR REPLACE FUNCTION get_submitted_candidates(row_limit INT DEFAULT 300)
RETURNS TABLE (
    candidate_id TEXT,
    expression_hash TEXT,
    canonical_expression TEXT,
    template_id TEXT,
    family TEXT,
    fields_json JSONB,
    params_json JSONB,
    settings_json JSONB,
    run_id TEXT,
    alpha_id TEXT,
    submitted_at TIMESTAMPTZ,
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    submit_eligible BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.candidate_id, c.expression_hash, c.canonical_expression,
        c.template_id, c.family, c.fields_json, c.params_json, c.settings_json,
        r.run_id, r.alpha_id, s.submitted_at,
        m.sharpe, m.fitness, m.turnover, m.submit_eligible
    FROM submissions s
    JOIN runs r ON s.run_id = r.run_id
    JOIN candidates c ON s.candidate_id = c.candidate_id
    LEFT JOIN metrics m ON r.run_id = m.run_id
    WHERE s.submission_status IN ('submitted', 'confirmed')
    ORDER BY s.submitted_at DESC
    LIMIT row_limit;
END;
$$ LANGUAGE plpgsql;

-- eligible candidates (multi-table JOIN)
CREATE OR REPLACE FUNCTION get_eligible_candidates(row_limit INT DEFAULT 50)
RETURNS TABLE (
    candidate_id TEXT,
    expression_hash TEXT,
    canonical_expression TEXT,
    template_id TEXT,
    family TEXT,
    fields_json JSONB,
    params_json JSONB,
    settings_json JSONB,
    run_id TEXT,
    alpha_id TEXT,
    completed_at TIMESTAMPTZ,
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    submit_eligible BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.candidate_id, c.expression_hash, c.canonical_expression,
        c.template_id, c.family, c.fields_json, c.params_json, c.settings_json,
        r.run_id, r.alpha_id, r.completed_at,
        m.sharpe, m.fitness, m.turnover, m.submit_eligible
    FROM runs r
    JOIN candidates c ON r.candidate_id = c.candidate_id
    JOIN metrics m ON r.run_id = m.run_id
    WHERE r.status = 'completed'
      AND m.submit_eligible = true
      AND r.alpha_id IS NOT NULL
    ORDER BY r.completed_at DESC
    LIMIT row_limit;
END;
$$ LANGUAGE plpgsql;

-- similarity reference candidates
CREATE OR REPLACE FUNCTION get_reference_candidates(row_limit INT, min_s REAL, min_f REAL)
RETURNS TABLE (
    candidate_id TEXT,
    expression_hash TEXT,
    canonical_expression TEXT,
    template_id TEXT,
    family TEXT,
    fields_json JSONB,
    params_json JSONB,
    settings_json JSONB,
    run_id TEXT,
    alpha_id TEXT,
    completed_at TIMESTAMPTZ,
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    submit_eligible BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.candidate_id, c.expression_hash, c.canonical_expression,
        c.template_id, c.family, c.fields_json, c.params_json, c.settings_json,
        r.run_id, r.alpha_id, r.completed_at,
        m.sharpe, m.fitness, m.turnover, m.submit_eligible
    FROM runs r
    JOIN candidates c ON r.candidate_id = c.candidate_id
    JOIN metrics m ON r.run_id = m.run_id
    WHERE r.status = 'completed'
      AND m.sharpe IS NOT NULL AND m.fitness IS NOT NULL
      AND m.sharpe >= min_s AND m.fitness >= min_f
    ORDER BY r.completed_at DESC
    LIMIT row_limit;
END;
$$ LANGUAGE plpgsql;

-- settings performance stats (universe, neutralization, decay, truncation)
CREATE OR REPLACE FUNCTION get_settings_stats(run_limit INT DEFAULT 500)
RETURNS TABLE (
    dimension TEXT,
    setting_value TEXT,
    n_runs BIGINT,
    avg_sharpe REAL,
    avg_fitness REAL,
    submit_rate REAL
) AS $$
BEGIN
    RETURN QUERY
    WITH recent AS (
        SELECT r.run_id, r.candidate_id
        FROM runs r
        WHERE r.status = 'completed'
        ORDER BY r.completed_at DESC
        LIMIT run_limit
    )
    SELECT 'universe'::TEXT AS dimension,
           (c.settings_json->>'universe')::TEXT AS setting_value,
           COUNT(*)::BIGINT AS n_runs,
           AVG(m.sharpe)::REAL AS avg_sharpe,
           AVG(m.fitness)::REAL AS avg_fitness,
           AVG(CASE WHEN m.submit_eligible THEN 1.0 ELSE 0.0 END)::REAL AS submit_rate
    FROM recent rec
    JOIN candidates c ON rec.candidate_id = c.candidate_id
    JOIN metrics m ON rec.run_id = m.run_id
    GROUP BY c.settings_json->>'universe'

    UNION ALL

    SELECT 'neutralization'::TEXT,
           (c.settings_json->>'neutralization')::TEXT,
           COUNT(*)::BIGINT,
           AVG(m.sharpe)::REAL,
           AVG(m.fitness)::REAL,
           AVG(CASE WHEN m.submit_eligible THEN 1.0 ELSE 0.0 END)::REAL
    FROM recent rec
    JOIN candidates c ON rec.candidate_id = c.candidate_id
    JOIN metrics m ON rec.run_id = m.run_id
    GROUP BY c.settings_json->>'neutralization'

    UNION ALL

    SELECT 'decay'::TEXT,
           (c.settings_json->>'decay')::TEXT,
           COUNT(*)::BIGINT,
           AVG(m.sharpe)::REAL,
           AVG(m.fitness)::REAL,
           AVG(CASE WHEN m.submit_eligible THEN 1.0 ELSE 0.0 END)::REAL
    FROM recent rec
    JOIN candidates c ON rec.candidate_id = c.candidate_id
    JOIN metrics m ON rec.run_id = m.run_id
    GROUP BY c.settings_json->>'decay'

    UNION ALL

    SELECT 'truncation'::TEXT,
           (c.settings_json->>'truncation')::TEXT,
           COUNT(*)::BIGINT,
           AVG(m.sharpe)::REAL,
           AVG(m.fitness)::REAL,
           AVG(CASE WHEN m.submit_eligible THEN 1.0 ELSE 0.0 END)::REAL
    FROM recent rec
    JOIN candidates c ON rec.candidate_id = c.candidate_id
    JOIN metrics m ON rec.run_id = m.run_id
    GROUP BY c.settings_json->>'truncation';
END;
$$ LANGUAGE plpgsql;

-- review queue for manual submission decisions (merged performance mode)
CREATE TABLE IF NOT EXISTS review_queue (
    id SERIAL PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    expression TEXT NOT NULL,
    core_signal TEXT,
    family TEXT,
    template_id TEXT,
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    settings_json TEXT,
    status TEXT DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    owner TEXT DEFAULT 'owner'
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
