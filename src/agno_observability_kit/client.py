"""Nonblocking application telemetry and explicit cross-service correlation."""
from __future__ import annotations

import asyncio
import contextvars
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.parse import urlparse

from agno_observability_kit.events import Event


@dataclass(frozen=True)
class Correlation:
    job_id: str
    trace_id: str
    span_id: str
    message_id: str = "unassigned"
    session_id: str = "unassigned"
    parent_span_id: str = ""


_current = contextvars.ContextVar('acessilia_observation', default=None)


def correlation_headers():
    ctx = _current.get()
    if not ctx:
        return {}
    return {'traceparent':f'00-{ctx.trace_id}-{ctx.span_id}-01', 'X-Obs-Job-Id':ctx.job_id,
            'X-Obs-Message-Id':ctx.message_id, 'X-Obs-Session-Id':ctx.session_id}


def correlation_from_headers(headers):
    def identifier(key):
        value = headers.get(key, '')
        return value if re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', value) else 'unassigned'
    trace = re.fullmatch(r'00-([a-f0-9]{32})-([a-f0-9]{16})-[a-f0-9]{2}', headers.get('traceparent',''))
    valid = trace and set(trace[1]) != {'0'} and set(trace[2]) != {'0'}
    return Correlation(job_id=identifier('x-obs-job-id') if identifier('x-obs-job-id') != 'unassigned' else uuid.uuid4().hex,
                       trace_id=trace[1] if valid else uuid.uuid4().hex, span_id=uuid.uuid4().hex[:16],
                       parent_span_id=trace[2] if valid else '', message_id=identifier('x-obs-message-id'),
                       session_id=identifier('x-obs-session-id'))


