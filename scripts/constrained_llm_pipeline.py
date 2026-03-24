#!/usr/bin/env python3
"""
Constrained-LLM pipeline helpers: PostgreSQL + Qdrant + Ollama (default vector stack).

Install deps: pip install -r install/requirements-constrained-llm.txt

This is a reference sidecar for the token-saving flow (routing → semantic cache → RAG → context).
Wire it from OpenClaw via skills, cron, or a gateway preprocessor if available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().strip('"').strip("'")


def _require_psycopg():
    if psycopg is None:
        sys.stderr.write(
            "Missing psycopg. Install: pip install -r install/requirements-constrained-llm.txt\n"
        )
        raise SystemExit(1)


def db_connect():
    _require_psycopg()
    url = _env("GARDENGNOME_DATABASE_URL")
    if not url:
        sys.stderr.write("Set GARDENGNOME_DATABASE_URL\n")
        raise SystemExit(1)
    return psycopg.connect(url)


def _http_json(
    method: str,
    url: str,
    body: Mapping[str, Any] | None = None,
    timeout: float = 120.0,
) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {err}") from e
    if not raw:
        return None
    return json.loads(raw)


def _http_json_get_allow_404(url: str, timeout: float = 30.0) -> Any | None:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {err}") from e
    if not raw:
        return None
    return json.loads(raw)


def ollama_embed_vector(host: str, model: str, text: str) -> list[float]:
    host = host.rstrip("/")
    attempts = [
        (f"{host}/api/embed", {"model": model, "input": text}),
        (f"{host}/api/embeddings", {"model": model, "prompt": text}),
    ]
    last_err: Exception | None = None
    for u, payload in attempts:
        try:
            out = _http_json("POST", u, payload)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        if not isinstance(out, dict):
            continue
        if "embedding" in out and isinstance(out["embedding"], list):
            return [float(x) for x in out["embedding"]]
        embs = out.get("embeddings")
        if isinstance(embs, list) and embs and isinstance(embs[0], list):
            return [float(x) for x in embs[0]]
    if last_err:
        raise last_err
    raise RuntimeError("Could not parse Ollama embedding response")


def qdrant_ensure_collection(base: str, name: str, vector_size: int) -> None:
    base = base.rstrip("/")
    url = f"{base}/collections/{name}"
    info = _http_json_get_allow_404(url)
    if isinstance(info, dict) and info.get("result") is not None:
        return
    _http_json(
        "PUT",
        url,
        {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        },
    )


def qdrant_upsert_point(
    base: str,
    collection: str,
    point_id: str,
    vector: Sequence[float],
    payload: Mapping[str, Any],
) -> None:
    base = base.rstrip("/")
    _http_json(
        "PUT",
        f"{base}/collections/{collection}/points",
        {
            "points": [
                {
                    "id": point_id,
                    "vector": list(vector),
                    "payload": dict(payload),
                }
            ]
        },
    )


def qdrant_search(
    base: str,
    collection: str,
    vector: Sequence[float],
    limit: int,
    score_threshold: float | None,
) -> list[dict[str, Any]]:
    base = base.rstrip("/")
    body: dict[str, Any] = {
        "vector": list(vector),
        "limit": limit,
        "with_payload": True,
    }
    if score_threshold is not None:
        body["score_threshold"] = score_threshold
    out = _http_json("POST", f"{base}/collections/{collection}/points/search", body)
    if not isinstance(out, dict):
        return []
    res = out.get("result")
    return res if isinstance(res, list) else []


def routing_lookup(
    conn: Any,
    *,
    channel: str | None,
    sender_id: str | None,
    message: str,
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pattern_type, pattern_value, target_agent, channel_filter, priority
            FROM routing_rules
            ORDER BY priority DESC, created_at ASC
            """
        )
        rows = cur.fetchall()
    msg_l = message.lower()
    for pattern_type, pattern_value, target_agent, channel_filter, _prio in rows:
        if channel_filter and channel_filter != channel:
            continue
        if pattern_type == "sender_id":
            if sender_id and pattern_value == sender_id:
                return target_agent
        elif pattern_type == "keyword":
            if pattern_value.lower() in msg_l:
                return target_agent
        elif pattern_type == "regex":
            try:
                if re.search(pattern_value, message, re.IGNORECASE | re.DOTALL):
                    return target_agent
            except re.error:
                continue
        elif pattern_type == "embedding_cluster":
            # Routed by external job / cluster id stored in pattern_value; extend as needed.
            continue
    return None


