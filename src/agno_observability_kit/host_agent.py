"""Run on the monitored Linux host. Reads process statistics, never arguments/env."""
import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

from agno_observability_kit.client import _NoRedirect
from agno_observability_kit.events import HostSnapshot


class HostSampler:
    def __init__(self, host_id, service_pids=None, psutil_module=None):
        if psutil_module is None:
            import psutil as psutil_module
        self.psutil = psutil_module
        self.host_id = host_id
        self.service_pids = service_pids or {}
        self.processes = {}
        self.psutil.cpu_percent()

    def sample(self):
        psutil = self.psutil
        rows, live = [], {}
        now = time.time()
        count = 0
        for process in psutil.process_iter():
            count += 1
            try:
                # Reusing Process instances preserves CPU sampling intervals.
                previous = self.processes.get(process.pid)
                if previous is not None and previous.create_time() == process.create_time():
                    process = previous
                live[process.pid] = process
                rows.append({'pid':process.pid, 'ppid':process.ppid(), 'name':process.name()[:80] or 'unknown',
                             'status':process.status()[:32], 'cpu_percent':max(0,process.cpu_percent()),
                             'memory_bytes':process.memory_info().rss, 'age_seconds':max(0,now-process.create_time()),
                             'service':self.service_pids.get(process.pid,'')})
            except (psutil.NoSuchProcess,psutil.AccessDenied,psutil.ZombieProcess):
                continue
        self.processes = live
        rows.sort(key=lambda row:(bool(row['service']),row['cpu_percent'],row['memory_bytes']),reverse=True)
        memory = psutil.virtual_memory()
        return HostSnapshot(host_id=self.host_id,timestamp=datetime.now(timezone.utc),cpu_percent=max(0,psutil.cpu_percent()),
            cpu_count=psutil.cpu_count() or 1, memory_total_bytes=memory.total,memory_used_bytes=memory.total-memory.available,
            disk_percent=psutil.disk_usage('/').percent,process_count=count,processes=rows[:200])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-id', default=os.getenv('OBS_HOST_ID',''))
    parser.add_argument('--interval', type=int, default=15)
    parser.add_argument('--once', action='store_true', help='Print a local snapshot without publishing')
    args = parser.parse_args()
    if not args.host_id or not 5 <= args.interval <= 300:
        parser.error('Set --host-id and an interval between 5 and 300 seconds')
    from agno_observability_kit.client import Telemetry
    url,token = os.getenv('OBS_CENTRAL_URL',''),os.getenv('OBS_HOST_TOKEN','')
    # Reuse destination URL validation without starting an event exporter.
    Telemetry('acessilia',url=url,token='')
    if not args.once and not (url and token):
        parser.error('Set OBS_CENTRAL_URL and OBS_HOST_TOKEN')
    pids = {}
    for assignment in os.getenv('OBS_SERVICE_PIDS','').split(','):
        if not assignment:
            continue
        name,sep,pid = assignment.partition('=')
        if not sep or name not in {'acessilia','acessilia-toolbox'} or not pid.isdigit() or int(pid) < 1:
            parser.error('OBS_SERVICE_PIDS format: acessilia=123,acessilia-toolbox=456')
        pids[int(pid)] = name
    sampler = HostSampler(args.host_id,pids)
    stopped = threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stopped.set())
    if args.once:
        stopped.wait(1)
        print(sampler.sample().model_dump_json(indent=2))
        return
    while not stopped.wait(args.interval):
        request = urllib.request.Request(url.rstrip('/')+'/api/ingest/hosts',data=sampler.sample().model_dump_json().encode(),
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.build_opener(_NoRedirect).open(request,timeout=5):
                pass
        except OSError as exc:
            print(f'Host export unavailable ({type(exc).__name__}); retry on next sample.',file=sys.stderr)


if __name__ == '__main__':
    main()
