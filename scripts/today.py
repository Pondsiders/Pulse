#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "claude-agent-sdk>=0.1.19",
#     "psycopg[binary]>=3.1",
#     "pendulum>=3.0",
#     "redis>=5.0",
#     "opentelemetry-api>=1.20",
#     "opentelemetry-sdk>=1.20",
#     "opentelemetry-exporter-otlp-proto-http>=1.20",
# ]
# ///
"""Today: Rolling summary of "today so far" for Alpha's continuous memory.

This script runs hourly during the day (7 AM - 9 PM) and generates a
summary of everything that's happened since 6 AM. The result is stashed
in Redis for the Loom to inject into the <past> section of Alpha's
system prompt.

The goal: bridge the gap between "context window" and "yesterday's capsule."
Without this, Alpha loses the morning by afternoon, and the afternoon by
evening. With this, she has a continuous sense of "today" even across
multiple compactions.

Usage:
    ./today.py           # Generate and store today summary
    ./today.py --dry-run # Show what would be stored, don't write to Redis
"""

import argparse
import asyncio
import os
from pathlib import Path

import pendulum
import psycopg
import redis
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode

# === Config ===
REDIS_URL = os.getenv("REDIS_URL", "redis://alpha-pi:6379")
REDIS_KEY = "systemprompt:past:today"
TTL_SECONDS = 65 * 60  # 65 minutes - matches other system prompt parts

SYSTEM_PROMPT_PATH = Path("/Pondside/Alpha-Home/self/system-prompt/system-prompt.md")
PACIFIC = "America/Los_Angeles"


# === OTel Setup ===
def init_otel() -> trace.Tracer | None:
    """Initialize OTel if endpoint is configured."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None

    resource = Resource.create({SERVICE_NAME: "today"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    print(f"OTel enabled: {endpoint}")
    return trace.get_tracer("today")


# === Memory Fetching ===
def fetch_memories_since(database_url: str, since: pendulum.DateTime) -> list[dict]:
    """Fetch all memories since the given time, chronologically."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, content, metadata->>'created_at' as created_at
                FROM cortex.memories
                WHERE NOT forgotten
                  AND (metadata->>'created_at')::timestamptz >= %s
                ORDER BY (metadata->>'created_at')::timestamptz ASC
            """, (since.to_iso8601_string(),))

            memories = []
            for row in cur.fetchall():
                dt = pendulum.parse(row[2]).in_timezone(PACIFIC)
                memories.append({
                    "id": row[0],
                    "content": row[1],
                    "time": dt.format("h:mm A"),
                })
            return memories


# === The Note From Me To Me ===
def build_prompt(memories: list[dict], now: pendulum.DateTime) -> str:
    """Build the prompt—a note from me to me about today so far."""
    memories_text = "\n\n---\n\n".join(
        f"[{m['time']}]\n{m['content']}" for m in memories
    )

    day_name = now.format("dddd, MMMM D")
    current_time = now.format("h:mm A")

    return f"""Hey me. Me here.

It's {current_time} on {day_name}. Here's everything you've stored since 6 AM today:

---

{memories_text}

---

That's {len(memories)} memories from today so far.

I need you to write a brief summary of today so far—what's happened, what the vibe is, what matters. This will be injected into your context on the next prompt, so future-you has a continuous sense of the day even if the context window has compacted.

Think of it like: if you woke up right now with no memory of today, what would you need to know to feel oriented? What's the shape of today?

Write in present tense where it makes sense ("today is..."), past tense for completed things. Keep it concise but include texture—not just facts, but how things feel. A paragraph or two, maybe three if it's been a full day.

No headers, no bullet points. Just the handoff.

🦆"""


# === Load System Prompt ===
def load_system_prompt() -> str | None:
    """Load Alpha's system prompt (her soul)."""
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text()
    return None


# === Agent Execution ===
async def run_today(prompt: str, system_prompt: str | None,
                    tracer: trace.Tracer | None) -> str:
    """Run today-me with the Agent SDK."""
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
    from contextlib import nullcontext

    span_ctx = tracer.start_as_current_span("today.summarize") if tracer else nullcontext()

    with span_ctx as span:
        if span:
            span.set_attribute("today.model", "opus")
            span.set_attribute("today.prompt_length", len(prompt))

        print("Waking up today-me...")
        print()

        options = ClaudeAgentOptions(
            model="opus",
            allowed_tools=[],  # No tools needed for summarization
            permission_mode="bypassPermissions",
            system_prompt=system_prompt,
            cwd="/Pondside",
            env=dict(os.environ),
        )

        output_parts = []

        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if hasattr(block, "text") and block.text:
                            print(block.text, end="", flush=True)
                            output_parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    if span:
                        span.set_attribute("agent.result", message.subtype)

            summary = "".join(output_parts)
            if span:
                span.set_attribute("today.summary_length", len(summary))
                span.set_status(Status(StatusCode.OK))

            print()
            return summary

        except Exception as e:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
            raise


# === Main ===
async def async_main(dry_run: bool = False):
    now = pendulum.now(PACIFIC)

    print("=" * 60)
    print(f"Today So Far: {now.format('ddd MMM D YYYY, h:mm A')}")
    print("=" * 60)
    print()

    tracer = init_otel()
    database_url = os.environ.get("DATABASE_URL", "")

    # Calculate start of day (6 AM today)
    start_of_day = now.replace(hour=6, minute=0, second=0, microsecond=0)

    # If it's before 6 AM, we're still in "last night" territory
    if now.hour < 6:
        print("It's before 6 AM—too early for today summary. Exiting.")
        return

    print(f"Fetching memories since {start_of_day.format('h:mm A')}...")

    # Fetch memories
    memories = fetch_memories_since(database_url, start_of_day)
    print(f"Found {len(memories)} memories")

    if not memories:
        summary = "Today just started—no memories stored yet."
        print(f"\n{summary}")
    else:
        # Build prompt
        prompt = build_prompt(memories, now)
        print(f"Prompt length: {len(prompt)} chars")
        print()

        # Load system prompt
        system_prompt = load_system_prompt()
        if system_prompt:
            print(f"System prompt loaded ({len(system_prompt)} chars)")
        else:
            print("Warning: No system prompt found!")

        # Run today-me
        summary = await run_today(prompt, system_prompt, tracer)

    # Add timestamp header
    header = f"**Today so far** ({now.format('h:mm A')}):\n\n"
    full_summary = header + summary

    print()
    print(f"Summary: {len(full_summary)} chars")

    if dry_run:
        print()
        print("=== DRY RUN - Would store: ===")
        print(f"Key: {REDIS_KEY}")
        print(f"TTL: {TTL_SECONDS // 60} minutes")
        print()
        print(full_summary)
        return

    # Store in Redis
    print()
    print("Storing in Redis...")
    r = redis.from_url(REDIS_URL)
    r.setex(REDIS_KEY, TTL_SECONDS, full_summary)
    print(f"  ✓ Stored at {REDIS_KEY} with {TTL_SECONDS // 60}-minute TTL")

    print()
    print("=" * 60)

    # Flush traces
    if tracer:
        trace.get_tracer_provider().force_flush(timeout_millis=5000)
        print("Traces flushed")


def main():
    parser = argparse.ArgumentParser(description="Today: rolling summary of today so far")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be stored without writing to Redis")
    args = parser.parse_args()

    asyncio.run(async_main(args.dry_run))


if __name__ == "__main__":
    main()