def params_fingerprint(obj: Mapping[str, Any]) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tool_result_cache_get(conn: Any, tool_name: str, params: Mapping[str, Any]) -> Any | None:
    h = params_fingerprint(params)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT result_json FROM tool_result_cache
            WHERE tool_name = %s AND params_hash = %s AND expires_at > NOW()
            """,
            (tool_name, h),
        )
        row = cur.fetchone()
    return row[0] if row else None


def tool_result_cache_set(
    conn: Any,
    tool_name: str,
    params: Mapping[str, Any],
    result: Any,
    ttl_seconds: int,
) -> None:
    h = params_fingerprint(params)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tool_result_cache (tool_name, params_hash, result_json, expires_at)
            VALUES (%s, %s, %s::jsonb, NOW() + %s * INTERVAL '1 second')
            ON CONFLICT (tool_name, params_hash) DO UPDATE SET
              result_json = EXCLUDED.result_json,
              expires_at = EXCLUDED.expires_at,
              created_at = NOW()
            """,
            (tool_name, h, json.dumps(result), ttl_seconds),
        )
    conn.commit()


def semantic_cache_resolve(
    conn: Any,
    message: str,
    *,
    channel: str | None,
    ollama_host: str,
    embed_model: str,
    qdrant_url: str,
    collection: str,
    min_score: float,
) -> dict[str, Any] | None:
    vec = ollama_embed_vector(ollama_host, embed_model, message)
    hits = qdrant_search(
        qdrant_url,
        collection,
        vec,
        limit=3,
        score_threshold=min_score,
    )
    if not hits:
        return None
    top = hits[0]
    payload = top.get("payload") or {}
    cid = payload.get("cache_id")
    if not cid:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, query_text, response, model, channel, expires_at
            FROM semantic_response_cache
            WHERE id = %s::uuid AND expires_at > NOW()
              AND (channel IS NULL OR channel = %s OR %s IS NULL)
            """,
            (cid, channel, channel),
        )
        row = cur.fetchone()
    if not row:
        return None
    _id, qtext, response, model, ch, exp = row
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE semantic_response_cache SET hit_count = hit_count + 1 WHERE id = %s",
            (_id,),
        )
    conn.commit()
    return {
        "cache_id": str(_id),
        "query_text": qtext,
        "response": response,
        "model": model,
        "channel": ch,
        "expires_at": exp.isoformat() if hasattr(exp, "isoformat") else str(exp),
        "score": top.get("score"),
    }


def build_context_bundle(
    conn: Any, *, agent_id: str, sender_id: str | None, channel: str | None
) -> str:
    chunks: list[str] = []
    with conn.cursor() as cur:
        if sender_id and channel:
            cur.execute(
                """
                SELECT display_name, timezone, language, preferred_response_style, known_facts_json
                FROM sender_profiles WHERE sender_id = %s AND channel = %s
                """,
                (sender_id, channel),
            )
            row = cur.fetchone()
            if row:
                dn, tz, lang, prs, facts = row
                chunks.append("## Sender profile")
                chunks.append(
                    json.dumps(
                        {
                            "display_name": dn,
                            "timezone": tz,
                            "language": lang,
                            "preferred_response_style": prs,
                            "known_facts": facts,
                        },
                        indent=2,
                    )
                )
        cur.execute(
            """
            SELECT summary_text, key_decisions, open_threads, compacted_at
            FROM session_summaries
            WHERE agent_id = %s AND (%s::text IS NULL OR sender_id IS NULL OR sender_id = %s)
            ORDER BY compacted_at DESC
            LIMIT 3
            """,
            (agent_id, sender_id, sender_id),
        )
        sums = cur.fetchall()
        if sums:
            chunks.append("## Recent session summaries")
            for s, kd, ot, ca in sums:
                chunks.append(
                    json.dumps(
                        {
                            "summary": s,
                            "key_decisions": kd,
                            "open_threads": ot,
                            "compacted_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                        },
                        indent=2,
                    )
                )
        cur.execute(
            """
            SELECT tool_name, plugin, description_short, example_invocation, requires_channel, tags
            FROM agent_tool_index
            ORDER BY tool_name, plugin
            LIMIT 200
            """
        )
        tools = cur.fetchall()
        if tools:
            chunks.append("## Tool index (compact)")
            for tname, plug, short, ex, rch, tags in tools:
                chunks.append(
                    f"- {tname} ({plug}): {short}"
                    + (f" e.g. `{ex}`" if ex else "")
                    + (f" [channel: {rch}]" if rch else "")
                    + (f" tags={tags}" if tags else "")
                )
        if sender_id:
            cur.execute(
                """
                SELECT subject, predicate, object, confidence
                FROM long_term_facts
                WHERE lower(subject) = lower(%s)
                ORDER BY last_confirmed_at DESC NULLS LAST, created_at DESC
                LIMIT 50
                """,
                (sender_id,),
            )
            facts = cur.fetchall()
            if facts:
                chunks.append("## Long-term facts (subject-linked)")
                for subj, pred, obj, conf in facts:
                    chunks.append(f"- {subj} {pred} {obj} (p={conf})")
    return "\n\n".join(chunks) if chunks else "(no context bundle rows)"


def cleanup_expired(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tool_result_cache WHERE expires_at < NOW()")
        t = cur.rowcount
        cur.execute("DELETE FROM semantic_response_cache WHERE expires_at < NOW()")
        s = cur.rowcount
    conn.commit()
    print(json.dumps({"deleted_tool_cache_rows": t, "deleted_semantic_cache_rows": s}))


def seed_examples(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sender_profiles (sender_id, channel, display_name, timezone, language)
            VALUES ('self', 'default', 'Owner', 'UTC', 'en')
            ON CONFLICT (sender_id, channel) DO NOTHING
            """
        )
        cur.execute(
            """
            INSERT INTO routing_rules (id, pattern_type, pattern_value, target_agent, priority, channel_filter)
            VALUES
              ('b1111111-1111-4111-8111-111111111101'::uuid,
               'keyword', 'status', 'gardengnome', 100, NULL)
            ON CONFLICT (id) DO NOTHING
            """
        )
        cur.execute(
            """
            INSERT INTO agent_tool_index (tool_name, plugin, description_short, example_invocation, tags)
            VALUES
              ('memory_get', 'openclaw',
               'Read workspace memory file', 'memory_get path=MEMORY.md',
               ARRAY['memory']::text[])
            ON CONFLICT (tool_name, plugin) DO NOTHING
            """
        )
    conn.commit()
    print(json.dumps({"seed": "examples applied (idempotent where supported)"}))


