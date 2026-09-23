# Agno Observability Kit

A standalone, read-only observability hub for an Agno AgentOS application. The hub and the monitored application can run on different machines. The panel discovers agents, teams and workflows through the AgentOS API and reads persisted sessions and runs when AgentOS has a database. An optional Alloy process beside the application sends metrics, logs and traces to the hub.

The kit monitors one project per installation. It does not import application code or require a shared Docker network or filesystem between the hub and AgentOS.

## Requirements

- Python 3.11 or newer to generate runtime configuration.
- Docker with Compose on the hub, and on the monitored host if using the bundled Alloy service.
- Network access from the hub to AgentOS. For remote ingestion, use a private network address reachable from the monitored host.
- An AgentOS instance exposing the Agno 3.x API. Persisted sessions require AgentOS database storage.

Install the Python package in a local environment before generating configuration:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Configure the project

Edit [`config.py`](config.py). Set `project_id`, `project_name`, `environment` and `agentos_url`. The URL must be reachable **from inside the panel container**; `localhost` inside that container is not the monitored host. The panel uses `/info` and `/config` when available, then falls back to `/agents`, `/teams` and `/workflows`.

For remote ingestion, set `hub_bind_ip` to the hub's private IPv4 address and `hub_ingest_url` to the matching address without a port, for example `http://100.64.0.10`. Leave `metrics_target` and `edge_log_dir` empty if those signals are unavailable. `metrics_target` is a `host:port` address reachable from the **edge Alloy container**, and `edge_log_dir` is an absolute directory on the monitored host. Additional panel PromQL queries go in `metric_queries`.

Secrets are separate:

```sh
cp .env.example .env
```

Set `GRAFANA_ADMIN_PASSWORD` in `.env`. Set `AGENTOS_TOKEN` there when AgentOS requires a bearer token. The panel sends this token server-side; it is never returned by `/api/config`.

After editing `config.py`, regenerate the local runtime files:

```sh
.venv/bin/python -m agno_observability_kit.configure
```

This writes ignored `.runtime.env`, `edge/.runtime.env`, `edge/generated.alloy` and `loadtest/.runtime.env`. Regenerate them on each machine after copying or editing `config.py`.

## Start the hub

On the hub machine:

```sh
docker compose --env-file .env --env-file .runtime.env up -d --build
```

Open the panel at `http://localhost:8010` and Grafana at `http://localhost:3000`. The panel and Grafana listen on loopback. Prometheus, Loki and the Tempo OTLP receiver bind to `hub_bind_ip`; keep that address inside a private network and restrict access to the monitored hosts.

After changing `config.py`, rerun `.venv/bin/python -m agno_observability_kit.configure` and rebuild the panel with `docker compose --env-file .env --env-file .runtime.env up -d --build panel`.

## Start the edge collector

On the monitored host, copy this repository with the edited `config.py`, then run:

```sh
.venv/bin/python -m agno_observability_kit.configure
docker compose -f edge/compose.yaml --env-file edge/.runtime.env up -d
```

The edge collector listens for OTLP on local ports `4317` and `4318`. By default these ports bind only to `127.0.0.1`. When an application container must reach Alloy through another private host interface, set `edge_bind_ip` to that interface's IPv4 address and regenerate the files. Do not bind ingestion ports to a public interface.

Signal sources are independent:

| Signal | What the monitored application supplies | Edge setting |
| --- | --- | --- |
| AgentOS state | Reachable AgentOS HTTP API; database for persisted sessions | `agentos_url` on the hub |
| Metrics | OTLP export or a Prometheus exposition endpoint, usually `/metrics` | OTLP HTTP `:4318` or gRPC `:4317`; optionally `metrics_target` and `metrics_path` |
| Logs | OTLP export or log files in a host directory | OTLP HTTP `:4318` or gRPC `:4317`; optionally `edge_log_dir` and `edge_log_glob` |
| Traces | OpenTelemetry OTLP export to edge Alloy | OTLP HTTP `:4318` or gRPC `:4317` |

