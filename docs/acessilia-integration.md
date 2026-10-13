# O que criar no Acessília e no Toolbox

Este guia registra mudanças **a fazer nos serviços**, além das URLs/tokens que você preencherá depois. Nenhum código desses dois repositórios foi alterado nesta branch. A central, SDK, host agent e interface estão no acessilia-observability.

## Estado conferido em 13/10/2026

| Repositório / develop | Revisão lida | Comportamento atual |
|---|---|---|
| A11yDevs/acessilia | `331e55935e89dda8fa33a684f69f0a45efeacf48` | API de jobs, fila unificada, pipeline PDDL+Toolbox, histórico; engine legado desativado |
| A11yDevs/acessilia-toolbox | `64318eaeb9b358b5ea06137b85c2fdc310be66e1` | REST/MCP, registro de capacidades/providers, CapabilityExecutor, artifacts/cache/proveniência |

Entradas confirmadas:

- Acessília `backend/api/app.py`: rotas `/api/v1/health`, `/stats`, `/history`, `/jobs/{task_id}`, `/logs`. `/logs` exige `settings.observability_api_token`; **não existe GET global `/jobs`**. A central não supõe esse endpoint nem vasculha nomes de arquivos/documentos para descobrir jobs.
- `backend/api/worker.py`: `register_queued_job`, `JobExecutor.run`, status callback, exports, entrega e cancelamento. `backend/services/queue_service.py`: fila. `backend/agents/state_manager.py`: transições/cancelamento.
- `backend/service.py`: `process`, cache e normalização; `PIPELINE_ENGINE=pddl`.
- `backend/agents/pddl_orchestrator.py`: extração remota, inspeção de mídia, enriquecimento de imagens/tabelas, `_build_plan`, payload. A implementação atual chama `self.executor.execute` **somente no branch `execute_dry_run=True`**. `False` não liga automaticamente um executor de produção. Há handlers no-op em `_build_executor`; não os apresente como trabalho realizado.
- `backend/core/planning/planner_agent.py`: planejamento interno/Fast Downward/comparação; `backend/core/execution/executor.py`: workflow Agno, passos, pré-condições, validação, relatório e pedido de replanejamento.
- `frontend/agent_os.py`: showcase independente de VisionAgent/DataAgent; não executa o pipeline completo. `telemetry=False` não substitui configuração explícita de tracing.
- Toolbox `src/acessilia_toolbox/api/rest.py`: `/v1/health`, `/capabilities`, `/providers`, `/providers/{id}/health`, execução `/capabilities/{id}:execute`.
- Toolbox `core/executor.py`: resolve provider, cache, orientação opcional, execução adapter, manifesto, artifacts e `ExecutionProvenance` (`duration_ms`, `cache_hit`, versões, fingerprints). Não existe registry global de jobs nesse serviço; ele recebe operações do Acessília.

## 1. Valores que você deve criar

Crie tokens diferentes com `openssl rand -hex 32`. Não copie exemplos como credenciais reais.

| Local | Variável | Preenchimento |
|---|---|---|
| Central | `OBS_VIEW_TOKEN` | Token para entrar no painel; não compartilhar com aplicações |
| Central + emissores Acessília/Toolbox | `OBS_INGEST_TOKEN` | Token de envio de eventos |
| Central + coletores de máquinas | `OBS_HOST_TOKEN` | Token distinto para amostras de máquina |
| Central | `ACESSILIA_API_URL` | URL base alcançável da API Acessília; sem `/api/v1` |
| Acessília + central | `OBSERVABILITY_API_TOKEN` / `ACESSILIA_OBSERVABILITY_TOKEN` | Mesmo token de leitura dos endpoints de observabilidade Acessília; nomes diferentes nos dois ambientes |
| Central | `TOOLBOX_API_URL` | URL base da Toolbox; sem `/v1` |
| Toolbox + central | `TOOLBOX_API_KEY` | API key do REST Toolbox (ver env/config do serviço) |
| Emissores / host agents | `OBS_CENTRAL_URL` | URL base da central, por exemplo via rede privada/túnel |
| Emissor e coletor na mesma máquina | `OBS_HOST_ID` | ID estável da máquina; o mesmo em ambos |
| Todos | `OBS_ENVIRONMENT` | `develop`, `staging` ou `production` |
| Central | `AGENTOS_URL`, `AGENTOS_TOKEN` | Opcionais; somente o showcase Agno |
| Central | `GRAFANA_ADMIN_PASSWORD` | Senha forte para a stack Grafana |

