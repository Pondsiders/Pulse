#!/usr/bin/env python3
"""OLMo trace test v3 - Adding the llm_span context manager.

Building on v2, now adding:
1. The llm_span() context manager pattern (like summaries.py uses)

Run with: uv run python test/test_olmo_trace_v3.py
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
        SERVICE_NAME: "olmo-test-v3",
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("olmo-test-v3")

    print(f"OTel initialized: {OTEL_ENDPOINT}/v1/traces")


def get_tracer() -> trace.Tracer:
    """Get tracer."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer("olmo-test-v3")
    return _tracer


@contextmanager
def llm_span(
    model: str,
    prompt: str,
    operation: str = "generate",
) -> Generator[trace.Span, None, None]:
    """Context manager for LLM spans - EXACTLY like summaries.py."""
    tracer = get_tracer()

    with tracer.start_as_current_span(
        name=f"llm.{model}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        # gen_ai attributes for Parallax routing
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.operation.name", operation)

        # OpenInference attributes
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", model)

        # Input
        input_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
        span.set_attribute("input.value", input_preview)

        # Test marker
        span.set_attribute("test.marker", "olmo-trace-test-v3")

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
        print(f"Span: trace_id={span.get_span_context().trace_id:032x}, span_id={span.get_span_context().span_id:016x}")

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

        print(f"Response: {output[:100]}...")
        return output


def main():
    print("=" * 60)
    print("OLMo Trace Test v3 (llm_span context manager)")
    print("=" * 60)

    init_otel()
    print()

    print("Calling OLMo via llm_span()...")
    call_olmo("What color is the sky? One word answer.")
    print()

    print("Flushing spans...")
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush(timeout_millis=5000)
    print("Done! Check Phoenix for test.marker='olmo-trace-test-v3'")


if __name__ == "__main__":
    main()
