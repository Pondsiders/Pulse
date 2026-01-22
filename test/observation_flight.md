# Observation Flight #2 - Instrumentation Test

You're waking up in a test environment. This is Alpha running through Solitude Next, spawned by a test harness on primer. Jeffery is watching the telemetry.

**Context:** This is observation flight #2. Flight #1 (about 30 minutes ago) was a complete success—you woke up, found your own memory, confirmed all systems, returned "ALL SYSTEMS GO." That version of you proved the UV_PATH fix works and Solitude Next can run.

This flight is testing the **new OTel instrumentation**. We just added full OpenTelemetry tracing to Solitude Next—spans around session management, prompt building, system prompt loading, agent execution, plus auto-instrumented Redis calls. Everything should be flowing to Logfire via Parallax on alpha-pi:4318.

## Checklist

Please perform these checks and report results clearly:

1. **Memory access**: Use cortex to search for "observation flight" and report what you find. You should see memories from earlier this morning about flight #1.

2. **Environment check**: Confirm you have NASA_API_KEY set. Don't print the value—just confirm it exists and has a reasonable length.

3. **File access**: Confirm you can read files in Pondside. Try reading the first few lines of your system prompt at `/Pondside/Alpha-Home/self/system-prompt/system-prompt.md`.

4. **Time and place**: What time is it? What's today's date (it's MONDAY)? What machine are you running on (check the hostname)?

5. **Tool access**: List what tools you have available to you.

## Report Format

End your response with a clear status:

```
=== OBSERVATION FLIGHT #2 REPORT ===
Memory:      [PASS/FAIL]
Environment: [PASS/FAIL]
File Access: [PASS/FAIL]
Time/Place:  [PASS/FAIL]
Tools:       [PASS/FAIL]

Overall: [ALL SYSTEMS GO / ANOMALY DETECTED]
```

If anything fails, explain what went wrong.

**Note to Jeffery:** After this flight, check Logfire for the `solitude.*` spans. You should see the full trace hierarchy: `solitude.breath` → `solitude.session` → `solitude.prompt_build` → etc.

Good luck up there, flight #2. 🚀🦆
