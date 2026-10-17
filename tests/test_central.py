import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from frontend.app import create_app
from agno_observability_kit.events import Event, EventBatch, HostSnapshot
from agno_observability_kit.integrations.ecosystem import EcosystemClient
from agno_observability_kit.settings import ProjectConfig
from agno_observability_kit.store import EventStore


def event(number=1, **changes):
    return {'event_id':f'event-{number}', 'timestamp':datetime.now(timezone.utc).isoformat(),
            'service':'acessilia','job_id':'develop:job-1','message_id':'message-1','session_id':'session-1',
            'trace_id':'1'*32,'span_id':'2'*16,'parent_span_id':'','kind':'job','phase':'queue',
            'status':'queued','name':'Job na fila','attributes':{}, **changes}


def host(**changes):
    return {'host_id':'dev-host','timestamp':datetime.now(timezone.utc).isoformat(),'cpu_percent':20,
            'cpu_count':8,'memory_total_bytes':1000,'memory_used_bytes':500,'disk_percent':30,
            'process_count':1,'processes':[{'pid':123,'ppid':1,'name':'python','status':'running',
              'cpu_percent':5,'memory_bytes':100,'age_seconds':12,'service':'acessilia'}], **changes}


@pytest.fixture
def central(tmp_path, monkeypatch):
    for key,value in {'OBS_VIEW_TOKEN':'test-only-view-token','OBS_INGEST_TOKEN':'test-only-event-token','OBS_HOST_TOKEN':'test-only-host-token'}.items():
        monkeypatch.setenv(key,value)
    config = ProjectConfig(telemetry_db=str(tmp_path/'central.sqlite'))
    with TestClient(create_app(config)) as client:
        yield client


VIEW = {'Authorization':'Bearer test-only-view-token'}
WRITE = {'Authorization':'Bearer test-only-event-token'}
HOST = {'Authorization':'Bearer test-only-host-token'}


def test_token_scopes_and_private_validation(central):
    assert central.get('/api/jobs').status_code == 401
    assert central.get('/api/jobs',headers=WRITE).status_code == 401
    assert central.post('/api/ingest/events',headers=VIEW,json={'events':[event()]}).status_code == 401
    assert central.post('/api/ingest/hosts',headers=WRITE,json=host()).status_code == 401
    assert central.get('/healthz').json() == {'status':'ok'}
    assert central.post('/api/auth/login',json={'token':'错误'}).status_code == 401
    invalid = central.post('/api/ingest/events',headers=WRITE,json={'events':[event(prompt='private-document')]})
    assert invalid.status_code == 422 and 'private-document' not in invalid.text
    login = central.post('/api/auth/login',json={'token':'test-only-view-token'})
    assert login.status_code == 200 and 'HttpOnly' in login.headers['set-cookie'] and 'SameSite=strict' in login.headers['set-cookie']
    assert central.get('/api/jobs').status_code == 200
    assert central.get('/api/jobs').headers['cache-control'] == 'no-store'
    central.post('/api/auth/logout')
    assert central.get('/api/jobs').status_code == 401


def test_idempotence_out_of_order_and_child_success_does_not_complete_job(central):
    now = datetime.now(timezone.utc)
    root = event(2,status='running',phase='execution',timestamp=now.isoformat())
    older = event(1,timestamp=(now-timedelta(seconds=1)).isoformat())
    child = event(3,service='acessilia-toolbox',kind='span',status='succeeded',phase='tool',span_id='3'*16,parent_span_id='2'*16)
    assert central.post('/api/ingest/events',headers=WRITE,json={'events':[root,older,child]}).json()['accepted'] == 3
    assert central.post('/api/ingest/events',headers=WRITE,json={'events':[root]}).json() == {'accepted':0,'duplicates':1}
    jobs = central.get('/api/jobs',headers=VIEW).json()['jobs']
    assert len(jobs) == 1 and jobs[0]['status'] == 'running' and jobs[0]['event_count'] == 3
    first = central.get('/api/jobs/develop:job-1/events?limit=2',headers=VIEW).json()
    assert first['has_more'] and len(first['events']) == 2
    second = central.get(f"/api/jobs/develop:job-1/events?after={first['next_cursor']}",headers=VIEW).json()
    assert len(second['events']) == 1 and second['events'][0]['service'] == 'acessilia-toolbox'
    assert central.get('/api/events?trace_id='+'1'*32,headers=VIEW).json()['events'][0]['job_id'] == 'develop:job-1'
    assert central.get('/api/jobs/missing/events',headers=VIEW).status_code == 404
    assert central.get('/api/jobs?status=invalid',headers=VIEW).status_code == 422


def test_redaction_happens_before_persistence(central):
    payload = event(name='Bearer private-token user@example.test',attributes={'prompt':'never-store-this',
        'reason_code':'provider_unavailable','rationale':'token=private-value https://secret.test/private user@example.test'})
    central.post('/api/ingest/events',headers=WRITE,json={'events':[payload]})
    output = central.get('/api/events',headers=VIEW).text
    for secret in ['never-store-this','private-token','private-value','secret.test','user@example.test']:
        assert secret not in output
    assert 'provider_unavailable' in output
    with central.app.state.store.connection() as db:
        raw = db.execute('SELECT payload FROM events').fetchone()[0]
        assert 'never-store-this' not in raw and 'private-value' not in raw


