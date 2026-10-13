# Contrato operacional v1

`POST /api/ingest/events`, JSON `{"events": [...]}`, Bearer `OBS_INGEST_TOKEN`. Lote de 1–100 eventos; corpo máximo 1 MB, inclusive chunked. Duplicatas por `event_id` são ignoradas; resposta `accepted`/`duplicates`. Não reenvie outro conteúdo com o mesmo ID. Campos desconhecidos na raiz são recusados; atributos não permitidos são descartados. Na validação, a resposta não ecoa o conteúdo rejeitado.

| Campo | Contrato |
|---|---|
| schema_version | `"1"` |
| event_id | Identificador único por evento; preserve no retry |
| timestamp | ISO 8601 com timezone; até 90 dias no passado, até 5 min no futuro; relógios sincronizados |
| service | `acessilia` ou `acessilia-toolbox` |
| environment / host_id | IDs operacionais; padrão `develop` / `unassigned` |
| job_id | Mesmo identificador em todos os serviços; um namespace único por ambiente |
| message_id / session_id | IDs opacos; nunca email, texto, número de telefone ou identidade direta |
| trace_id / span_id / parent_span_id | W3C: 32 / 16 / 16 caracteres hexadecimais não nulos; pai vazio na raiz |
| kind | `job`, `span`, `decision` |
| phase | `intake`, `queue`, `cache`, `manifest`, `media_inspect`, `enrichment`, `planning`, `execution`, `validation`, `export`, `delivery`, `model`, `tool` |
| status | `queued`, `running`, `succeeded`, `failed`, `cancelled`, `retrying`, `skipped` |
| name | Nome curto da operação (máx. 160), sem mensagem/documento do usuário |
| attributes | Allowlist em `events.py`; valores escalares ou lista curta de strings |

Identificadores: letras, números, `_ . : -`, até 128 caracteres. Para separar ambientes, prefixe `job_id` (`develop:...`, `production:...`) ou use uma central/banco por ambiente. Correlacione retries do mesmo job; crie spans distintos para cada tentativa. Jobs reutilizados podem misturar histórias, portanto não reutilize IDs de execuções diferentes.

Um evento `kind=job` pertence ao dono do job (normalmente Acessília). Eventos `kind=span` da Toolbox **não** finalizam o job. O painel calcula status a partir do último evento de job por timestamp, desempate por sequência de ingestão. Use estados terminais somente após exportação/entrega, ou cancelamento/falha efetivos. Um HTTP 202 só confirma aceite. Emitir spans sem eventos de job permite consultar `/api/events`, mas não cria uma linha na listagem de jobs.

Decisões devem incluir `reason_code`, `selected`, alternativas realmente consideradas, provider/capacidade/método, `fallback`, `retry`, `dry_run` e `noop` quando aplicáveis. `rationale` admite somente justificativa operacional sanitizada; nunca raciocínio privado, prompt ou documento. Validador retornando relatório inválido deve emitir um evento `failed` com `validation=rejected`; sucesso do span de chamada só significa que a chamada retornou. Tokens e custos são opcionais e devem vir do runtime; ausência significa desconhecido, nunca zero calculado.

## Headers entre Acessília e Toolbox

`traceparent: 00-{trace_id}-{span_id}-01`, `X-Obs-Job-Id`, `X-Obs-Message-Id`, `X-Obs-Session-Id`. `correlation_headers()` gera os headers para a operação atual. Anexe a **todas** as chamadas HTTP, inclusive upload, execute, download de artifacts, clients OCR/layout/math/PDF e MCP quando o transporte permitir. São correlação, não autenticação. Mantenha os bearer tokens reais separados. Não guarde a correlação em headers compartilhados de um cliente reutilizado: passe por requisição para evitar misturar usuários.

O middleware interpreta headers e registra um span HTTP sem ler o body. Para um worker, preserve o objeto `Correlation` no item da fila: `ContextVar` não atravessa automaticamente filas ou processos. `asyncio.to_thread` preserva contexto no mesmo processo; executores de threads/processos exigem transportar a correlação e chamar `telemetry.bind(ctx)`.

## API de leitura

Quando `OBS_VIEW_TOKEN` está configurado, todos os `/api/*` de leitura exigem Bearer de visualização ou cookie de sessão HttpOnly. `POST /api/auth/login` recebe `{"token": "..."}` e define o cookie SameSite Strict (Secure quando HTTPS); `POST /api/auth/logout` remove. Use HTTPS ou túnel para tráfego remoto. O token de visualização não concede ingestão; o token de eventos não concede leitura ou escrita de hosts.

- `GET /healthz`: liveness sem conteúdo de telemetria.
- `GET /api/jobs?status=running&service=acessilia&q=job&limit=50&offset=0`: jobs e paginação, status real de lifecycle.
- `GET /api/jobs/{job_id}/events?after=0&limit=100`: timeline paginada, 404 quando sem eventos.
- `GET /api/events?trace_id=...&after=0&limit=100`: eventos por trace/job; `next_cursor` segue ingestão, não relógio do produtor. Use enquanto `has_more`; uma página pode estar fora da ordem cronológica.
- `GET /api/hosts`: últimas amostras, `stale` e horário de recebimento.
- `GET /api/telemetry/status`: contagem, estados dos jobs, limites, últimos eventos por serviço.
- `GET /api/ecosystem`: health/stats Acessília, health/capabilities/providers Toolbox. Cache de 30 segundos, timeout 5 segundos, isolamento entre endpoints, limite de 1 MB por resposta. Não executa capabilities ou baixa documentos.
- `GET /api/integration`: referências da revisão e cobertura.

Exportação no painel baixa apenas os eventos carregados, explicitamente identificados como tal. Limite visual de 10.000 eventos por job; a API permanece paginada até a retenção. Eventos deletados por retenção não podem ser recuperados. IDs recebidos por caminho não viram SQL ou caminhos de disco.

## Coleta de host

`POST /api/ingest/hosts`, Bearer `OBS_HOST_TOKEN`, schema `HostSnapshot` em `events.py`. Relógio com timezone, diferença máxima de 5 minutos. No máximo 100 máquinas e 200 processos por amostra. Apenas PID/PPID, nome do executável, status, CPU, RSS, idade e serviço explicitamente mapeado. Sem cmdline, ambiente, usuário, caminhos ou socket Docker. Amostra mais antiga que a já armazenada não sobrescreve a nova. Nomes de processos podem refletir software instalado; acesso é protegido pelo mesmo token de leitura da central.

## Persistência e cobertura

SQLite WAL com transações; limites padrão 7 dias/100.000 eventos. A poda usa o timestamp do produtor para idade e a sequência para capacidade, com manutenção periódica mesmo sem ingestão. Há uma central por ambiente, com uma instância de Uvicorn e volume local; não compartilhe SQLite em NFS ou múltiplas máquinas. Banco/WAL devem ser protegidos e incluídos em backup consistente. A central não é uma fila de jobs nem uma autoridade sobre o estado do processo; perda de spans e workers encerrados são exibidos como lacunas, não sucesso presumido.

Redação é complementar: não existe filtro infalível para dados sensíveis em texto livre. Não emita prompts/documentos, parâmetros completos, URLs com credenciais, mensagens de exceptions ou nomes de arquivos do usuário. Emitir conteúdo não permitido é um erro de instrumentação. O envio OTLP opcional deve aplicar política própria de privacidade antes de instrumentar Agno: o OpenInference pode capturar mensagens e resultados fora deste contrato.
