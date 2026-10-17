# O que criar no Acessília e no Toolbox

Este guia registra mudanças **a fazer nos serviços**, além das URLs/tokens que você preencherá depois. Nenhum código desses dois repositórios foi alterado nesta branch. A central, SDK, host agent e interface estão no acessilia-observability.

## Estado conferido em 17/10/2026

| Repositório / develop | Revisão lida | Comportamento atual |
|---|---|---|
| A11yDevs/acessilia | `aebf600fa7a05d780b6d922f2450ded54a10fd40` | API de jobs com autorização por job, fila unificada, persistência SQLite, pipeline PDDL+Toolbox e cache |
| A11yDevs/acessilia-toolbox | `3e0fc2ecfac1ac7711220c148fccef7ea2950341` | REST/MCP, registro de capabilities/providers, limite de concorrência, artifacts/cache/proveniência |

### O que já existe

**Acessília**

- Endpoints já disponíveis:

  | Método / rota | Acesso | O que entrega |
  |---|---|---|
  | `POST /api/v1/jobs` | Público, limitado a 5/min | Aceita documento; responde 202 com `task_id`, `job_token` e posição |
  | `GET /api/v1/jobs/{task_id}` | `X-Job-Token` daquele job | Estado e etapa atual; não lista outros jobs |
  | `POST /api/v1/jobs/{task_id}/cancel` | `X-Job-Token` daquele job | Solicita cancelamento |
  | `GET /api/v1/health` | `OBSERVABILITY_API_TOKEN` | Liveness, fila e alcance do modelo |
  | `GET /api/v1/stats` | Mesmo token | Totais, sucesso/erro, duração agregada |
  | `GET /api/v1/history?limit=20` | Mesmo token | Até 100 conversões anteriores com metadados de resultado |
  | `GET /api/v1/logs` e `/api/v1/logs/{filename}` | Mesmo token | Lista e baixa logs brutos permitidos |
  | `GET /api/v1/download/{token}[/{format}]` | Token de download na rota | Consulta/baixa artefato final |

  `backend/api/routes/jobs.py` gera o token por job; `backend/api/job_auth.py` exige `X-Job-Token` para status e cancelamento. Acesso ao status é por job, não por token administrativo global. **Não existe listagem global de jobs.**
- `backend/api/worker.py` e `services/queue_service.py`: fila em memória, worker, estados de execução, cancelamento, exportação/entrega. `services/job_store.py` persiste requisição, hash do token e status em SQLite para consulta/recovery. Na reinicialização, trabalho ainda enfileirado pode ser recuperado; execução que já estava em andamento é marcada interrompida, não repetida automaticamente.
- `GET /api/v1/health`, `/stats`, `/history` e `/logs` compartilham `OBSERVABILITY_API_TOKEN`, sem escopos separados. `/history` retorna metadados de conversões; `/logs` lista e baixa logs brutos `bot_*.log` e `.zip`. O logger gira diariamente e mantém 30 dias. O serviço registra email destinatário durante o envio; portanto, quem tem o token de leitura também consegue baixar essa informação. O token deve ficar apenas no backend da central. Se o requisito for que a central não tenha acesso a logs pessoais, crie autorização separada/scopada no Acessília antes de entregar o token à central. Esses endpoints **não** são um fluxo de eventos por decisão.
- `GET /health` consulta também a disponibilidade do modelo, com timeout de 3 segundos. Pode retornar `status=ok` e `model_reachable=false`; a central deve mostrar a degradação e não interpretar liveness como capacidade de processar.
- `backend/service.py`: cache e entrada de processamento. `backend/agents/pddl_orchestrator.py`: extração Toolbox, inspeção/enriquecimento, planejamento, execução e montagem do resultado. `PDDL_EXECUTE_DRY_RUN=true` ainda chama o executor, que simula os passos; `false` executa os métodos e o fluxo pode replanejar até duas vezes. Instrumente o resultado real de cada etapa, incluindo `simulated` no dry-run e `replan-required` quando ocorrer. O status final do job é diferente do status HTTP 202 de aceite.
- `backend/core/execution/executor.py` guarda decisões por método, obrigações, precondições e relatório; `core/planning/planner_agent.py` guarda back-end/planos comparados. `frontend/agent_os.py` é um showcase separado, não o pipeline de documentos.

**Acessília Toolbox**

- `src/acessilia_toolbox/api/rest.py`: `GET /v1/health` é público. REST autenticado com `TOOLBOX_API_KEY` inclui `GET /v1/capabilities[/{id}]`, `/v1/providers[/{id}]`, `/v1/providers/{id}/health`; `POST /v1/capabilities/{id}:execute`; `POST/GET /v1/artifacts` e metadados; `/v1/datasets/...`; e `/v1/planning/...`. Há também servidor MCP, com transporte próprio.
- `api/app.py` se recusa a iniciar sem `TOOLBOX_API_KEY`, exceto quando `TOOLBOX_ALLOW_UNAUTHENTICATED=1` é explicitamente ligado para desenvolvimento local. O endpoint público de health não prova que cada provider esteja saudável; consulte `/v1/providers/{provider_id}/health` quando necessário.
- `core/executor.py` valida manifesto/entrada, resolve provider, orienta imagem quando solicitado, consulta/escreve cache, executa adapter, normaliza documento e devolve artifacts + `ExecutionProvenance` (versões, duração, cache hit, fingerprints). REST roda esse trabalho em threadpool e limita execuções simultâneas. Não existe lifecycle/global job store na Toolbox: ela executa capability chamada pelo serviço/agente consumidor.

