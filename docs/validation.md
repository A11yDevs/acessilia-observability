# Validação desta configuração

Conferência em 13/10/2026, branch `feat/configure-acessilia-observability`.

- Referências das branches `develop`: Acessília `331e55935e89dda8fa33a684f69f0a45efeacf48`; Toolbox `64318eaeb9b358b5ea06137b85c2fdc310be66e1`. Os dois repositórios foram somente lidos.
- Pytest: **40 passed, 4 skipped**. Cobertura de autenticação por função, privacidade, ingestão idempotente, persistência, retenção, paginação, lifecycle, propagação de contexto, envio HTTP real do SDK, retry, Unicode, limites e concorrência.
- Os quatro testes opcionais ignorados requerem Agno live, Agno workflow, extra OTLP e stack Alloy Docker opt-in. Não foram apresentados como integrações verificadas.
- Chrome/Playwright: login, processos, seleção de job, linha do tempo e filtros; sem erros JavaScript. Larguras 320, 768, 1024 e 1440 px sem overflow horizontal da página. A tabela de processos permite rolagem própria.
- Docker: imagem construída; painel executado com usuário não-root, tokens de teste e volume temporário; leitura autenticada e guia acessíveis. Evento confirmado continuou presente após restart. Container e volume de teste removidos.
- Revisão independente Ponytail: três achados corrigidos e reconferidos, com regressões automatizadas — lotes limitados pelo tamanho UTF-8, limite de máquinas atômico e atividade recente do job considerando spans filhos. Nenhum achado concreto restante.
- Benchmark sintético do revisor: 100 mil eventos / 10 mil jobs; resumo 0,178 s, listagem de jobs 0,049 s, eventos 0,001 s e pruning 0,012 s nesta máquina. Não equivale a teste prolongado de carga concorrente.

Ainda requer validação após ativação: APIs reais, credenciais, instrumentação nas aplicações, providers/modelos reais e tracing OTLP. Consulte [o guia de integração](acessilia-integration.md) para o que criar e os critérios de aceite por mensagem. Os testes locais não comprovam o processamento real de documentos.
