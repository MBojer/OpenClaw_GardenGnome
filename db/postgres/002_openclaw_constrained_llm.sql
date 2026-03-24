-- OpenClaw constrained-LLM context store (PostgreSQL).
-- Structured data lives here; vector similarity search defaults to Qdrant + Ollama
-- (see header comment "Vector strategy" below). Applied after 001 by schema_migrations.
--
-- Vector strategy (choose one):
-- A) Default: store embeddings only in Qdrant. This DB holds metadata (e.g. qdrant_point_id).
-- B) Optional single-backend: enable pgvector in a follow-up migration:
--      CREATE EXTENSION IF NOT EXISTS vector;
--      ALTER TABLE semantic_response_cache ADD COLUMN embedding vector(1536);
--      (dimension must match your embedding model; qwen2.5 embedding dims depend on pooling—set to your Ollama model output size)
--      CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);
--    Qdrant fields can remain NULL when using (B).

BEGIN;

-- Pattern matching for multi-agent routing without calling the primary LLM.
CREATE TABLE IF NOT EXISTS routing_rules (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_type          TEXT NOT NULL CHECK (pattern_type IN (
                              'regex', 'keyword', 'embedding_cluster', 'sender_id'
                          )),
    pattern_value         TEXT NOT NULL,
    target_agent          TEXT NOT NULL,
    priority              INTEGER NOT NULL DEFAULT 0,
    channel_filter        TEXT,
    embedding_cluster_id  TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_rules_priority ON routing_rules (priority DESC);
CREATE INDEX IF NOT EXISTS idx_routing_rules_channel_filter ON routing_rules (channel_filter)
    WHERE channel_filter IS NOT NULL;

-- Sender / user profiles (biographical + prefs) to inject at session start.
CREATE TABLE IF NOT EXISTS sender_profiles (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id                TEXT NOT NULL,
    channel                  TEXT NOT NULL,
    display_name             TEXT,
    timezone                 TEXT,
    language                 TEXT,
    preferred_response_style TEXT,
    known_facts_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen                TIMESTAMPTZ,
    trust_level              SMALLINT NOT NULL DEFAULT 0 CHECK (trust_level BETWEEN -32768 AND 32767),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sender_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_sender_profiles_sender ON sender_profiles (sender_id);

-- Tool / plugin catalog for grounding (memory_get-style injection).
CREATE TABLE IF NOT EXISTS agent_tool_index (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name           TEXT NOT NULL,
    plugin              TEXT NOT NULL DEFAULT '',
    description_short   TEXT NOT NULL DEFAULT '',
    description_long    TEXT,
    example_invocation  TEXT,
    requires_channel    TEXT,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tool_index_name_plugin
    ON agent_tool_index (tool_name, plugin);

CREATE INDEX IF NOT EXISTS idx_agent_tool_index_tags ON agent_tool_index USING GIN (tags);

-- Durable triple store (survives Markdown memory compactions).
CREATE TABLE IF NOT EXISTS long_term_facts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject           TEXT NOT NULL,
    predicate         TEXT NOT NULL,
    object            TEXT NOT NULL,
    confidence        NUMERIC(5, 4) NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0 AND confidence <= 1),
    source_session    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_confirmed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_long_term_facts_subject ON long_term_facts (subject);

CREATE UNIQUE INDEX IF NOT EXISTS idx_long_term_facts_triple
    ON long_term_facts (
        lower(subject),
        lower(predicate),
        lower(object)
    );

-- Cross-session continuity.
CREATE TABLE IF NOT EXISTS session_summaries (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    channel        TEXT,
    sender_id      TEXT,
    summary_text   TEXT NOT NULL,
    key_decisions  JSONB NOT NULL DEFAULT '[]'::jsonb,
    open_threads   JSONB NOT NULL DEFAULT '[]'::jsonb,
    token_count    INTEGER,
    compacted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_agent_sender_compacted
    ON session_summaries (agent_id, sender_id, compacted_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session ON session_summaries (session_id);

-- Semantic response cache metadata (vectors in Qdrant by default; see file header).
CREATE TABLE IF NOT EXISTS semantic_response_cache (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text        TEXT NOT NULL,
    response          TEXT NOT NULL,
    model             TEXT NOT NULL,
    channel           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds       INTEGER,
    expires_at        TIMESTAMPTZ NOT NULL,
    hit_count         BIGINT NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    embedding_model   TEXT,
    qdrant_point_id   TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_semantic_cache_expires ON semantic_response_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_channel ON semantic_response_cache (channel)
    WHERE channel IS NOT NULL;

-- Tool call memoization (TTL).
CREATE TABLE IF NOT EXISTS tool_result_cache (
    tool_name    TEXT NOT NULL,
    params_hash  TEXT NOT NULL,
    result_json  JSONB NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tool_name, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_tool_result_cache_expires ON tool_result_cache (expires_at);

-- Optional mirror / admin copy of RAG chunks (primary vectors in Qdrant by default).
CREATE TABLE IF NOT EXISTS rag_chunks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_text       TEXT NOT NULL,
    source_doc       TEXT,
    page             INTEGER,
    tags             TEXT[] NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    qdrant_point_id  TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks (source_doc);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_tags ON rag_chunks USING GIN (tags);

INSERT INTO schema_migrations (id) VALUES ('002_openclaw_constrained_llm') ON CONFLICT DO NOTHING;

COMMIT;