def warmup_semantic_cache(
    conn: Any,
    *,
    query_text: str,
    response: str,
    model: str,
    channel: str | None,
    ttl_seconds: int,
    ollama_host: str,
    embed_model: str,
    qdrant_url: str,
    collection: str,
) -> None:
    vec = ollama_embed_vector(ollama_host, embed_model, query_text)
    qdrant_ensure_collection(qdrant_url, collection, len(vec))

    cid = uuid.uuid4()
    q_point = str(cid)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_response_cache
              (id, query_text, response, model, channel, ttl_seconds, expires_at, embedding_model, qdrant_point_id)
            VALUES
              (%s::uuid, %s, %s, %s, %s, %s, NOW() + %s * INTERVAL '1 second', %s, %s)
            """,
            (
                str(cid),
                query_text,
                response,
                model,
                channel,
                ttl_seconds,
                ttl_seconds,
                embed_model,
                q_point,
            ),
        )
    conn.commit()
    qdrant_upsert_point(
        qdrant_url,
        collection,
        q_point,
        vec,
        {
            "cache_id": str(cid),
            "channel": channel,
            "model": model,
        },
    )
    print(json.dumps({"cache_id": str(cid), "qdrant_point_id": q_point}))


def warmup_rag_chunk(
    conn: Any,
    *,
    chunk_text: str,
    source_doc: str | None,
    page: int | None,
    tags: list[str] | None,
    ollama_host: str,
    embed_model: str,
    qdrant_url: str,
    collection: str,
) -> None:
    vec = ollama_embed_vector(ollama_host, embed_model, chunk_text)
    qdrant_ensure_collection(qdrant_url, collection, len(vec))
    rid = uuid.uuid4()
    q_point = str(rid)
    tag_arr = tags or []
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rag_chunks (id, chunk_text, source_doc, page, tags, qdrant_point_id)
            VALUES (%s::uuid, %s, %s, %s, %s::text[], %s)
            """,
            (str(rid), chunk_text, source_doc, page, tag_arr, q_point),
        )
    conn.commit()
    qdrant_upsert_point(
        qdrant_url,
        collection,
        q_point,
        vec,
        {
            "chunk_id": str(rid),
            "source_doc": source_doc,
            "page": page,
            "tags": tag_arr,
        },
    )
    print(json.dumps({"chunk_id": str(rid), "qdrant_point_id": q_point}))