def test_bounded_body_and_disabled_ingestion(central, monkeypatch):
    assert central.post('/api/ingest/events',headers=WRITE,content=b'x'*1_000_001).status_code == 413
    assert central.post('/api/ingest/events',headers=WRITE,json={'events':[event(i) for i in range(101)]}).status_code == 422
    monkeypatch.delenv('OBS_INGEST_TOKEN')
    assert central.post('/api/ingest/events',headers=WRITE,json={'events':[event()]}).status_code == 503
    assert central.post('/api/tests/runs',headers=VIEW,json={}).status_code == 404


def test_hosts_keep_newest_and_flag_stale(central):
    new = host()
    central.post('/api/ingest/hosts',headers=HOST,json=new)
    old = host(timestamp=(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat(),cpu_percent=99)
    central.post('/api/ingest/hosts',headers=HOST,json=old)
    result = central.get('/api/hosts',headers=VIEW).json()['hosts'][0]
    assert result['cpu_percent'] == 20 and result['stale'] is False
    old['host_id'] = 'old-host'
    central.post('/api/ingest/hosts',headers=HOST,json=old)
    assert central.get('/api/hosts',headers=VIEW).json()['hosts'][1]['stale'] is True
    assert central.post('/api/ingest/hosts',headers=HOST,json=host(processes=[{**new['processes'][0], 'cmdline':'secret'}])).status_code == 422


def test_restart_retention_and_capacity(tmp_path):
    path = str(tmp_path/'persistent.sqlite')
    store = EventStore(path,retention_days=1,max_events=100)
    store.ingest(EventBatch(events=[Event(**event(i)) for i in range(100)]))
    store.ingest(EventBatch(events=[Event(**event(101))]))
    assert store.summary()['event_count'] == 100
    assert EventStore(path).summary()['event_count'] == 100
    old = Event(**event(200,timestamp=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))
    store.ingest(EventBatch(events=[old]))
    assert not store.events(job_id='missing')['events']
    assert all(e['event_id'] != 'event-200' for e in store.events(limit=500)['events'])
    with store.connection() as db:
        db.execute('UPDATE events SET timestamp=?',(0,))
    store.prune()
    assert store.summary()['event_count'] == 0


def test_future_clock_and_zero_trace_are_rejected():
    for changes in [{'trace_id':'0'*32},{'timestamp':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}, {'timestamp':'2026-10-13T00:00:00'}]:
        with pytest.raises(ValidationError):
            Event(**event(**changes))


def test_readonly_ecosystem_isolated_failure_and_private_provider_data():
    calls=[]
    def respond(request):
        calls.append(request)
        assert request.method == 'GET'
        if request.url.host == 'acessilia.test':
            raise httpx.ConnectError('offline',request=request)
        if request.url.path.endswith('/health'):
            return httpx.Response(200,json={'status':'healthy','version':'1'})
        return httpx.Response(200,json=[{'id':'ocr','version':1,'api_key':'dont-forward','endpoint':'http://internal'}])
    config = ProjectConfig(acessilia_url='http://acessilia.test',toolbox_url='http://toolbox.test')
    client = EcosystemClient(config,httpx.MockTransport(respond))
    async def run():
        first = await client.snapshot()
        second = await client.snapshot()
        return first,second
    first,second=asyncio.run(run())
    assert first['acessilia']['state'] == 'unavailable'
    assert first['toolbox']['state'] == 'connected'
    assert 'dont-forward' not in json.dumps(first) and 'http://internal' not in json.dumps(first)
    assert len(calls) == 5 and first == second


def test_unconfigured_ecosystem_makes_no_requests():
    def fail(request):
        pytest.fail('Unconfigured services must not make network requests')
    response = asyncio.run(EcosystemClient(ProjectConfig(),httpx.MockTransport(fail)).snapshot())
    assert response['acessilia']['state'] == response['toolbox']['state'] == 'not_configured'


def test_model_metrics_only_count_terminal_spans_and_missing_is_unknown(central):
    assert central.get('/api/telemetry/status',headers=VIEW).json()['tokens_input'] is None
    start=event(1,kind='span',phase='model',status='running',attributes={'tokens_input':10})
    end=event(2,kind='span',phase='model',status='succeeded',attributes={'tokens_input':10,'tokens_output':5,'cost_usd':.25})
    central.post('/api/ingest/events',headers=WRITE,json={'events':[start,end]})
    result=central.get('/api/telemetry/status',headers=VIEW).json()
    assert result['tokens_input']==10 and result['tokens_output']==5 and result['cost_usd']==.25


def test_host_count_limit_is_atomic_under_concurrent_ingestion(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=EventStore(str(tmp_path/'hosts.sqlite'))
    for i in range(99):
        store.host(HostSnapshot(**host(host_id=f'host-{i}')))
    def ingest(index):
        try:
            store.host(HostSnapshot(**host(host_id=f'concurrent-{index}')))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(ingest,[1,2]))
    assert sum(results)==1 and len(store.hosts())==100


def test_job_activity_uses_recent_child_events_without_changing_status(tmp_path):
    import time
    store=EventStore(str(tmp_path/'active.sqlite'))
    store.ingest(EventBatch(events=[Event(**event(1,status='running'))]))
    with store.connection() as db:
        db.execute('UPDATE events SET received=?',(time.time()-600,))
    assert store.jobs()['jobs'][0]['stale'] is True
    store.ingest(EventBatch(events=[Event(**event(2,kind='span',phase='tool',status='succeeded'))]))
    result=store.jobs()['jobs'][0]
    assert result['status']=='running' and result['stale'] is False
