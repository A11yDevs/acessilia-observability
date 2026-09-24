# Agno Observability Kit

A standalone, read-only observability server for an Agno AgentOS application. The observability server and the monitored application can run on different machines. The panel discovers agents, teams and workflows through the AgentOS API and reads persisted sessions and runs when AgentOS has a database. An optional Alloy process beside the application sends metrics, logs and traces to the observability server.

The kit monitors one project per installation. It does not import application code or require a shared Docker network or filesystem between the observability server and AgentOS.

`src/agno_observability_kit` contains configuration and service integrations. `frontend/` contains the panel and its assets. `infra/` groups the observability server, application collector, optional Langfuse services and performance tests. Project settings stay in the root `config.py`.

## Requirements

- Python 3.11 or newer to generate runtime configuration.
- Docker with Compose on the observability server, and on the monitored host if using the bundled Alloy service.
- Network access from the observability server to AgentOS. For remote ingestion, use a private network address reachable from the monitored host.
- An AgentOS instance exposing the Agno 3.x API. Persisted sessions require AgentOS database storage.

Install the Python package in a local environment before generating configuration:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Connect an AgentOS project

Use this checklist when an Agno application is available. The AgentOS API and the observability server can run on different machines. The example addresses below are private network addresses; replace them with your own.

1. Connect both machines through a private network. Confirm that the observability server can reach the application's AgentOS API, and that the application host can reach the observability server. Start the private network before Docker Compose.
2. On **both machines**, edit `config.py` with the same project settings:

   ```python
   project_id="my-project",
   project_name="My project",
   environment="production",
   agentos_url="http://100.64.0.20:7777",
   observability_bind_ip="100.64.0.10",
   observability_ingest_url="http://100.64.0.10",
   ```

   Here `100.64.0.10` is the observability server and `100.64.0.20` is the application host. `agentos_url` must work **inside the panel container**. Keep `collector_bind_ip="127.0.0.1"` when the application runs directly on its host. If the application runs in a container, set it to a private host interface that the application container can reach.
