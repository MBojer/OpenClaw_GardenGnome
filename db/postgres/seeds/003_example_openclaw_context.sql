-- Optional example / dev rows. Installer: GARDENGNOME_DB_APPLY_SEEDS=auto (default) applies when sender_profiles is empty;
-- 1 = always; 0 = never. Manual: psql "$GARDENGNOME_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/postgres/seeds/003_example_openclaw_context.sql
-- Equivalent to: python3 scripts/constrained_llm_pipeline.py seed-examples

BEGIN;

INSERT INTO sender_profiles (sender_id, channel, display_name, timezone, language)
VALUES ('self', 'default', 'Owner', 'UTC', 'en')
ON CONFLICT (sender_id, channel) DO NOTHING;

INSERT INTO routing_rules (id, pattern_type, pattern_value, target_agent, priority, channel_filter)
VALUES
  ('b1111111-1111-4111-8111-111111111101'::uuid,
   'keyword', 'status', 'gardengnome', 100, NULL)
ON CONFLICT (id) DO NOTHING;

INSERT INTO agent_tool_index (tool_name, plugin, description_short, example_invocation, tags)
VALUES
  ('memory_get', 'openclaw',
   'Read workspace memory file', 'memory_get path=MEMORY.md',
   ARRAY['memory']::text[])
ON CONFLICT (tool_name, plugin) DO NOTHING;

INSERT INTO schema_migrations (id) VALUES ('003_example_openclaw_context') ON CONFLICT DO NOTHING;

COMMIT;