### Fronteira modular: o que fica em cada serviço

- **Acessília mantém** autoridade sobre mensagem, `task_id`, fila, estado, cancelamento, recovery, pipeline, resultado e entrega. A telemetria acompanha esses fatos; não substitui `state_manager`, `job_store` ou a API por job. Dentro do Acessília ficam o pequeno módulo de instrumentação, a correlação serializável junto de `ApiJob`/requisição persistida e os eventos emitidos nos pontos reais de decisão. Continue expondo `OBSERVABILITY_API_TOKEN` para leituras existentes; não acrescente um endpoint global de jobs só para a central.
- **Toolbox mantém** catálogo/manifestos, providers, execução de capabilities, cache, artifacts e proveniência próprios. Instrumente execução como spans filhos da operação recebida, propague a correlação nas chamadas REST e MCP que suportarem contexto; não emita um segundo `job succeeded` para o job do Acessília.
- **Central mantém** ingestão, retenção, consultas, painel, correlação e processo/host. Seu SQLite é uma cópia de telemetria, não fonte autoritativa do processamento. Não espelhe tabelas de jobs, documentos, `email`, token do job, payload, artefatos ou logs brutos.

### Trabalho ainda necessário para observabilidade completa

Os endpoints de saúde/catálogo existentes bastam para inventário e disponibilidade básica. Para responder “por que esta mensagem escolheu este caminho?”, ainda é necessário instalar o SDK da central nos processos Acessília e Toolbox, criar os hooks abaixo e transportar a mesma correlação pela fila e pelas chamadas entre serviços. Sem isso, status agregado e logs não reconstroem a decisão por mensagem.

Na API Acessília o token do job é deliberadamente separado do token de observabilidade. A central não deve enumerar jobs com credenciais de usuário nem extrair timeline de `/history`/`/logs`; publique eventos no próprio worker. O endpoint de logs serve a diagnóstico administrativo: como os logs podem conter metadados privados, mantenha o token restrito e não os encaminhe para a central.

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
import os
from agno_observability_kit.client import Correlation

environment = os.getenv("OBS_ENVIRONMENT", "develop")
ctx = Correlation(
    job_id=f"{environment}:{task_id}", trace_id=uuid.uuid4().hex,
    span_id=uuid.uuid4().hex[:16],
    message_id=uuid.uuid4().hex, session_id="opaque-session-id",
)
telemetry.emit(kind="job", phase="queue", status="queued",
               name="Job na fila", correlation=ctx,
               attributes={"queue_position": position})
```

**Adicione `observation: dict` ao `ApiJob` e persista `Correlation.model_dump()` junto da requisição SQLite.** O `QueueItem` já encaminha o `ApiJob` ao worker; reconstrua a correlação desse dicionário no `JobExecutor.run`, inclusive durante `recover_pending_jobs`. Passe o mesmo contexto ao worker; não crie trace novo para o mesmo job. `ContextVar` não atravessa reinícios/processos. Observe a execução inteira, incluindo exportação/entrega, preservando os handlers existentes:

```python
with telemetry.job(job.task_id, correlation=job.observation):
    await existing_job_run(job)  # Extrair corpo atual de run, não chamar run recursivamente.
