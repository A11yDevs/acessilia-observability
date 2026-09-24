# Implementation plan

The kit monitors one Agno project per installation. AgentOS supplies component and session data through its HTTP API. An optional Alloy collector beside the application sends telemetry to Prometheus, Loki, Tempo and, when configured, Langfuse. The panel reads those services; the monitored application does not import panel code or share its filesystem.

## Current progress

| Phase | Implemented | Validation still needed |
| --- | --- | --- |
| 1. Real AgentOS connection | Configurable API adapter, project settings and connection guide | Connect a real Agno 3.x AgentOS instance with persisted runs and authentication |
| 2. Application instrumentation | Optional Agno/OpenTelemetry setup, OTLP trace, metric and log export, local receiver test | Verify spans from an actual Agno run in another application |
| 3. Remote deployment | Separate Compose stacks, private interface binds, SSH access guide, connection checks | Exercise two machines or isolated networks with private routing, failure and restart behavior |
| 4. Panel and Grafana | Source states, bounded history and log filters, session runs, trace links and provisioned dashboard | Check real telemetry, partial outages and AgentOS response variations |
| 5. Optional Langfuse | Separate services, Alloy fan-out, credentials outside generated files, smoke command and synthetic outage check | Use real project keys and confirm the same Agno run in Tempo and Langfuse |

The local OTLP and Alloy tests use synthetic signals. They confirm exporter wiring and failure isolation but do not prove a deployment against a live AgentOS or Langfuse project.

## 1. Prepare and validate a real AgentOS connection

**Current state:** `config.py` already accepts the AgentOS URL, project identity and private network addresses. The panel discovers components through `/info` and `/config`, falling back to list endpoints. The README now gives a short two-machine connection procedure. The API client has been exercised with simulated AgentOS responses, and the collector with synthetic OTLP traffic; there is no available live Agno application for this phase.

**When an application is available:**

1. Configure the private addresses and credentials using the README procedure. Verify network reachability in both directions.
2. Check `/api/entities` and `/api/sessions` through the panel. Record the Agno version and any actual response differences; adapt only the affected API adapter.
3. Run one agent, then confirm its session and run appear when AgentOS persistence is enabled. Send one metric, log and trace through the collector and confirm each destination receives it.
4. Repeat with AgentOS authentication enabled and with the observability server on another machine.

**Done when:** a real Agno 3.x AgentOS instance is discovered, a persisted run is readable, and each enabled signal reaches its backend across the private network. This phase cannot be declared complete from mocks; it requires a live application, access credentials and a working private connection.

## 2. Add reusable application instrumentation

**Goal:** a monitored Agno application can opt into telemetry without copying panel code or deploying the server stack on its host.

