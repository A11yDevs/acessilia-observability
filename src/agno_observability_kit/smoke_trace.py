"""Send a model-free trace, log and metric through the application collector."""

from __future__ import annotations

import argparse
import logging
import sys

from config import CONFIG
from agno_observability_kit.instrumentation.agno import configure_agno_telemetry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector-url", default="http://127.0.0.1:4318")
    args = parser.parse_args()

    telemetry = configure_agno_telemetry(
        service_name="observability-smoke",
        project_id=CONFIG.project_id,
        environment=CONFIG.environment,
        collector_url=args.collector_url,
        loggers=("observability.smoke",),
    )
    from opentelemetry import trace
    logger = logging.getLogger("observability.smoke")
    logger.setLevel(logging.INFO)
    with trace.get_tracer("observability.smoke").start_as_current_span("observability-smoke") as span:
        trace_id = f"{span.get_span_context().trace_id:032x}"
        span.set_attribute("run_id", "observability-smoke")
        logger.info("Observability smoke trace", extra={"run_id": "observability-smoke"})
        telemetry.record_run(component_type="agent", status="ok", duration_seconds=0.001)
    if not telemetry.flush():
        print("The collector did not confirm every signal; check its address and logs.", file=sys.stderr)
        return 1
    print(f"Trace ID: {trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