```

`Telemetry.job` pode gerar running + terminal e duração. **Inspecione os ramos atuais do `JobExecutor.run` antes de usá-lo como wrapper:** o worker captura falhas/cancelamento e registra estado; se a exceção for engolida, o context manager pode concluir `succeeded`. Emita o status terminal a partir do estado persistido/retornado ou repropague a exceção só depois de persistir o desfecho. Cancelamento ainda na fila precisa emitir `cancelled`; cache hit continua sendo o mesmo job e deve registrar o retorno antecipado.

Para mensagem respondida sem criar job, emita o lifecycle próprio com `job_id=message_id`, fases intake/model/delivery. Não use mensagens recebidas como `name`/`rationale`.

## 4. Registrar as decisões nos pontos reais

| Arquivo / ponto | Evento a acrescentar | Evidência a registrar |
|---|---|---|
| `backend/service.py` / cache | span cache + decisão hit/miss | `cache_hit`, versão/pipeline; sem paths/nomes de arquivo |
| `pddl_orchestrator.py` / extraction | span manifest | capability/provider realmente escolhidos, duração, contagens |
| `inspect_source_media` / imagem-tabela | spans media_inspect/enrichment | fallback, página, provider, sucesso/falha; sem imagem/texto |
| `_build_plan` / `PlannerAgent.plan/compare` | span planning + decisão | backend escolhido, alternativas comparadas, preferred_plan, motivo, plan_id |
| `ExecutorAgent._execute_step` | span execution por passo | action/method, índice, obrigação, pré-condições verificadas, dry_run, status `simulated` |
| `MethodRegistry` / resultado | decisão validation | accepted/rejected, reason_code, obrigações satisfeitas, `replan_required`; retorno do handler sozinho não comprova resultado final |
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

O executor roda tanto em dry-run quanto no modo real. No dry-run, registre `dry_run=true` e status de passo `simulated`; isso não prova efeito real no documento. No modo real, registre `succeeded/failed` do método e obrigações satisfeitas/reprovadas. Um relatório pode retornar `replan-required`; acompanhe cada tentativa com span próprio e só finalize o job após o relatório final e a entrega. Se método de revisão humana ou resultado pendente aparecer, registre o resultado explícito, sem inferir conclusão a partir do retorno da função. Registre motivos concretos e outputs estruturados da política/planner, não peça ao modelo uma suposta cadeia de pensamento interna.

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

O handler REST chama `CapabilityExecutor.execute` via `run_in_threadpool`; verifique a propagação de contexto da versão de AnyIO instalada e faça bind explícito se necessário. Para MCP, extraia/binde contexto no handler de tools do transporte quando houver metadados; o middleware HTTP não instrumenta sessões MCP/stdin por conta própria. Se não houver contexto propagado, registre trace local com vínculo remoto ausente explicitamente.

Caso a Toolbox tenha tarefas internas assíncronas, só crie lifecycle `kind=job` para esses jobs com IDs próprios. As operações síncronas de um job Acessília são spans; não emita conclusão do job pai na Toolbox.

## 7. Host agent

No host onde rodam Acessília/Toolbox, instale `acessilia-observability[host]`, preencha `OBS_HOST_ID`, `OBS_CENTRAL_URL` e `OBS_HOST_TOKEN` e execute `python -m agno_observability_kit.host_agent`. Deixe o processo sob o supervisor já usado no deployment (systemd/Compose externo), com restart on failure. Não execute dentro do container da central para obter processos do host. Não precisa criar uma API de processos no Acessília nem conceder Docker socket/root.

Permissões normais mostram somente processos acessíveis; processos inacessíveis são ignorados. Use `OBS_SERVICE_PIDS=acessilia=123,acessilia-toolbox=456` opcionalmente e atualize ao reiniciar serviços. PIDs em containers dependem do namespace observado. Jobs são identificados pelos eventos, não por adivinhação de command line.

## 8. Traces Agno / OTLP opcionais

O runtime Agno tem tracing próprio, mas ele não substitui os eventos do pipeline. Consulte [OpenTelemetry Agno](https://docs.agno.com/observability/overview) e [tracing AgentOS](https://docs.agno.com/agent-os/tracing/overview). O suporte é por processo; instrumentação externa requer exporter/instrumentor explícitos. Instale `[telemetry]` só no processo em que precisa instrumentar Agno e configure uma vez, antes de criar agentes. O helper existente `instrumentation/agno.py` manda OTLP ao Alloy; preserve service.name distinto e project_id=acessilia.

**Privacidade antes de ativar OpenInference:** configure a política de ocultação/redação da versão instalada para prompts, inputs, outputs e argumentos de tools. O contrato de eventos desta central não garante redação de spans OTLP capturados por outro instrumentor. Para IDs W3C compartilhados com OTLP, use o contexto real do OTel como origem dos `Correlation` IDs; IDs criados somente pelo SDK de eventos não implicam que existe um trace no Tempo. Não gere links Tempo de eventos sem confirmar exportação OTLP.

## Aceite depois que você preencher as URLs

- Envie uma mensagem/documento real de teste sem dados pessoais. Confirme queued → running → etapas → export/delivery → terminal no mesmo job/message/trace e host.
- Selecione o job: confira provider/capacidade, decisão de planner, cache, validação, dry-run/simulação ou execução real, replans e durações. Compare com efeitos/artifacts reais.
- Provoque cache hit, falha de provider, fallback e cancelamento na fila e em execução. Falhas não podem terminar como sucesso.
- Duas mensagens simultâneas não podem trocar session/job/trace IDs. Um span Toolbox deve ter pai Acessília com os mesmos IDs.
- Pare a Toolbox: seu health falha, o painel/máquina permanecem acessíveis. Pare a central: aplicações continuam; o emissor incrementa dropped_events.
- Reinicie a central: os eventos confirmados continuam no volume. Pare o host agent: a amostra fica antiga, sem fingir CPU/processos atuais.
- Confirme que tokens, bodies, conteúdo do documento, email, download tokens, paths e mensagens privadas não estão no SQLite, export ou OTLP.
- Após integrar os dois serviços, revise os testes correspondentes à instrumentação (especialmente early returns, exceptions tratadas e cancelamentos).
