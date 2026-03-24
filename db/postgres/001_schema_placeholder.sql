-- GardenGnome placeholder schema (PostgreSQL).
-- Applied by install/setup_db.sh when GARDENGNOME_DATABASE_URL is set,
-- connectivity succeeds, and GARDENGNOME_DB_APPLY_SCHEMA=1.
-- Safe to re-run: uses IF NOT EXISTS where practical.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    id         TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS garden_beds (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS plants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bed_id      UUID REFERENCES garden_beds (id) ON DELETE SET NULL,
    common_name TEXT NOT NULL,
    variety     TEXT,
    planted_on  DATE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS care_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plant_id    UUID NOT NULL REFERENCES plants (id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    event_date  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plants_bed_id ON plants (bed_id);
CREATE INDEX IF NOT EXISTS idx_care_events_plant_id ON care_events (plant_id);
CREATE INDEX IF NOT EXISTS idx_care_events_event_date ON care_events (event_date);

-- Example seed row (optional narrative for the agent)
INSERT INTO garden_beds (name, notes)
SELECT 'Example bed',
       'Placeholder row from installer; delete or edit as needed.'
WHERE NOT EXISTS (SELECT 1 FROM garden_beds LIMIT 1);

INSERT INTO schema_migrations (id) VALUES ('001_schema_placeholder') ON CONFLICT DO NOTHING;

COMMIT;
