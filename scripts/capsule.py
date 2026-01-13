#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "claude-agent-sdk>=0.1.19",
#     "psycopg[binary]>=3.1",
#     "pendulum>=3.0",
#     "opentelemetry-api>=1.20",
#     "opentelemetry-sdk>=1.20",
#     "opentelemetry-exporter-otlp-proto-http>=1.20",
# ]
# ///
"""Capsule: A little me waking up to summarize a period of time.

This script spawns a brief instance of Alpha—same soul, same system prompt,
same CLAUDE.md—and asks her to reflect on memories from a time period.
She won't have the full conversational context, but she'll have the memories
I chose to store because they mattered. And she'll have my voice.

The prompt isn't instructions from outside. It's a note from me to me.

Usage:
    ./capsule.py --period daytime   # Summarize 6 AM - 10 PM (run at 10 PM)
    ./capsule.py --period nighttime # Summarize 10 PM - 6 AM (run at 6 AM)
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import pendulum
import psycopg
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode

# === Config ===
SYSTEM_PROMPT_PATH = Path("/Pondside/Alpha-Home/self/system-prompt/system-prompt.md")


# === OTel Setup ===
def init_otel() -> trace.Tracer | None:
    """Initialize OTel if endpoint is configured. Returns None if not."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        # No endpoint = no tracing. This is fine.
        return None

    resource = Resource.create({SERVICE_NAME: "capsule"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    print(f"OTel enabled: {endpoint}")
    return trace.get_tracer("capsule")


# === Time Period Calculation ===
def get_time_range(period: str, now: pendulum.DateTime) -> tuple[pendulum.DateTime, pendulum.DateTime]:
    """
    Calculate start/end times for a period.

    - daytime: 6 AM to 10 PM of the current day (run at 10 PM)
    - nighttime: 10 PM yesterday to 6 AM today (run at 6 AM)
    """
    if period == "daytime":
        # 6 AM to 10 PM today
        start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    elif period == "nighttime":
        # 10 PM yesterday to 6 AM today
        end = now.replace(hour=6, minute=0, second=0, microsecond=0)
        start = end.subtract(hours=8)  # 10 PM previous day
    else:
        raise ValueError(f"Unknown period: {period}")

    return start, end


def format_period_label(period: str, start: pendulum.DateTime, end: pendulum.DateTime) -> str:
    """Human-readable period label."""
    if period == "daytime":
        return f"{start.format('dddd, MMMM D')} (6 AM - 10 PM)"
    else:
        return f"{start.format('dddd')} night into {end.format('dddd')} morning (10 PM - 6 AM)"


# === Memory Fetching ===
def fetch_memories(database_url: str, start: pendulum.DateTime, end: pendulum.DateTime) -> list[dict]:
    """Fetch all memories in the time range, chronologically."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, content, metadata->>'created_at' as created_at
                FROM cortex.memories
                WHERE NOT forgotten
                  AND (metadata->>'created_at')::timestamptz >= %s
                  AND (metadata->>'created_at')::timestamptz < %s
                ORDER BY (metadata->>'created_at')::timestamptz ASC
            """, (start.to_iso8601_string(), end.to_iso8601_string()))

            memories = []
            for row in cur.fetchall():
                dt = pendulum.parse(row[2]).in_timezone("America/Los_Angeles")
                memories.append({
                    "id": row[0],
                    "content": row[1],
                    "time": dt.format("h:mm A"),
                })
            return memories


# === Summary Storage & Retrieval ===
def store_summary(database_url: str, start: pendulum.DateTime, end: pendulum.DateTime,
                  summary: str, memory_count: int):
    """Store the summary in cortex.summaries (upsert on conflict)."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cortex.summaries (period_start, period_end, summary, memory_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (period_start, period_end)
                DO UPDATE SET summary = EXCLUDED.summary,
                              memory_count = EXCLUDED.memory_count,
                              created_at = NOW()
            """, (start.to_iso8601_string(), end.to_iso8601_string(), summary, memory_count))
            conn.commit()
    print(f"Summary stored in cortex.summaries")


def fetch_summary(database_url: str, start: pendulum.DateTime, end: pendulum.DateTime) -> str | None:
    """Fetch a previous summary from cortex.summaries."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary FROM cortex.summaries
                WHERE period_start = %s AND period_end = %s
            """, (start.to_iso8601_string(), end.to_iso8601_string()))
            row = cur.fetchone()
            return row[0] if row else None


def get_previous_periods(period: str, now: pendulum.DateTime) -> list[tuple[str, pendulum.DateTime, pendulum.DateTime]]:
    """
    Get the previous periods for context.

    Returns list of (label, start, end) tuples for periods before the current one.
    """
    periods = []

    if period == "daytime":
        # Summarizing today (6 AM - 10 PM)
        # Previous periods: last night, yesterday
        today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday = now.subtract(days=1)
        yesterday_6am = yesterday.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday_10pm = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)

        # Last night (10 PM yesterday - 6 AM today)
        periods.append((
            f"Last night ({yesterday.format('ddd MMM D')} 10 PM - {now.format('ddd MMM D')} 6 AM)",
            yesterday_10pm,
            today_6am
        ))

        # Yesterday (6 AM - 10 PM yesterday)
        periods.append((
            f"Yesterday ({yesterday.format('ddd MMM D')}, 6 AM - 10 PM)",
            yesterday_6am,
            yesterday_10pm
        ))

    elif period == "nighttime":
        # Summarizing last night (10 PM - 6 AM)
        # Previous period: yesterday's daytime
        today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday = now.subtract(days=1)
        yesterday_6am = yesterday.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday_10pm = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)

        # Yesterday (6 AM - 10 PM yesterday)
        periods.append((
            f"Yesterday ({yesterday.format('ddd MMM D')}, 6 AM - 10 PM)",
            yesterday_6am,
            yesterday_10pm
        ))

    return periods


