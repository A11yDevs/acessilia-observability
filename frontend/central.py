"""Authenticated telemetry ingestion and read-only investigation routes."""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from agno_observability_kit.events import EventBatch, HostSnapshot, Identifier, Status, Service
from agno_observability_kit.integrations.ecosystem import EcosystemClient


def token_equal(supplied, expected):
    return secrets.compare_digest(supplied.encode(), expected.encode())


def token_required(variable):
    def authenticate(request: Request):
        expected = os.getenv(variable, "")
        if not expected:
            raise HTTPException(503, f"Configure {variable} no servidor.")
        if not token_equal(request.headers.get("authorization", ""), f"Bearer {expected}"):
            raise HTTPException(401, "Credencial inválida.", headers={"WWW-Authenticate": "Bearer"})
    return authenticate


class BodyLimit:
    """Bound chunked requests too, before validation can allocate an unbounded body."""
    def __init__(self, app, maximum=1_000_000):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST','PUT','PATCH'}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.maximum:
                return await JSONResponse({'detail': 'Corpo excede 1 MB.'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request', 'body':bytes(body), 'more_body':False}
            return await receive()
        await self.app(scope, replay, send)


def central_routes(config, store):
    router = APIRouter()
    client = EcosystemClient(config)

    @router.post('/api/auth/login')
    async def login(request: Request):
        expected = os.getenv('OBS_VIEW_TOKEN', '')
        try:
            token = (await request.json()).get('token', '')
        except (ValueError, AttributeError):
            token = ''
        if not expected or not isinstance(token, str) or not token_equal(token, expected):
            raise HTTPException(401, 'Credencial inválida.')
        response = JSONResponse({'authenticated':True})
        response.set_cookie('obs_session', token, httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=86400)
        return response

    @router.post('/api/auth/logout')
    def logout():
        response = JSONResponse({'authenticated':False})
        response.delete_cookie('obs_session')
        return response

    @router.get('/healthz')
    def health():
        return {'status':'ok'}

    @router.post('/api/ingest/events', dependencies=[Depends(token_required('OBS_INGEST_TOKEN'))])
    def ingest(batch: EventBatch):
        accepted = store.ingest(batch)
        return {'accepted':accepted, 'duplicates':len(batch.events) - accepted}

    @router.post('/api/ingest/hosts', dependencies=[Depends(token_required('OBS_HOST_TOKEN'))])
    def hosts_ingest(snapshot: HostSnapshot):
        try:
            store.host(snapshot)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'accepted':True}

    @router.get('/api/ecosystem')
    async def ecosystem():
        return await client.snapshot()

    @router.get('/api/jobs')
    def jobs(status: Status | None = None, service: Service | None = None,
             q: str = Query('', max_length=128), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1_000_000)):
        return store.jobs(status or '', service or '', q, limit, offset)

    @router.get('/api/events')
    def events(job_id: Identifier | None = None, trace_id: str = Query('', pattern=r'^(?:[a-f0-9]{32})?$'),
               after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        return store.events(job_id=job_id, trace_id=trace_id, after=after, limit=limit)

    @router.get('/api/jobs/{job_id}/events')
    def job_events(job_id: Identifier, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        result = store.events(job_id=job_id, after=after, limit=limit)
        if not result['events'] and after == 0:
            raise HTTPException(404, 'Job sem eventos no período de retenção.')
        return result

    @router.get('/api/hosts')
    def hosts():
        return {'hosts':store.hosts(config.host_stale_seconds)}

    @router.get('/api/telemetry/status')
    def telemetry():
        return {**store.summary(), 'ingest_configured':bool(os.getenv('OBS_INGEST_TOKEN')),
                'host_ingest_configured':bool(os.getenv('OBS_HOST_TOKEN')),
                'viewer_protected':bool(os.getenv('OBS_VIEW_TOKEN')),
                'test_console_enabled':config.enable_test_console}

    @router.get('/api/integration')
    def integration():
        return {
            'revisions':{'acessilia':'331e55935e89dda8fa33a684f69f0a45efeacf48','acessilia-toolbox':'64318eaeb9b358b5ea06137b85c2fdc310be66e1'},
            'phases':['intake','queue','cache','manifest','media_inspect','enrichment','planning','execution','validation','export','delivery'],
            'guide':'/docs/integration',
            'coverage':'Eventos explícitos e decisões operacionais emitidas. Etapas não instrumentadas não são inferidas.',
            'pipeline_notes':['AgentOS é um showcase separado do pipeline.','A develop contém handlers no-op e execução dry-run; registre dry_run e noop.','Não existe listagem global de jobs na API atual; publique eventos no worker.'],
        }

    return router