class Telemetry:
    def __init__(self, service, *, url=None, token=None, host_id=None, environment=None, capacity=1000):
        self.service = service
        self.url = (url if url is not None else os.getenv('OBS_CENTRAL_URL','')).rstrip('/')
        self.token = token if token is not None else os.getenv('OBS_INGEST_TOKEN','')
        self.host_id = host_id or os.getenv('OBS_HOST_ID','unassigned')
        self.environment = environment or os.getenv('OBS_ENVIRONMENT','develop')
        if self.url:
            parsed = urlparse(self.url)
            if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('OBS_CENTRAL_URL must be an HTTP(S) URL without credentials, query or fragment')
        if service not in {'acessilia','acessilia-toolbox'}:
            raise ValueError('Unsupported telemetry service')
        if type(capacity) is not int or not 1 <= capacity <= 10_000:
            raise ValueError('Telemetry capacity must be between 1 and 10000')
        self.enabled = bool(self.url and self.token)
        self.dropped_events = 0
        self.sent_events = 0
        self._queue = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._worker, daemon=True, name='acessilia-telemetry')
            self._thread.start()

    def emit(self, *, kind, phase, status, name, attributes=None, correlation=None):
        if not self.enabled or self._stop.is_set():
            return False
        ctx = correlation or _current.get()
        if ctx is None:
            self.dropped_events += 1
            return False
        try:
            event = Event(event_id=uuid.uuid4().hex, timestamp=datetime.now(timezone.utc),
                          service=self.service, host_id=self.host_id, environment=self.environment,
                          job_id=ctx.job_id, message_id=ctx.message_id, session_id=ctx.session_id,
                          trace_id=ctx.trace_id, span_id=ctx.span_id, parent_span_id=ctx.parent_span_id,
                          kind=kind, phase=phase, status=status, name=name,
                          attributes={**(attributes or {}), 'dropped_events':self.dropped_events})
            self._queue.put_nowait(event.model_dump_json().encode())
            return True
        except (ValueError, queue.Full, TypeError):
            self.dropped_events += 1
            return False

    @contextmanager
    def bind(self, correlation):
        marker = _current.set(correlation)
        try:
            yield correlation
        finally:
            _current.reset(marker)

    @contextmanager
    def job(self, job_id, *, message_id='unassigned', session_id='unassigned', correlation=None):
        ctx = correlation or Correlation(job_id, uuid.uuid4().hex, uuid.uuid4().hex[:16], message_id, session_id)
        with self.bind(ctx):
            self.emit(kind='job', phase='execution', status='running', name='Job iniciado')
            started = time.monotonic()
            try:
                yield ctx
            except BaseException as exc:
                cancelled = isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) or type(exc).__name__ == 'TaskCancelledError'
                self.emit(kind='job', phase='execution', status='cancelled' if cancelled else 'failed', name='Job interrompido',
                          attributes={'error_type':type(exc).__name__, 'duration_ms':(time.monotonic()-started)*1000})
                raise
            else:
                self.emit(kind='job', phase='delivery', status='succeeded', name='Job concluído',
                          attributes={'duration_ms':(time.monotonic()-started)*1000})

    @contextmanager
    def span(self, phase, name, **attributes):
        parent = _current.get()
        if not parent:
            yield None
            return
        ctx = replace(parent, span_id=uuid.uuid4().hex[:16], parent_span_id=parent.span_id)
        with self.bind(ctx):
            self.emit(kind='span',phase=phase,status='running',name=name,attributes=attributes)
            started = time.monotonic()
            try:
                yield ctx
            except BaseException as exc:
                self.emit(kind='span',phase=phase,status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed',name=name,
                          attributes={**attributes,'error_type':type(exc).__name__,'duration_ms':(time.monotonic()-started)*1000})
                raise
            else:
                self.emit(kind='span',phase=phase,status='succeeded',name=name,
                          attributes={**attributes,'duration_ms':(time.monotonic()-started)*1000})

    def decision(self, phase, name, *, reason_code, selected, alternatives=(), **attributes):
        return self.emit(kind='decision',phase=phase,status='succeeded',name=name,
                         attributes={**attributes,'reason_code':reason_code,'selected':selected,'alternatives':list(alternatives)})

    def _worker(self):
        pending = None
        while not self._stop.is_set() or not self._queue.empty() or pending is not None:
            try:
                first = pending if pending is not None else self._queue.get(timeout=.1)
                pending = None
            except queue.Empty:
                continue
            batch = [first]
            size = len(b'{"events":[]}') + len(first)
            while len(batch) < 100:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if size + 1 + len(item) > 1_000_000:
                    pending = item
                    break
                batch.append(item)
                size += 1 + len(item)
            body = b'{"events":[' + b','.join(batch) + b']}'
            delivered = False
            for attempt in range(2):
                request = urllib.request.Request(self.url+'/api/ingest/events', data=body,
                    headers={'Authorization':'Bearer '+self.token, 'Content-Type':'application/json'}, method='POST')
                try:
                    # No redirects: a misconfigured collector must never forward its bearer token.
                    opener = urllib.request.build_opener(_NoRedirect)
                    with opener.open(request, timeout=2) as response:
                        delivered = response.status == 200
                    if delivered:
                        break
                except urllib.error.HTTPError as exc:
                    if exc.code < 500:
                        break
                except (urllib.error.URLError, OSError):
                    pass
                if attempt == 0:
                    self._stop.wait(.1)
            if delivered:
                self.sent_events += len(batch)
            else:
                self.dropped_events += len(batch)
            for _ in batch:
                self._queue.task_done()

    def flush(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.01)
        return self._queue.unfinished_tasks == 0 and self.dropped_events == 0

    def close(self, timeout=5):
        flushed = self.flush(timeout)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        return flushed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ObservationMiddleware:
    """HTTP span only: accepted requests are not falsely reported as completed jobs."""
    def __init__(self, app, telemetry):
        self.app, self.telemetry = app, telemetry

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in {'GET','HEAD','OPTIONS'}:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
        correlation = correlation_from_headers(headers)
        phase = 'tool' if self.telemetry.service == 'acessilia-toolbox' else 'intake'
        status_code = 500
        async def observed_send(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
                message = {**message, 'headers':list(message.get('headers',[])) + [(b'x-obs-trace-id',correlation.trace_id.encode())]}
            await send(message)
        with self.telemetry.bind(correlation):
            self.telemetry.emit(kind='span',phase=phase,status='running',name='Requisição HTTP',attributes={'operation':scope['method']})
            started = time.monotonic()
            try:
                await self.app(scope,receive,observed_send)
            except BaseException as exc:
                self.telemetry.emit(kind='span',phase=phase,status='cancelled' if isinstance(exc,asyncio.CancelledError) else 'failed',name='Requisição interrompida',attributes={'error_type':type(exc).__name__})
                raise
            else:
                self.telemetry.emit(kind='span',phase=phase,status='failed' if status_code >= 400 else 'succeeded',name='Requisição HTTP',
                                    attributes={'http_status':status_code,'duration_ms':(time.monotonic()-started)*1000})