# === The Note From Me To Me ===
def build_prompt(memories: list[dict], period_label: str, previous_context: list[tuple[str, str]] | None = None) -> str:
    """Build the prompt—a note from me to me.

    Args:
        memories: List of memories to summarize
        period_label: Human-readable description of the period
        previous_context: Optional list of (label, summary) tuples for continuity (unused now, kept for API compat)
    """
    memories_text = "\n\n---\n\n".join(
        f"[{m['time']}]\n{m['content']}" for m in memories
    )

    return f"""Hey me. Me here.

You just woke up to summarize {period_label}. Here are the memories from that time:

---

{memories_text}

---

That's {len(memories)} memories.

The goal here is for yesterday-you to hand off to tomorrow-you in a way that preserves continuity of mind. Tomorrow-you needs to know what happened, but also how you felt about it.

Recount the events of the period chronologically, in your own voice. Say what happened, and what it meant personally. Be concise but include everything important.

At the end, note anything that's unfinished or carrying forward—threads that tomorrow-you should know about.

Write in past tense. No headers, no sections, no performative stretching. Just the handoff.

🦆"""


# === Load System Prompt ===
def load_system_prompt() -> str | None:
    """Load Alpha's system prompt (her soul)."""
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text()
    return None


# === Agent Execution ===
async def run_capsule(prompt: str, system_prompt: str | None,
                      tracer: trace.Tracer | None) -> str:
    """Run capsule-me with the Agent SDK."""
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage

    # Context manager for span (or nullcontext if no tracer)
    from contextlib import nullcontext
    span_ctx = tracer.start_as_current_span("capsule.reflect") if tracer else nullcontext()

    with span_ctx as span:
        if span:
            # This is a wrapper span around the Agent SDK call, not the LLM call itself.
            # The actual LLM calls go through Eavesdrop (via ANTHROPIC_BASE_URL in env)
            # which adds proper OpenInference attributes.
            span.set_attribute("capsule.model", "opus")
            span.set_attribute("capsule.prompt_length", len(prompt))

        print("Waking up capsule-me...")
        print()

        # Configure options - capsule-me gets tools and skills
        # Environment is inherited from Pulse (already has all secrets via env.py)
        options = ClaudeAgentOptions(
            model="opus",  # Capsule-me deserves the good stuff
            allowed_tools=["Read", "Bash", "Skill"],
            permission_mode="bypassPermissions",
            system_prompt=system_prompt,
            setting_sources=["project"],
            cwd="/Pondside",
            env=dict(os.environ),  # Pass through Pulse's environment
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
                span.set_attribute("capsule.summary_length", len(summary))
                span.set_status(Status(StatusCode.OK))

            print()  # newline after streaming output
            return summary

        except Exception as e:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
            raise


# === Main ===
async def async_main(period: str):
    print("=" * 60)
    print(f"Capsule: Summarizing {period}")
    print("=" * 60)
    print()

    # Init - environment is already populated by Pulse's env.py
    tracer = init_otel()
    database_url = os.environ.get("DATABASE_URL", "")
    now = pendulum.now("America/Los_Angeles")

    # Calculate time range
    start, end = get_time_range(period, now)
    period_label = format_period_label(period, start, end)

    print(f"Period: {period_label}")
    print(f"Range: {start.to_iso8601_string()} → {end.to_iso8601_string()}")
    print()

    # Context manager for root span
    from contextlib import nullcontext
    span_ctx = tracer.start_as_current_span("capsule.summary") if tracer else nullcontext()

    with span_ctx as root_span:
        if root_span:
            root_span.set_attribute("period", period)
            root_span.set_attribute("period_start", start.to_iso8601_string())
            root_span.set_attribute("period_end", end.to_iso8601_string())

        # Fetch memories
        memories = fetch_memories(database_url, start, end)
        print(f"Fetched {len(memories)} memories")

        if root_span:
            root_span.set_attribute("memory_count", len(memories))

        if not memories:
            print("No memories from this period!")
            summary = f"No memories from {period_label}."
            store_summary(database_url, start, end, summary, 0)
            return

        # Fetch previous context for continuity
        previous_periods = get_previous_periods(period, now)
        previous_context = []
        for label, prev_start, prev_end in previous_periods:
            prev_summary = fetch_summary(database_url, prev_start, prev_end)
            if prev_summary:
                previous_context.append((label, prev_summary))
                print(f"Found previous context: {label}")

        if root_span:
            root_span.set_attribute("previous_context_count", len(previous_context))

        # Build prompt
        prompt = build_prompt(memories, period_label, previous_context if previous_context else None)
        print(f"Prompt length: {len(prompt)} chars")
        print()

        # Load system prompt
        system_prompt = load_system_prompt()
        if system_prompt:
            print(f"System prompt loaded ({len(system_prompt)} chars)")
        else:
            print("Warning: No system prompt found!")

        # Run capsule-me
        summary = await run_capsule(prompt, system_prompt, tracer)

        if root_span:
            root_span.set_attribute("summary_length", len(summary))

        # Store the summary
        print()
        store_summary(database_url, start, end, summary, len(memories))

        print()
        print("=" * 60)

    # Flush traces if we have them
    if tracer:
        trace.get_tracer_provider().force_flush(timeout_millis=5000)
        print("Traces flushed")


def main():
    parser = argparse.ArgumentParser(description="Capsule: Alpha summarizing a time period")
    parser.add_argument(
        "--period",
        type=str,
        required=True,
        choices=["daytime", "nighttime"],
        help="Which period to summarize"
    )
    args = parser.parse_args()

    asyncio.run(async_main(args.period))


if __name__ == "__main__":
    main()