1. Add a small, optional application-side integration under `src/agno_observability_kit/instrumentation/`. Keep Agno, OpenInference and OpenTelemetry exporter packages out of the base server dependencies; install them only in the monitored application.
2. Provide one startup recipe that configures an OTLP HTTP trace exporter to the nearby Alloy collector and instruments Agno before agent runs begin. Make `service.name`, project and environment explicit. Provide an application example that runs without this repository's frontend or server.
3. Document the distinction between AgentOS database tracing and external OTLP export. Agno tracing setup is process-wide; the recipe must define who owns the tracer provider and avoid silently replacing an existing provider. [Agno's tracing guide](https://docs.agno.com/tracing/overview) describes this behavior.
4. Provide an opt-in pattern for structured application logs and low-cardinality metrics. Carry `trace_id` and `span_id` into logs, and attach `run_id` and `session_id` when the application has them. Do not make run or session IDs metric labels. Document that traces may include prompts or responses, so the application owner chooses what to export.
5. Test the integration with a local OTLP receiver or collector and assert that a sample run emits a trace with its service identity. Test missing optional dependencies and an existing tracer provider without requiring model API calls.

**Done when:** another Agno project can add the optional package, call a documented setup function at startup and see one trace, one log and one metric in the corresponding backends. No project-specific module or model provider is required.

## 3. Make remote deployment safe and repeatable

**Goal:** the application and observability server communicate across a private network without publishing ingestion or administrative APIs to the internet.

1. Document one supported deployment path using private IPs from Tailscale or WireGuard. Explain which direction each connection travels: panel to AgentOS; collector to Prometheus, Loki, Tempo and optional Langfuse; application to its local collector.
2. Keep the panel and Grafana bound to loopback by default. For remote viewing, document SSH tunnels first. If direct browser access is required, provide an optional reverse-proxy example with TLS and user authentication; do not add a second custom login system to the panel.
3. Add a concise connectivity check covering AgentOS discovery, collector reachability and the configured backend endpoints. Report wrong bind addresses, DNS failures, unauthorized AgentOS access and missing Langfuse credentials separately.
4. Document a minimum firewall policy: only the monitored hosts can reach ingestion ports on the private interface; only the observability server can reach the AgentOS administrative API. Keep credentials in ignored `.env` files, never in `config.py` or browser responses.
5. Exercise Compose configuration and an end-to-end transfer between separate hosts or network namespaces, including failure and restart behavior.

**Done when:** a fresh pair of machines can follow the guide, pass the connectivity check and receive telemetry while no ingestion port is exposed on a public interface. An authenticated reverse proxy is required only if the panel is opened beyond loopback or an SSH tunnel.

## 4. Expand the generic panel and Grafana views

**Goal:** the panel answers whether telemetry is arriving, what changed over time and which run produced a problem.

1. Add a status view for AgentOS, Prometheus, Loki, Tempo, the collector's last received signal and optional Langfuse. Distinguish “not configured,” “no data yet” and “unavailable.”
2. Add bounded Prometheus range queries and a small time-series view for request volume, error rate and latency when those metrics exist. Keep custom PromQL in `config.py` and show an empty state when an application does not emit a metric.
3. Add time range, text and level filters for Loki logs. Escape user input and bound query ranges and result counts. Show timestamps and trace IDs where present.
4. Use the existing session-runs API in the UI. Show run status, timing and identifiers from AgentOS; link to a Tempo/Grafana trace only when a matching trace ID exists. Do not assume all Agno responses contain identical fields.
5. Provision a small Grafana dashboard with project and environment filters and links across metrics, logs and traces. Use standard telemetry fields; avoid application-specific agent names or query expressions.
6. Verify loading, empty, partial outage and unauthorized states; test keyboard access and narrow screens.

**Done when:** a user can select a time range, inspect a persisted run, find its related logs and open its trace when correlation data exists. The UI still works when only the AgentOS API is connected. Agent execution and chat controls remain outside this read-only panel.

## 5. Finish optional Langfuse integration

**Goal:** users who enable Langfuse see the same Agno trace in Tempo and Langfuse; users who leave it disabled run no Langfuse services or exporter.

1. Keep Langfuse in its own optional Compose file. Document both self-hosted and existing Langfuse endpoints, project key creation, private routing, storage and resource requirements.
2. Validate the Alloy trace fan-out and Basic authentication using real Langfuse project keys. Confirm one Agno run appears in Tempo and in the matching Langfuse project. Check that a Langfuse outage does not interrupt Tempo export, and document the retry and loss limits.
3. Show Langfuse connection state and a project link in the panel only when configured. Add a trace deep link only if the installed Langfuse version exposes a stable URL for that trace.
4. Check credential rotation and failure messages. Keep keys in the collector's ignored `.env`; never return them from panel APIs or write them to generated Alloy files.

**Done when:** enabling Langfuse requires only its URL and project keys, one run is visible in both tracing systems, and disabling it removes the exporter without changing the core stack.

## Order and release checks

Implement phase 2 first so phases 4 and 5 have real telemetry. Complete phase 3 before treating a deployment between machines as production-ready. Build phase 4 against the existing adapters, then validate phase 5 with real keys. Run phase 1's live checks as soon as an application is available, and feed any Agno API differences back into the adapter. Each phase should land in small, English-language commits with no application-specific names or secrets.
