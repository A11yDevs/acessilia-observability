# Acessília Observability

Central de operação para **Acessília + Acessília Toolbox**: processos da máquina, jobs em andamento, decisões e operações correlacionadas por mensagem, sessão, job e trace. A página inicial mostra a máquina monitorada; ao selecionar um job, exibe a sequência de eventos e os spans entre os dois serviços.

- Processos, CPU, memória e disco por máquina; amostras antigas são sinalizadas.
- Jobs na fila, em execução, concluídos, cancelados e falhos; perda de eventos e falta de atualização são visíveis.
- Planejamento PDDL, cache, escolha de provider, capacidade, alternativas, código do motivo, fallback, tentativas, validação e exportação.
- IDs correlacionados entre serviços; hierarquia dos spans, duração, tokens/custo quando fornecidos pela aplicação, e exportação dos eventos carregados.
- Consulta somente de leitura das APIs reais da `develop`; falha de um serviço não derruba os demais.
- SQLite persistente, ingestão idempotente, limite de eventos e retenção; tokens distintos para leitura, eventos e máquina.
- Prometheus, Loki, Tempo, Grafana e Langfuse opcional preservados como ferramentas de investigação complementar.

**A central está pronta para receber dados. É necessário instrumentar as aplicações e executar o host agent na máquina monitorada.** URLs vazias mostram “não configurado”; nenhum job ou processo fictício é inserido automaticamente. O AgentOS atual é um showcase de VisionAgent/DataAgent, separado do pipeline real. O executor PDDL roda em modo simulado quando `PDDL_EXECUTE_DRY_RUN=true`; a interface deve distinguir simulação de efeito real.

## Executar localmente

Python 3.11+; Linux para o coletor de máquina. No diretório do projeto:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[host]' pytest
cp .env.example .env
# Preencha OBS_VIEW_TOKEN, OBS_INGEST_TOKEN e OBS_HOST_TOKEN com tokens distintos.
# Gere cada valor localmente com: openssl rand -hex 32
# As URLs dos outros serviços podem continuar vazias.
set -a
source .env
set +a
.venv/bin/uvicorn frontend.app:app --host 127.0.0.1 --port 8010
```

Abra http://localhost:8010 e entre com `OBS_VIEW_TOKEN`. Sem esse token, execução local permite leitura; mantenha o bind em loopback. A ingestão sempre exige seus próprios tokens, inclusive no modo local. Não coloque `.env` no Git. O guia também pode ser aberto em `/docs/integration`.

## Stack Docker

```bash
.venv/bin/python -m agno_observability_kit.configure
docker compose --env-file .env --env-file infra/observability-server/.runtime.env \
  -f infra/observability-server/compose.yaml up -d --build
```

Preencha também `GRAFANA_ADMIN_PASSWORD`. Os três tokens da central são obrigatórios no Compose. O volume `observation-data` preserva os eventos após reinício. APIs vazias são permitidas; configure depois uma URL alcançável **a partir do container** (`localhost` aponta para o próprio container). O Compose disponibiliza `host.docker.internal` no Linux. O painel fica em loopback; para acesso remoto, use um túnel SSH ou proxy HTTPS autenticado. Ingestão OTLP e serviços Grafana devem permanecer na rede privada.

## Monitorar a máquina

Instale o extra `[host]` e execute **fora do container do painel**, no host que executa os serviços:

```bash
export OBS_CENTRAL_URL=http://127.0.0.1:8010
export OBS_HOST_ID=acessilia-dev-01
# OBS_HOST_TOKEN deve corresponder ao configurado na central.
.venv/bin/python -m agno_observability_kit.host_agent --interval 15
# Para inspecionar somente localmente, sem publicar:
.venv/bin/python -m agno_observability_kit.host_agent --once
```

O coletor é somente de leitura. Não executa comandos administrativos, não mata processos e não monta Docker socket. Coleta os processos visíveis ao usuário até 200 por amostra, priorizando os serviços mapeados em `OBS_SERVICE_PIDS` e CPU/memória. A primeira medida de CPU de um novo PID pode ser zero. Amostras sem atualização por 90 segundos aparecem como antigas. Execute um coletor por máquina com `OBS_HOST_ID` distinto.

## Instrumentar os projetos

O [guia completo](docs/acessilia-integration.md) registra o estado atual das duas branches `develop`, todos os pontos de instrumentação, variáveis, headers e critérios de aceite. O [contrato](docs/event-contract.md) descreve eventos e APIs. O cliente está em `agno_observability_kit.client`: `Telemetry`, `Correlation`, `ObservationMiddleware`, `correlation_headers` e `correlation_from_headers`.

```python
from agno_observability_kit.client import Telemetry

telemetry = Telemetry("acessilia")  # URL/token pelo ambiente; vazio desabilita exportação.
with telemetry.job("job-123", message_id="message-123", session_id="opaque-session"):
    with telemetry.span("planning", "Plano nominal", planner_backend="internal"):
        telemetry.decision("planning", "Plano selecionado",
                           reason_code="configured_backend", selected="internal")
telemetry.close()  # No encerramento do processo, não a cada job.
```

Esse exemplo demonstra o contrato; não substitui o pipeline real. Reuse a correlação criada na entrada ao enfileirar e executar o job. O cliente exporta em segundo plano, fila limitada, retry único e IDs idempotentes. Falhas de coleta não interrompem o pipeline. `dropped_events` informa perda local. Não há spool durável no emissor: eventos ainda em memória podem se perder em encerramento abrupto. Na central, a persistência ocorre antes da resposta de ingestão.

## Verificar

```bash
.venv/bin/pytest -q
node --check frontend/static/central.js
```

Para testar envio dos dois emissores sem modelos ou providers, defina `OBS_CENTRAL_URL`/`OBS_INGEST_TOKEN` e execute `.venv/bin/python examples/smoke_ecosystem.py`. O script publica um job com ID `smoke-*` e eventos marcados **TESTE SINTÉTICO**; não é validação do pipeline real.

Os testes usam banco temporário e APIs simuladas; não chamam modelos nem serviços de produção. Veja o guia para validar depois com suas URLs. A central observa eventos e justificativas operacionais explicitamente registrados; não inventa decisões ausentes nem acessa raciocínio privado do modelo. Entradas/saídas de documentos e prompts não fazem parte do contrato. Strings operacionais recebem redação de credenciais, URLs e emails; ainda devem ser produzidas sem dados pessoais pela aplicação.

O [guia anterior do kit Agno](docs/agno-kit.md) permanece como referência da stack OTLP/Langfuse, com comandos de instalação do nome anterior; para esta branch instale `acessilia-observability`.