3. On the observability server, copy `.env.example` to `.env`. Set `GRAFANA_ADMIN_PASSWORD`, and set `AGENTOS_TOKEN` if AgentOS requires a bearer credential. Keep the AgentOS API reachable only over the private network.
4. On each machine, run `.venv/bin/python -m agno_observability_kit.configure`. On the observability server, start the [observability server](#start-the-observability-server). On the application host, start the [application collector](#start-the-application-collector).
5. On the observability server, check discovery with `curl -fsS http://127.0.0.1:8010/api/entities`. The response should list the registered agents, teams and workflows. Open `http://127.0.0.1:8010` to see the panel. For a remote browser, use an SSH tunnel to port `8010` rather than publishing the panel publicly.

An API connection supplies the component list. Sessions and runs require persistence in AgentOS. Metrics, logs and traces require the application to emit those signals to the collector; pointing `agentos_url` at the API does not export them. The planned application instrumentation and remote deployment work is tracked in [the implementation plan](docs/implementation-plan.md). Agno's current [API guide](https://docs.agno.com/agent-os/using-the-api) describes `/info` and `/config`; applications using a restricted public AgentOS surface may hide these administrative routes.

### Check a remote installation

After starting both Compose stacks, run the server check **inside the panel container** so it tests the same route and bearer credential as the panel:

```sh
docker compose -f infra/observability-server/compose.yaml --env-file .env --env-file infra/observability-server/.runtime.env exec -T panel python -m agno_observability_kit.check_connection server
```

On the application host, run the collector and ingestion reachability check from the kit checkout:

```sh
.venv/bin/python -m agno_observability_kit.check_connection application
```

The second command checks TCP reachability and, when Langfuse is enabled, whether both keys are set. It does not send a telemetry payload or verify backend authentication. The server check calls AgentOS `/info` and component discovery. A failed check names the missing URL, rejected AgentOS credential, DNS problem or unreachable port.

Keep ports `8010` (panel) and `3000` (Grafana) on the observability server's loopback address. From another computer, open them through SSH:

```sh
ssh -L 8010:127.0.0.1:8010 -L 3000:127.0.0.1:3000 user@observability-server
```

Then use `http://127.0.0.1:8010` and `http://127.0.0.1:3000` in that computer's browser. SSH provides the remote access control. If the panel must be published directly, put an authenticated HTTPS reverse proxy in front of it before changing the loopback bind.

Allow only these private-network connections in the host firewalls or network ACLs:

| Source | Destination | TCP ports | Purpose |
| --- | --- | --- | --- |
| Observability server | Application host | AgentOS port, usually `7777` | Read AgentOS metadata, sessions and runs |
| Application host | Observability server | `9090`, `3100`, `4318` | Send metrics, logs and traces |
| Application process or container | Alloy on application host | `4318` or `4317` | Send OTLP signals locally |
| Application host, if Langfuse is enabled | Langfuse endpoint | Endpoint port, usually `3001` or `443` | Send a copy of traces |

Bind the server ingestion ports to `observability_bind_ip`, a private interface address. Restrict the AgentOS administrative API to the observability server. Keep `.env` files on their respective machines; do not copy secrets into `config.py`.

## Configure the project

Edit [`config.py`](config.py). Set `project_id`, `project_name`, `environment` and `agentos_url`. The URL must be reachable **from inside the panel container**; `localhost` inside that container is not the monitored host. The panel uses `/info` and `/config` when available, then falls back to `/agents`, `/teams` and `/workflows`. Set `grafana_ui_url` to the URL your browser uses for Grafana when it differs from `http://localhost:3000`.

For remote ingestion, set `observability_bind_ip` to the observability server's private IPv4 address and `observability_ingest_url` to the matching address without a port, for example `http://100.64.0.10`. Leave `metrics_target` and `collector_log_dir` empty if those signals are unavailable. `metrics_target` is a `host:port` address reachable from the **Alloy container beside the application**, and `collector_log_dir` is an absolute directory on the monitored host. Additional panel PromQL queries go in `metric_queries`.

Secrets are separate:

```sh
cp .env.example .env
```

Set `GRAFANA_ADMIN_PASSWORD` in `.env`. Set `AGENTOS_TOKEN` there when AgentOS requires a bearer token. The panel sends this token server-side; it is never returned by `/api/config`.

After editing `config.py`, regenerate the local runtime files:

```sh
.venv/bin/python -m agno_observability_kit.configure
```

This writes ignored `infra/observability-server/.runtime.env`, `infra/application-collector/.runtime.env`, `infra/application-collector/generated.alloy` and `infra/performance-tests/.runtime.env`. Regenerate them on each machine after copying or editing `config.py`.

## Start the observability server

On the machine that will run the observability server:

```sh
docker compose -f infra/observability-server/compose.yaml --env-file .env --env-file infra/observability-server/.runtime.env up -d --build
```

Open the panel at `http://localhost:8010` and Grafana at `http://localhost:3000`. The panel and Grafana listen on loopback. Prometheus, Loki and the Tempo OTLP receiver bind to `observability_bind_ip`; keep that address inside a private network and restrict access to the monitored hosts. Grafana provisions a generic dashboard with run rate, error rate, duration and logs. It shows run metrics after the application calls `telemetry.record_run(...)`.

After changing `config.py`, rerun `.venv/bin/python -m agno_observability_kit.configure` and rebuild the panel with `docker compose -f infra/observability-server/compose.yaml --env-file .env --env-file infra/observability-server/.runtime.env up -d --build panel`.

## Start the application collector

On the monitored host, copy this repository with the edited `config.py`, then run:

```sh
.venv/bin/python -m agno_observability_kit.configure
docker compose -f infra/application-collector/compose.yaml --env-file infra/application-collector/.runtime.env up -d
```

The application collector listens for OTLP on local ports `4317` and `4318`. By default these ports bind only to `127.0.0.1`. When an application container must reach Alloy through another private host interface, set `collector_bind_ip` to that interface's IPv4 address and regenerate the files. Do not bind ingestion ports to a public interface.

Signal sources are independent:

| Signal | What the monitored application supplies | Collector setting |
| --- | --- | --- |
| AgentOS state | Reachable AgentOS HTTP API; database for persisted sessions | `agentos_url` on the observability server |
| Metrics | OTLP export or a Prometheus exposition endpoint, usually `/metrics` | OTLP HTTP `:4318` or gRPC `:4317`; optionally `metrics_target` and `metrics_path` |
| Logs | OTLP export or log files in a host directory | OTLP HTTP `:4318` or gRPC `:4317`; optionally `collector_log_dir` and `collector_log_glob` |
| Traces | OpenTelemetry OTLP export to Alloy on the monitored host | OTLP HTTP `:4318` or gRPC `:4317` |

For a process running directly on the monitored host, a typical OTLP HTTP endpoint is `http://127.0.0.1:4318`. A container must use an address that reaches the chosen `collector_bind_ip`. Set a stable OpenTelemetry `service.name` in the application. The application must export each signal it needs monitored; data stored in an AgentOS database does not automatically reach Prometheus, Loki or Tempo. The application collector adds `project_id` and `environment` labels to metric and log streams.

The AgentOS native `/metrics` API contains persisted Agno aggregates. It is not assumed to be a Prometheus exposition endpoint. Configure `metrics_target` only when the application exposes Prometheus format metrics.

## Instrument an Agno application

From this repository's checkout on the application host, install the optional telemetry dependencies in the **application's** Python environment:

```sh
pip install -e '.[telemetry]'
```

Call the setup function once at startup, before creating AgentOS or running agents. `collector_url` points to Alloy on the application host, not to the observability server:

```python
from agno_observability_kit.instrumentation.agno import configure_agno_telemetry

telemetry = configure_agno_telemetry(
    service_name="my-agentos",
    project_id="my-project",
    environment="production",
    collector_url="http://127.0.0.1:4318",
    loggers=("my_application",),
)

# Create the existing AgentOS app below this line. Keep its own persistence setup.
```

The helper exports Agno spans through OpenInference, attaches one OTLP logging handler to each named Python logger, and creates a meter. Record application-level run metrics where the caller has timing and status:

```python
import logging

telemetry.record_run(component_type="agent", status="ok", duration_seconds=1.2)
logger = logging.getLogger("my_application")
logger.setLevel(logging.INFO)
logger.info("run complete", extra={"run_id": "run-123", "session_id": "session-456"})
```

Use actual run and session IDs from the application. `run_id` and `session_id` belong in traces and logs, never in metric labels. Logs written while a span is active also carry its trace and span IDs. Call `telemetry.flush()` during a controlled shutdown if the process may exit before batched signals are sent. OTLP HTTP sends traces, metrics and logs to `/v1/traces`, `/v1/metrics` and `/v1/logs` on the collector.

Agno tracing is process-wide. If `AgentOS(tracing=True)` or another tracer provider is already active, this helper raises an error instead of replacing it; configure an exporter on the existing provider and instrument Agno there. Set up one tracer provider before AgentOS starts. Traces can include prompts or responses, so review application data before enabling external export. See the [Agno tracing guide](https://docs.agno.com/tracing/overview) and [OpenTelemetry Python exporter guide](https://opentelemetry.io/docs/languages/python/exporters/).

## Optional Langfuse

The application collector can send OTLP traces to Langfuse as well as Tempo. Use an existing Langfuse instance or start the self-hosted Compose services below. Langfuse API keys are created per project in its UI; the kit does not create them.

To start Langfuse on the observability server, first fill the secrets in `infra/langfuse/.env`. Use long random values and a 64-character hex `LANGFUSE_ENCRYPTION_KEY` (`openssl rand -hex 32`). Keep database passwords URL-safe.

```sh
cp infra/langfuse/.env.example infra/langfuse/.env
docker compose -f infra/observability-server/compose.yaml -f infra/langfuse/compose.yaml \
  --env-file .env --env-file infra/langfuse/.env --env-file infra/observability-server/.runtime.env \
  up -d langfuse-web langfuse-worker
```

By default, the UI is at `http://localhost:3001` and the media endpoint is at `http://localhost:9092`. If the application collector runs on another machine, set `langfuse_bind_ip` to a private address on the observability server and set `langfuse_ui_url` and `langfuse_media_url` to URLs using that address. Regenerate `infra/observability-server/.runtime.env` before starting the services. Allow access to the UI from the application collector only through a trusted private network. Langfuse's Docker Compose setup needs substantial memory and persistent storage; see its [deployment guide](https://langfuse.com/self-hosting/deployment/docker-compose).

Create a Langfuse project and its API keys in the UI. Then set `langfuse_otlp_url` in `config.py` to the URL reachable **from Alloy on the monitored host**, ending in `/api/public/otel`, for example `http://100.64.0.10:3001/api/public/otel`. Set `langfuse_ui_url` to the browser URL to show its link in the panel. For Langfuse Cloud, use the base URL for the chosen data region followed by `/api/public/otel`.

On the monitored host, put the project keys in `infra/application-collector/.env`, regenerate the Alloy configuration, and restart the application collector container:

```sh
cp infra/application-collector/.env.example infra/application-collector/.env
# Fill LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in infra/application-collector/.env.
.venv/bin/python -m agno_observability_kit.configure
docker compose -f infra/application-collector/compose.yaml --env-file infra/application-collector/.runtime.env up -d --force-recreate
```

The credentials stay outside `config.py` and are sent as HTTP Basic authentication to Langfuse. The [Langfuse OTLP endpoint](https://langfuse.com/docs/observability/get-started) accepts traces; metrics and logs continue to Prometheus and Loki.

## Performance tests

The API request scenario is isolated from the observability server and only calls the AgentOS listing endpoints. It does not run agents or spend model tokens. Start it explicitly on a machine that can reach AgentOS:

```sh
docker compose -f infra/performance-tests/compose.yaml --env-file .env --env-file infra/performance-tests/.runtime.env up -d
```

Locust is then available at `http://localhost:8089`. Use a separate test environment or an approved test window before creating users in its UI.

## Development checks

```sh
.venv/bin/python -m unittest discover -s tests -v
docker compose -f infra/observability-server/compose.yaml --env-file .env --env-file infra/observability-server/.runtime.env config --quiet
docker compose -f infra/application-collector/compose.yaml --env-file infra/application-collector/.runtime.env config --quiet
docker compose -f infra/observability-server/compose.yaml -f infra/langfuse/compose.yaml --env-file .env --env-file infra/langfuse/.env --env-file infra/observability-server/.runtime.env config --quiet
```

The panel uses only AgentOS read endpoints. It shows source status, recent logs with filters, run history and persisted session runs. Grafana's data sources and a generic dashboard are provisioned; project-specific dashboards can be added without changing the panel.