No Acessília, a variável nativa é `OBSERVABILITY_API_TOKEN` (mapeada para `settings.observability_api_token`). Nenhuma API de listagem de jobs é necessária para a central: os eventos oferecem o estado. Se quiser oferecer uma API administrativa adicional no Acessília, ela precisa de autenticação read-only e schema sem arquivos/emails/download tokens; não é requisito desta implementação.

Deixe URLs vazias até definir hosts. Ao usar containers, configure os endereços alcançáveis a partir de cada container. Tokens de leitura upstream ficam somente no backend da central; não são enviados ao browser. A central não chama LLMs nem executa capabilities para verificar saúde.

## 2. Instalar o SDK e criar um módulo no Acessília

Instale esta branch pelo caminho local ou fixe o SHA após integração:

```bash
pip install '/caminho/acessilia-observability'
```

Crie `backend/observability.py`:

```python
from agno_observability_kit.client import Telemetry

telemetry = Telemetry("acessilia")
# Construir uma vez por processo, depois do fork e antes dos requests/jobs.
# No lifespan de shutdown, chame telemetry.close() com orçamento de tempo.
```

Em `backend/api/app.py`, adicione `ObservationMiddleware` ao app criado:

```python
from agno_observability_kit.client import ObservationMiddleware
from backend.observability import telemetry

app.add_middleware(ObservationMiddleware, telemetry=telemetry)
```

Esse middleware observa POST/PUT/PATCH sem ler bodies e retorna `X-Obs-Trace-Id`; um HTTP 202 vira sucesso do span de aceite, **não** sucesso do processamento.

## 3. Mensagem → fila → worker: criar correlação persistida

Para **cada mensagem que dispara trabalho**, gere um `message_id` opaco. Telegram: não use chat ID puro nem texto; web/API/CLI: gere UUID. Crie `job_id` com namespace de ambiente e `Correlation` na entrada, antes de enfileirar. Se o task_id atual não tiver namespace, preserve-o em `job_id` somente numa central exclusiva desse ambiente. Todos os canais devem usar o mesmo caminho de instrumentação de jobs.

```python
import uuid
from agno_observability_kit.client import Correlation

ctx = Correlation(
    job_id=task_id, trace_id=uuid.uuid4().hex,
    span_id=uuid.uuid4().hex[:16],
    message_id=uuid.uuid4().hex, session_id="opaque-session-id",
)
telemetry.emit(kind="job", phase="queue", status="queued",
               name="Job na fila", correlation=ctx,
               attributes={"queue_position": position})
```

**Crie um campo `observation: Correlation` no QueueItem/ApiJob e serialize-o se a fila cruzar processos.** Passe o mesmo ctx ao worker; não crie trace novo para o mesmo job. ContextVar isolado não atravessa a fila. No `JobExecutor.run`, envolva a execução inteira, incluindo exports/entrega, preservando os handlers existentes:

```python
with telemetry.job(job.task_id, correlation=job.observation):
    await existing_job_run(job)  # Extrair corpo atual de run, não chamar run recursivamente.
```

`Telemetry.job` gera running + terminal e duração. **O corpo atual captura exceptions e pode retornar normalmente mesmo em falha/cancelamento.** Não envolva esse corpo sem adaptar o desfecho: repropague a exceção após o estado/history serem atualizados, ou use `telemetry.bind(ctx)` + emissão explícita em cada ramo de término. Isso impede um falso `succeeded`. Cancelamento ainda na fila (`cancel_job_status`) também precisa emitir `kind=job/status=cancelled` com a correlação armazenada. Cache hit mantém o mesmo job e precisa terminar corretamente mesmo quando `process` retorna cedo.

