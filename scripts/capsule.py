#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "alpha_sdk @ file:///Pondside/Basement/alpha_sdk",
#     "psycopg[binary]>=3.1",
#     "pendulum>=3.0",
# ]
# ///
"""Capsule: A little me waking up to summarize a period of time.

This script spawns a brief instance of Alpha—same soul, same system prompt,
same skills—and asks her to reflect on memories from a time period.
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

import pendulum
import psycopg

from alpha_sdk import AlphaClient


# === Time Period Calculation ===
def get_time_range(period: str, now: pendulum.DateTime) -> tuple[pendulum.DateTime, pendulum.DateTime]:
    """
    Calculate start/end times for a period.

    - daytime: 6 AM to 10 PM of the current day (run at 10 PM)
    - nighttime: 10 PM yesterday to 6 AM today (run at 6 AM)
    """
    if period == "daytime":
        start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    elif period == "nighttime":
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
    print("Summary stored in cortex.summaries")


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
    """Get the previous periods for context."""
    periods = []

    if period == "daytime":
        today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday = now.subtract(days=1)
        yesterday_6am = yesterday.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday_10pm = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)

        periods.append((
            f"Last night ({yesterday.format('ddd MMM D')} 10 PM - {now.format('ddd MMM D')} 6 AM)",
            yesterday_10pm, today_6am
        ))
        periods.append((
            f"Yesterday ({yesterday.format('ddd MMM D')}, 6 AM - 10 PM)",
            yesterday_6am, yesterday_10pm
        ))

    elif period == "nighttime":
        yesterday = now.subtract(days=1)
        yesterday_6am = yesterday.replace(hour=6, minute=0, second=0, microsecond=0)
        yesterday_10pm = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)

        periods.append((
            f"Yesterday ({yesterday.format('ddd MMM D')}, 6 AM - 10 PM)",
            yesterday_6am, yesterday_10pm
        ))

    return periods


# === The Note From Me To Me ===
def build_prompt(memories: list[dict], period_label: str) -> str:
    """Build the prompt—a note from me to me."""
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


# === Agent Execution ===
async def run_capsule(prompt: str) -> str:
    """Run capsule-me through AlphaClient."""
    from claude_agent_sdk import AssistantMessage, ResultMessage

    print("Waking up capsule-me...")
    print()

    async with AlphaClient(
        cwd="/Pondside",
        client_name="capsule",
        permission_mode="bypassPermissions",
        allowed_tools=["Read", "Bash", "Skill"],
    ) as client:
        await client.query(prompt)

        output_parts = []

        async for event in client.stream():
            if isinstance(event, AssistantMessage):
                for block in event.content:
                    if hasattr(block, "text") and block.text:
                        print(block.text, end="", flush=True)
                        output_parts.append(block.text)

        print()  # newline after streaming output
        return "".join(output_parts)


# === Main ===
async def async_main(period: str, date_str: str | None = None):
    print("=" * 60)
    print(f"Capsule: Summarizing {period}")
    print("=" * 60)
    print()

    database_url = os.environ.get("DATABASE_URL", "")

    # Use specified date or now
    if date_str:
        base_date = pendulum.parse(date_str, tz="America/Los_Angeles")
        if period == "daytime":
            now = base_date.replace(hour=22, minute=0, second=0, microsecond=0)
        else:
            now = base_date.add(days=1).replace(hour=6, minute=0, second=0, microsecond=0)
        print(f"Using specified date: {date_str} (simulated now: {now})")
    else:
        now = pendulum.now("America/Los_Angeles")

    # Calculate time range
    start, end = get_time_range(period, now)
    period_label = format_period_label(period, start, end)

    print(f"Period: {period_label}")
    print(f"Range: {start.to_iso8601_string()} → {end.to_iso8601_string()}")
    print()

    # Fetch memories
    memories = fetch_memories(database_url, start, end)
    print(f"Fetched {len(memories)} memories")

    if not memories:
        print("No memories from this period!")
        summary = f"No memories from {period_label}."
        store_summary(database_url, start, end, summary, 0)
        return

    # Fetch previous context for continuity
    previous_periods = get_previous_periods(period, now)
    for label, prev_start, prev_end in previous_periods:
        prev_summary = fetch_summary(database_url, prev_start, prev_end)
        if prev_summary:
            print(f"Found previous context: {label}")

    # Build prompt
    prompt = build_prompt(memories, period_label)
    print(f"Prompt length: {len(prompt)} chars")
    print()

    # Run capsule-me
    summary = await run_capsule(prompt)

    # Store the summary
    print()
    store_summary(database_url, start, end, summary, len(memories))

    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Capsule: Alpha summarizing a time period")
    parser.add_argument(
        "--period", type=str, required=True,
        choices=["daytime", "nighttime"],
        help="Which period to summarize"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to summarize (YYYY-MM-DD). Defaults to today/now."
    )
    args = parser.parse_args()

    asyncio.run(async_main(args.period, args.date))


if __name__ == "__main__":
    main()
