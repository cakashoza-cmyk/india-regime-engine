-- Postgres-native schema (SQLite uses the same file via db.py translation).
CREATE TABLE IF NOT EXISTS raw_ingest (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    indicator VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    release_date DATE,
    is_verified BOOLEAN DEFAULT FALSE,
    ok BOOLEAN DEFAULT TRUE              -- added: false = failed pull (error payload, no value)
);
CREATE TABLE IF NOT EXISTS indicators (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(40),                  -- added: pipeline run that wrote the row
    indicator VARCHAR(50) NOT NULL,
    dial VARCHAR(20) NOT NULL,
    value NUMERIC,
    prior_value NUMERIC,
    direction SMALLINT,
    score SMALLINT,
    weight SMALLINT DEFAULT 1,
    as_of DATE NOT NULL,
    is_stale BOOLEAN DEFAULT FALSE,      -- added: last good value carried forward
    stale_since TIMESTAMPTZ,
    source_raw_id BIGINT REFERENCES raw_ingest(id)
);
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(40),
    snapshot_date DATE NOT NULL,
    growth_score NUMERIC,
    inflation_score NUMERIC,
    liquidity_score NUMERIC,
    vote_score NUMERIC,
    fragility_score NUMERIC,
    regime_label VARCHAR(30),
    sub_label VARCHAR(30),
    stage SMALLINT,
    tier1_flips SMALLINT,
    tier2_confirmed BOOLEAN,
    gap_description TEXT,
    sizing_recommendation TEXT,
    invalidation_conditions JSONB,
    detail JSONB,                        -- added: dial labels, sleeve, sectors, alerts
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS flip_levels (
    indicator VARCHAR(50) PRIMARY KEY,
    current_value NUMERIC,
    flip_level NUMERIC,
    flip_direction VARCHAR(10),
    is_flipped BOOLEAN DEFAULT FALSE,
    tier SMALLINT,
    last_checked TIMESTAMPTZ
);