Para mensagem respondida sem criar job, emita o lifecycle próprio com `job_id=message_id`, fases intake/model/delivery. Não use mensagens recebidas como `name`/`rationale`.

## 4. Registrar as decisões nos pontos reais

| Arquivo / ponto | Evento a acrescentar | Evidência a registrar |
|---|---|---|
| `backend/service.py` / cache | span cache + decisão hit/miss | `cache_hit`, versão/pipeline; sem paths/nomes de arquivo |
| `pddl_orchestrator.py` / extraction | span manifest | capability/provider realmente escolhidos, duração, contagens |
| `inspect_source_media` / imagem-tabela | spans media_inspect/enrichment | fallback, página, provider, sucesso/falha; sem imagem/texto |
| `_build_plan` / `PlannerAgent.plan/compare` | span planning + decisão | backend escolhido, alternativas comparadas, preferred_plan, motivo, plan_id |
| `ExecutorAgent._execute_step` | span execution por passo | action/method, índice, obrigação, pré-condições verificadas, dry_run/noop |
| `MethodRegistry` / resultado | decisão validation | accepted/rejected, reason_code, replan_required; sucesso de handler no-op não é prova de efeito |
| `state_manager` / atualização | span/decisão de progresso | phase estável e status; não parsear mensagens traduzidas para inferir decisão |
| `worker.py` / export e entrega | spans export/delivery | formato, duração, erro por tipo; terminal job somente após finalização real |
| `ai_client.py`, vision/data, fusion | spans model | model, prompt_version, tokens/custo fornecidos, status e duração |

Use o contexto existente e spans curtos:

```python
with telemetry.span("planning", "Construção do plano", planner_backend=backend):
    plan, comparison = await asyncio.to_thread(build_plan, manifest)
    telemetry.decision("planning", "Backend selecionado",
                       reason_code="preferred_plan_available", selected=backend,
                       alternatives=actually_compared_backends,
                       plan_id=plan.plan_id, dry_run=execute_dry_run)
```

No branch atual em que executor é ignorado, emita `kind=span, phase=execution, status=skipped, attributes={"reason_code":"executor_not_invoked"}`. Handlers no-op: `noop=True`. Dry-run: `dry_run=True`. Validação reprovada que retorna um relatório (sem exception): emita `status=failed, validation="rejected"`; não confunda retorno bem-sucedido da função com aceitação do resultado. Registre motivos concretos e outputs estruturados da política/planner, não peça ao modelo uma suposta cadeia de pensamento interna.

## 5. Propagar para todos os clients Toolbox

Em `backend/tools/toolbox_client.py`, `*_layout_client.py`, `*_ocr_client.py`, `*_math_client.py`, `*_pdf_client.py`, `*_media_inspect_client.py`, `*_dataset_tools.py` e chamadas diretas restantes: acrescente headers por requisição, junto dos de auth.

```python
from agno_observability_kit.client import correlation_headers

headers = {**self._auth_headers, **correlation_headers()}
response = await client.post(url, headers=headers, files=files, data=data)
```

Não escreva o contexto em `self._client.headers` compartilhado. Use `telemetry.span("tool", "Execução remota", capability=capability, provider=provider)` envolvendo o request, registre retry/fallback **quando ocorrerem**, incluindo upload e artifacts. Ao receber `ExecutionResponse`, registre apenas os campos necessários de `provenance` (provider_version, duration_ms, cache_hit); não copie `document`, parâmetros, artifact URLs ou payload para telemetria.

## 6. Criar instrumentação na Toolbox

Crie `src/acessilia_toolbox/observability.py` com `Telemetry("acessilia-toolbox")`. Em `api/app.py`, instale o mesmo `ObservationMiddleware`; no shutdown, `close()`. Em `core/executor.py`, registre:

