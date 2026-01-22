#!/usr/bin/env python3
"""OLMo trace test v4 - Adding nested spans.

Building on v3, now adding:
1. Nested spans like the HUD job: parent_span → llm_span

Run with: uv run python test/test_olmo_trace_v4.py
"""

import os
import time
from contextlib import contextmanager
from typing import Generator

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://primer:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "olmo-3:7b-instruct")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alpha-pi:4318")

# Module-level tracer
_tracer: trace.Tracer | None = None


def init_otel():
    """Initialize OTel."""
    global _tracer

    resource = Resource.create({
        SERVICE_NAME: "olmo-test-v4",
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("olmo-test-v4")

    print(f"OTel initialized: {OTEL_ENDPOINT}/v1/traces")


def get_tracer() -> trace.Tracer:
    """Get tracer."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer("olmo-test-v4")
    return _tracer


@contextmanager
def llm_span(
    model: str,
    prompt: str,
    operation: str = "generate",
) -> Generator[trace.Span, None, None]:
    """Context manager for LLM spans."""
    tracer = get_tracer()

    with tracer.start_as_current_span(
        name=f"llm.{model}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", model)
        span.set_attribute("input.value", prompt[:500])
        span.set_attribute("test.marker", "olmo-trace-test-v4")

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def call_olmo(prompt: str) -> str:
    """Call OLMo using the llm_span context manager."""
    with llm_span(OLLAMA_MODEL, prompt) as span:
        print(f"  LLM Span: trace_id={span.get_span_context().trace_id:032x}, span_id={span.get_span_context().span_id:016x}")

        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        output = result.get("response", "").strip()

        span.set_attribute("output.value", output[:500])
        if "eval_count" in result:
            span.set_attribute("gen_ai.usage.output_tokens", result["eval_count"])

        print(f"  Response: {output[:50]}...")
        return output


def run_job():
    """Simulate the HUD job structure with nested spans."""
    tracer = get_tracer()

    # Outer span: like pulse.job.hud
    with tracer.start_as_current_span("test.job.hud") as job_span:
        job_span.set_attribute("test.marker", "olmo-trace-test-v4-job")
        print(f"Job Span: trace_id={job_span.get_span_context().trace_id:032x}, span_id={job_span.get_span_context().span_id:016x}")

        # Middle span: like hud.generate_summaries
        with tracer.start_as_current_span("test.generate_summaries") as summary_span:
            summary_span.set_attribute("summary_count", 1)
            print(f"  Summary Span: span_id={summary_span.get_span_context().span_id:016x}")

            # Inner span: the LLM call
            call_olmo("Name a random color. One word only.")


def main():
    print("=" * 60)
    print("OLMo Trace Test v4 (nested spans)")
    print("=" * 60)

    init_otel()
    print()

    print("Running simulated HUD job with nested spans...")
    run_job()
    print()

    print("Flushing spans...")
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush(timeout_millis=5000)
    print("Done! Check Phoenix for test.marker='olmo-trace-test-v4'")


if __name__ == "__main__":
    main()
