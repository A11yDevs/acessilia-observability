import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agno_observability_kit.client import Telemetry, Correlation, correlation_headers, correlation_from_headers
from agno_observability_kit.host_agent import HostSampler
from agno_observability_kit.events import ATTRIBUTE_KEYS


def test_sender_cross_service_context_and_failure_are_real_http():
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            assert self.headers['Authorization'] == 'Bearer test-only-token'
            received.extend(json.loads(self.rfile.read(int(self.headers['Content-Length'])))['events'])
            self.send_response(200); self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    telemetry=Telemetry('acessilia',url=f'http://127.0.0.1:{server.server_port}',token='test-only-token')
    remote=Telemetry('acessilia-toolbox',url=f'http://127.0.0.1:{server.server_port}',token='test-only-token')
    try:
        with pytest.raises(RuntimeError):
            with telemetry.job('job-1',message_id='message-1'):
                with telemetry.span('planning','Plano',dry_run=True):
                    telemetry.decision('planning','Escolha',reason_code='configured_backend',selected='internal')
                    headers={k.lower():v for k,v in correlation_headers().items()}
                    ctx=correlation_from_headers(headers)
                    with remote.bind(ctx):
                        remote.emit(kind='span',phase='tool',status='succeeded',name='Provider concluído')
                raise RuntimeError('private exception not exported')
        assert telemetry.flush() and remote.flush()
        assert not correlation_headers()
        roots=[e for e in received if e['kind']=='job']
        assert [e['status'] for e in roots] == ['running','failed']
        parent=[e for e in received if e['name']=='Plano'][0]
        child=[e for e in received if e['service']=='acessilia-toolbox'][0]
        assert child['trace_id']==parent['trace_id'] and child['parent_span_id']==parent['span_id']
        assert child['message_id']=='message-1'
        assert 'private exception' not in json.dumps(received)
    finally:
        telemetry.close();remote.close();server.shutdown();server.server_close()


def test_disabled_export_and_failure_never_mask_application_exception():
    telemetry=Telemetry('acessilia',url='',token='')
    with pytest.raises(ValueError,match='application-error'):
        with telemetry.job('job-1'):
            raise ValueError('application-error')
    assert not telemetry.enabled and telemetry.sent_events==0
    assert telemetry.close()


def test_context_isolation_concurrent_messages():
    telemetry=Telemetry('acessilia',url='',token='')
    async def observe(job):
        with telemetry.job(job):
            await asyncio.sleep(.01)
            return correlation_headers()['X-Obs-Job-Id']
    async def run():
        return await asyncio.gather(observe('job-a'),observe('job-b'))
    assert asyncio.run(run()) == ['job-a','job-b']
    assert not correlation_headers()


def test_bad_headers_do_not_become_identifiers():
    ctx=correlation_from_headers({'x-obs-job-id':'../../secret','traceparent':'00-'+'0'*32+'-'+'0'*16+'-01'})
    assert ctx.job_id != '../../secret' and ctx.parent_span_id == '' and ctx.trace_id != '0'*32


def test_host_sampler_collects_real_stats_without_sensitive_fields():
    snapshot=HostSampler('local-test').sample().model_dump()
    assert snapshot['cpu_count'] > 0 and snapshot['memory_total_bytes'] > 0
    assert snapshot['process_count'] >= len(snapshot['processes'])
    for process in snapshot['processes']:
        assert set(process) == {'pid','ppid','name','status','cpu_percent','memory_bytes','age_seconds','service'}


def test_large_unicode_events_split_into_bounded_batches_and_retry_ids_stay_same():
    received=[]; sizes=[]; requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            data=self.rfile.read(int(self.headers['Content-Length']))
            requests.append(data)
            if len(requests)==1:
                self.send_response(503);self.end_headers();return
            sizes.append(len(data));received.extend(json.loads(data)['events'])
            self.send_response(200 if len(data)<=1_000_000 else 413);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    telemetry=Telemetry('acessilia',url=f'http://127.0.0.1:{server.server_port}',token='test-only-token')
    attributes={key:'á'*1000 for key in ATTRIBUTE_KEYS - {'tokens_input','tokens_output','cost_usd','duration_ms','dropped_events'}}
    try:
        with telemetry.bind(Correlation('large-job','1'*32,'2'*16)):
            for i in range(100):
                assert telemetry.emit(kind='decision',phase='planning',status='succeeded',name=f'Large event {i}',attributes=attributes)
        assert telemetry.flush(timeout=10)
        assert len(received)==100 and len({event['event_id'] for event in received})==100
        assert max(sizes)<=1_000_000 and sum(sizes)>1_000_000 and requests[0]==requests[1]
        assert telemetry.dropped_events==0
    finally:
        telemetry.close();server.shutdown();server.server_close()
