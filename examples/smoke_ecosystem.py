"""Publish a labelled synthetic contract test; never invokes models or the Toolbox."""
import uuid

from agno_observability_kit.client import Correlation, Telemetry, correlation_headers, correlation_from_headers


def main():
    acessilia = Telemetry('acessilia')
    toolbox = Telemetry('acessilia-toolbox')
    if not acessilia.enabled:
        raise SystemExit('Set OBS_CENTRAL_URL and OBS_INGEST_TOKEN for the central under test.')
    ctx = Correlation('smoke-'+uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex[:16], 'synthetic-message', 'synthetic-session')
    try:
        acessilia.emit(kind='job',phase='queue',status='queued',name='TESTE SINTÉTICO · fila',correlation=ctx)
        with acessilia.job(ctx.job_id,correlation=ctx):
            with acessilia.span('planning','TESTE SINTÉTICO · planejamento',dry_run=True):
                acessilia.decision('planning','TESTE SINTÉTICO · escolha',reason_code='contract_smoke_only',selected='internal',alternatives=['internal'],dry_run=True)
            with acessilia.span('tool','TESTE SINTÉTICO · chamada Toolbox',capability='document.structure.extract'):
                headers = {key.lower():value for key,value in correlation_headers().items()}
                with toolbox.bind(correlation_from_headers(headers)):
                    toolbox.emit(kind='span',phase='tool',status='running',name='TESTE SINTÉTICO · entrada Toolbox')
                    with toolbox.span('execution','TESTE SINTÉTICO · provider',provider='synthetic',dry_run=True):
                        toolbox.decision('cache','TESTE SINTÉTICO · cache',reason_code='synthetic_cache_miss',selected='execute',cache_hit=False)
                    toolbox.emit(kind='span',phase='tool',status='succeeded',name='TESTE SINTÉTICO · entrada Toolbox')
            acessilia.emit(kind='span',phase='validation',status='skipped',name='TESTE SINTÉTICO · sem validação real',attributes={'dry_run':True,'noop':True})
        print(f'Synthetic contract test job: {ctx.job_id}')
    finally:
        acessilia.close(); toolbox.close()
    if acessilia.dropped_events or toolbox.dropped_events:
        raise SystemExit('Export failed: inspect destination URL, token and central health.')


if __name__ == '__main__':
    main()
