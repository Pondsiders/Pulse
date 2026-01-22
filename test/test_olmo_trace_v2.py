#!/usr/bin/env python3
"""OLMo trace test v2 - Adding Pulse-like complexity.

Building on v1 which worked, now adding:
1. BatchSpanProcessor instead of SimpleSpanProcessor
2. Module-level tracer (like Pulse does)
3. Logging integration

Run with: uv run python test/test_olmo_trace_v2.py
"""

import os
import time
import logging
import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # Changed from Simple
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://primer:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "olmo-3:7b-instruct")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alpha-pi:4318")

# Module-level tracer (like Pulse)
_tracer: trace.Tracer | None = None

def init_otel():
    """Initialize OTel - Pulse style."""
    global _tracer

    resource = Resource.create({
        SERVICE_NAME: "olmo-test-v2",
    })

    provider = TracerProvider(resource=resource)

    # BatchSpanProcessor like Pulse uses
    exporter = OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("olmo-test-v2")

    print(f"OTel initialized: {OTEL_ENDPOINT}/v1/traces")


def get_tracer() -> trace.Tracer:
    """Get tracer - Pulse style."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer("olmo-test-v2")
    return _tracer


def call_olmo(prompt: str) -> str:
    """Call OLMo with full gen_ai instrumentation."""
    tracer = get_tracer()

    with tracer.start_as_current_span(
        name=f"llm.{OLLAMA_MODEL}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        # THE CRITICAL ATTRIBUTES for Parallax routing
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", OLLAMA_MODEL)
        span.set_attribute("gen_ai.operation.name", "generate")

        # OpenInference attributes (what Phoenix expects)
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", OLLAMA_MODEL)
        span.set_attribute("input.value", prompt)

        # Test marker
        span.set_attribute("test.marker", "olmo-trace-test-v2")
        span.set_attribute("test.timestamp", time.time())

        print(f"Span: trace_id={span.get_span_context().trace_id:032x}, span_id={span.get_span_context().span_id:016x}")

        try:
            response = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()

            output = result.get("response", "").strip()

            span.set_attribute("output.value", output[:500] if len(output) > 500 else output)
            if "eval_count" in result:
                span.set_attribute("gen_ai.usage.output_tokens", result["eval_count"])
            if "prompt_eval_count" in result:
                span.set_attribute("gen_ai.usage.input_tokens", result["prompt_eval_count"])

            span.set_status(Status(StatusCode.OK))
            print(f"Response: {output[:100]}...")
            return output

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def main():
    print("=" * 60)
    print("OLMo Trace Test v2 (BatchSpanProcessor + module tracer)")
    print("=" * 60)

    init_otel()
    print()

    print("Calling OLMo...")
    call_olmo("What's 2 + 2? Answer briefly.")
    print()

    # Force flush with BatchSpanProcessor
    print("Flushing spans (BatchSpanProcessor needs this)...")
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush(timeout_millis=5000)
    print("Done! Check Phoenix for test.marker='olmo-trace-test-v2'")


if __name__ == "__main__":
    main()