For a process running directly on the monitored host, a typical OTLP HTTP endpoint is `http://127.0.0.1:4318`. A container must use an address that reaches the chosen `edge_bind_ip`. Set a stable OpenTelemetry `service.name` in the application. The application must export each signal it needs monitored; data stored in an AgentOS database does not automatically reach Prometheus, Loki or Tempo. The edge adds `project_id` and `environment` labels to metric and log streams.

The AgentOS native `/metrics` API contains persisted Agno aggregates. It is not assumed to be a Prometheus exposition endpoint. Configure `metrics_target` only when the application exposes Prometheus format metrics.

## Optional Langfuse

The edge can send OTLP traces to Langfuse as well as Tempo. Use an existing Langfuse instance or start the self-hosted Compose services below. Langfuse API keys are created per project in its UI; the kit does not create them.

To start Langfuse on the hub, first fill the secrets in `langfuse/.env`. Use long random values and a 64-character hex `LANGFUSE_ENCRYPTION_KEY` (`openssl rand -hex 32`). Keep database passwords URL-safe.

```sh
cp langfuse/.env.example langfuse/.env
docker compose -f compose.yaml -f langfuse/compose.yaml \
  --env-file .env --env-file langfuse/.env --env-file .runtime.env \
  up -d langfuse-web langfuse-worker
```

By default, the UI is at `http://localhost:3001` and the media endpoint is at `http://localhost:9092`. If the edge runs on another machine, set `langfuse_bind_ip` to a private address on the hub and set `langfuse_ui_url` and `langfuse_media_url` to URLs using that address. Regenerate `.runtime.env` before starting the services. Allow access to the UI from the edge only through a trusted private network. Langfuse's Docker Compose setup needs substantial memory and persistent storage; see its [deployment guide](https://langfuse.com/self-hosting/deployment/docker-compose).

Create a Langfuse project and its API keys in the UI. Then set `langfuse_otlp_url` in `config.py` to the URL reachable **from edge Alloy**, ending in `/api/public/otel`, for example `http://100.64.0.10:3001/api/public/otel`. Set `langfuse_ui_url` to the browser URL to show its link in the panel. For Langfuse Cloud, use the base URL for the chosen data region followed by `/api/public/otel`.

On the monitored host, put the project keys in `edge/.env`, regenerate the Alloy configuration, and restart the edge container:

```sh
cp edge/.env.example edge/.env
# Fill LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in edge/.env.
.venv/bin/python -m agno_observability_kit.configure
docker compose -f edge/compose.yaml --env-file edge/.runtime.env up -d --force-recreate
```

The credentials stay outside `config.py` and are sent as HTTP Basic authentication to Langfuse. The [Langfuse OTLP endpoint](https://langfuse.com/docs/observability/get-started) accepts traces; metrics and logs continue to Prometheus and Loki.

## Load tests

The load scenario is isolated from the hub and only calls the AgentOS listing endpoints. It does not run agents or spend model tokens. Start it explicitly on a machine that can reach AgentOS:

```sh
docker compose -f loadtest/compose.yaml --env-file .env --env-file loadtest/.runtime.env up -d
```

Locust is then available at `http://localhost:8089`. Use a separate test environment or an approved load window before creating users in its UI.

## Development checks

```sh
.venv/bin/python -m unittest discover -s tests -v
docker compose --env-file .env --env-file .runtime.env config --quiet
docker compose -f edge/compose.yaml --env-file edge/.runtime.env config --quiet
docker compose -f compose.yaml -f langfuse/compose.yaml --env-file .env --env-file langfuse/.env --env-file .runtime.env config --quiet
```

The panel uses only AgentOS read endpoints. Grafana's data sources are provisioned, while project-specific dashboards can be added without changing the panel.