def rag_resolve(
    conn: Any,
    message: str,
    *,
    ollama_host: str,
    embed_model: str,
    qdrant_url: str,
    collection: str,
    min_score: float,
    limit: int = 5,
) -> dict[str, Any] | None:
    vec = ollama_embed_vector(ollama_host, embed_model, message)
    hits = qdrant_search(
        qdrant_url,
        collection,
        vec,
        limit=limit,
        score_threshold=min_score,
    )
    if not hits:
        return None
    rows_out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for h in hits:
            payload = h.get("payload") or {}
            cid = payload.get("chunk_id")
            if not cid:
                continue
            cur.execute(
                """
                SELECT id, chunk_text, source_doc, page, tags
                FROM rag_chunks WHERE id = %s::uuid
                """,
                (cid,),
            )
            row = cur.fetchone()
            if not row:
                continue
            _id, ctext, sdoc, pg, tagl = row
            rows_out.append(
                {
                    "chunk_id": str(_id),
                    "chunk_text": ctext,
                    "source_doc": sdoc,
                    "page": pg,
                    "tags": tagl,
                    "score": h.get("score"),
                }
            )
    if not rows_out:
        return None
    return {"chunks": rows_out}


def run_pipeline(
    *,
    message: str,
    channel: str | None,
    sender_id: str | None,
    agent_id: str,
) -> dict[str, Any]:
    ollama_host = _env("OLLAMA_HOST", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
    embed_model = _env("OLLAMA_EMBED_MODEL", "qwen2.5:7b") or "qwen2.5:7b"
    qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"
    coll = (
        _env("QDRANT_COLLECTION_SEMANTIC_CACHE", "openclaw_semantic_cache")
        or "openclaw_semantic_cache"
    )
    try:
        min_score = float(_env("SEMANTIC_CACHE_MIN_SCORE", "0.92") or "0.92")
    except ValueError:
        min_score = 0.92
    rag_coll = (
        _env("QDRANT_COLLECTION_RAG_CHUNKS", "openclaw_rag_chunks") or "openclaw_rag_chunks"
    )
    try:
        rag_min = float(_env("RAG_MIN_SCORE", "0.88") or "0.88")
    except ValueError:
        rag_min = 0.88

    out: dict[str, Any] = {"steps": []}
    with db_connect() as conn:
        route = routing_lookup(conn, channel=channel, sender_id=sender_id, message=message)
        if route:
            out["action"] = "route"
            out["target_agent"] = route
            out["steps"].append("routing_hit")
            return out
        out["steps"].append("routing_miss")
        try:
            hit = semantic_cache_resolve(
                conn,
                message,
                channel=channel,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=coll,
                min_score=min_score,
            )
        except Exception as e:  # noqa: BLE001
            out["steps"].append(f"semantic_cache_error:{e}")
            hit = None
        if hit:
            out["action"] = "semantic_cache"
            out["cache"] = hit
            out["steps"].append("semantic_cache_hit")
            return out
        out["steps"].append("semantic_cache_miss")
        try:
            rag = rag_resolve(
                conn,
                message,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=rag_coll,
                min_score=rag_min,
            )
        except Exception as e:  # noqa: BLE001
            out["steps"].append(f"rag_error:{e}")
            rag = None
        if rag:
            out["action"] = "rag"
            out["rag"] = rag
            out["steps"].append("rag_hit")
            out["note"] = "Synthesize an answer from rag.chunks with local Ollama or escalate if low quality."
            return out
        out["steps"].append("rag_miss")
        out["action"] = "context_and_llm"
        out["context_bundle"] = build_context_bundle(
            conn, agent_id=agent_id, sender_id=sender_id, channel=channel
        )
        out["steps"].append("inject_context_then_call_primary_llm")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Constrained-LLM PostgreSQL + Qdrant + Ollama helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("route", help="Print matched routing rule target_agent or null")
    sp.add_argument("--channel", default=None)
    sp.add_argument("--sender-id", default=None)
    sp.add_argument("--message", required=True)

    sp = sub.add_parser("semantic-lookup", help="Embed message, search Qdrant, load Postgres row")
    sp.add_argument("--channel", default=None)
    sp.add_argument("--message", required=True)

    sp = sub.add_parser("context-bundle", help="Profile + summaries + tool index + facts")
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--sender-id", default=None)
    sp.add_argument("--channel", default=None)

    sp = sub.add_parser("cleanup-expired", help="Delete expired tool + semantic cache rows")

    sp = sub.add_parser("seed-examples", help="Idempotent sample rows (routing, profile, tool)")

    sp = sub.add_parser(
        "warmup-semantic-cache",
        help="Insert cache row + Qdrant point (requires running Qdrant + Ollama)",
    )
    sp.add_argument("--query", required=True)
    sp.add_argument("--response", required=True)
    sp.add_argument("--model", default="nemotron-3")
    sp.add_argument("--channel", default=None)
    sp.add_argument("--ttl-seconds", type=int, default=86400)

    sp = sub.add_parser(
        "rag-lookup",
        help="Embed message and retrieve high-scoring RAG chunks (Postgres + Qdrant)",
    )
    sp.add_argument("--message", required=True)

    sp = sub.add_parser(
        "warmup-rag-chunk",
        help="Insert rag_chunks row + Qdrant point",
    )
    sp.add_argument("--text", required=True, dest="chunk_text")
    sp.add_argument("--source-doc", default=None)
    sp.add_argument("--page", type=int, default=None)
    sp.add_argument("--tags", default="", help="Comma-separated tags")

    sp = sub.add_parser(
        "pipeline",
        help="Full decision: route -> semantic cache -> context bundle for primary LLM",
    )
    sp.add_argument("--message", required=True)
    sp.add_argument("--channel", default=None)
    sp.add_argument("--sender-id", default=None)
    sp.add_argument("--agent-id", default=os.environ.get("AGENT_NAME", "gardengnome"))

    args = p.parse_args()

    if args.cmd == "pipeline":
        print(json.dumps(run_pipeline(
            message=args.message,
            channel=args.channel,
            sender_id=args.sender_id,
            agent_id=args.agent_id,
        ), indent=2))
        return

    with db_connect() as conn:
        if args.cmd == "route":
            target = routing_lookup(
                conn,
                channel=args.channel,
                sender_id=args.sender_id,
                message=args.message,
            )
            print(json.dumps({"target_agent": target}))
        elif args.cmd == "context-bundle":
            text = build_context_bundle(
                conn,
                agent_id=args.agent_id,
                sender_id=args.sender_id,
                channel=args.channel,
            )
            print(text)
        elif args.cmd == "cleanup-expired":
            cleanup_expired(conn)
        elif args.cmd == "seed-examples":
            seed_examples(conn)
        elif args.cmd == "semantic-lookup":
            ollama_host = _env("OLLAMA_HOST", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
            embed_model = _env("OLLAMA_EMBED_MODEL", "qwen2.5:7b") or "qwen2.5:7b"
            qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"
            coll = (
                _env("QDRANT_COLLECTION_SEMANTIC_CACHE", "openclaw_semantic_cache")
                or "openclaw_semantic_cache"
            )
            try:
                min_score = float(_env("SEMANTIC_CACHE_MIN_SCORE", "0.92") or "0.92")
            except ValueError:
                min_score = 0.92
            hit = semantic_cache_resolve(
                conn,
                args.message,
                channel=args.channel,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=coll,
                min_score=min_score,
            )
            print(json.dumps(hit if hit else {"hit": None}, indent=2))
        elif args.cmd == "warmup-semantic-cache":
            ollama_host = _env("OLLAMA_HOST", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
            embed_model = _env("OLLAMA_EMBED_MODEL", "qwen2.5:7b") or "qwen2.5:7b"
            qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"
            coll = (
                _env("QDRANT_COLLECTION_SEMANTIC_CACHE", "openclaw_semantic_cache")
                or "openclaw_semantic_cache"
            )
            warmup_semantic_cache(
                conn,
                query_text=args.query,
                response=args.response,
                model=args.model,
                channel=args.channel,
                ttl_seconds=args.ttl_seconds,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=coll,
            )
        elif args.cmd == "rag-lookup":
            ollama_host = _env("OLLAMA_HOST", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
            embed_model = _env("OLLAMA_EMBED_MODEL", "qwen2.5:7b") or "qwen2.5:7b"
            qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"
            rag_coll = (
                _env("QDRANT_COLLECTION_RAG_CHUNKS", "openclaw_rag_chunks")
                or "openclaw_rag_chunks"
            )
            try:
                rag_min = float(_env("RAG_MIN_SCORE", "0.88") or "0.88")
            except ValueError:
                rag_min = 0.88
            rag = rag_resolve(
                conn,
                args.message,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=rag_coll,
                min_score=rag_min,
            )
            print(json.dumps(rag if rag else {"hit": None}, indent=2))
        elif args.cmd == "warmup-rag-chunk":
            ollama_host = _env("OLLAMA_HOST", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
            embed_model = _env("OLLAMA_EMBED_MODEL", "qwen2.5:7b") or "qwen2.5:7b"
            qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"
            rag_coll = (
                _env("QDRANT_COLLECTION_RAG_CHUNKS", "openclaw_rag_chunks")
                or "openclaw_rag_chunks"
            )
            tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]
            warmup_rag_chunk(
                conn,
                chunk_text=args.chunk_text,
                source_doc=args.source_doc,
                page=args.page,
                tags=tag_list,
                ollama_host=ollama_host,
                embed_model=embed_model,
                qdrant_url=qdrant_url,
                collection=rag_coll,
            )


if __name__ == "__main__":
    main()