1. Resultado de `self._providers.resolve` e razão de seleção (provider explícito ou default do registry), alternativas efetivamente admissíveis.
2. Cache hit/miss antes de ambos os retornos `_restore`, incluindo o branch depois da rotação.
3. Orientação pedida, provider indisponível/fallback, `auto_rotated` quando observado.
4. Span `adapter.execute`, status de contrato, duração real e versão do provider.
5. Manifesto/artifacts/cache final por contagens e resultado; sem documentos nem fingerprints que contenham dados pessoais derivados.

O código REST executa `CapabilityExecutor.execute` sincronicamente no handler async atual. Se mover para executor/thread no futuro, preserve `Correlation`/ContextVar; uma função síncrona instrumentada funciona normalmente no contexto do request. Para MCP, bind os IDs recebidos pelo transporte ou crie trace local explicitando que não há pai; o middleware HTTP não instrumenta sessões stdio por conta própria.

Caso a Toolbox tenha tarefas internas assíncronas, só crie lifecycle `kind=job` para esses jobs com IDs próprios. As operações síncronas de um job Acessília são spans; não emita conclusão do job pai na Toolbox.

## 7. Host agent

No host onde rodam Acessília/Toolbox, instale `acessilia-observability[host]`, preencha `OBS_HOST_ID`, `OBS_CENTRAL_URL` e `OBS_HOST_TOKEN` e execute `python -m agno_observability_kit.host_agent`. Deixe o processo sob o supervisor já usado no deployment (systemd/Compose externo), com restart on failure. Não execute dentro do container da central para obter processos do host. Não precisa criar uma API de processos no Acessília nem conceder Docker socket/root.

Permissões normais mostram somente processos acessíveis; processos inacessíveis são ignorados. Use `OBS_SERVICE_PIDS=acessilia=123,acessilia-toolbox=456` opcionalmente e atualize ao reiniciar serviços. PIDs em containers dependem do namespace observado. Jobs são identificados pelos eventos, não por adivinhação de command line.

## 8. Traces Agno / OTLP opcionais

O runtime Agno tem tracing próprio, mas ele não substitui os eventos do pipeline. Consulte [OpenTelemetry Agno](https://docs.agno.com/observability/overview) e [tracing AgentOS](https://docs.agno.com/agent-os/tracing/overview). O suporte é por processo; instrumentação externa requer exporter/instrumentor explícitos. Instale `[telemetry]` só no processo em que precisa instrumentar Agno e configure uma vez, antes de criar agentes. O helper existente `instrumentation/agno.py` manda OTLP ao Alloy; preserve service.name distinto e project_id=acessilia.

**Privacidade antes de ativar OpenInference:** configure a política de ocultação/redação da versão instalada para prompts, inputs, outputs e argumentos de tools. O contrato de eventos desta central não garante redação de spans OTLP capturados por outro instrumentor. Para IDs W3C compartilhados com OTLP, use o contexto real do OTel como origem dos `Correlation` IDs; IDs criados somente pelo SDK de eventos não implicam que existe um trace no Tempo. Não gere links Tempo de eventos sem confirmar exportação OTLP.

## Aceite depois que você preencher as URLs

- Envie uma mensagem/documento real de teste sem dados pessoais. Confirme queued → running → etapas → export/delivery → terminal no mesmo job/message/trace e host.
- Selecione o job: confira provider/capacidade, decisão de planner, cache, validação, no-op/dry-run e durações. Compare com efeitos/artifacts reais.
- Provoque cache hit, falha de provider, fallback e cancelamento na fila e em execução. Falhas não podem terminar como sucesso.
- Duas mensagens simultâneas não podem trocar session/job/trace IDs. Um span Toolbox deve ter pai Acessília com os mesmos IDs.
- Pare a Toolbox: seu health falha, o painel/máquina permanecem acessíveis. Pare a central: aplicações continuam; o emissor incrementa dropped_events.
- Reinicie a central: os eventos confirmados continuam no volume. Pare o host agent: a amostra fica antiga, sem fingir CPU/processos atuais.
- Confirme que tokens, bodies, conteúdo do documento, email, download tokens, paths e mensagens privadas não estão no SQLite, export ou OTLP.
- Após integrar os dois serviços, revise os testes correspondentes à instrumentação (especialmente early returns, exceptions tratadas e cancelamentos).
