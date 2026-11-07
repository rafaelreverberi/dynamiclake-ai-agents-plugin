"""Opt-in account quota reads via the official Codex app-server protocol."""
import json
import os
import selectors
import shutil
import subprocess
import threading
import time
from agent_models import quota_snapshots


def read_codex_quota(timeout=12, cancel=None):
    binary = shutil.which('codex')
    if not binary:
        raise OSError('Codex CLI unavailable')
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    process = subprocess.Popen([binary, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b''
    deadline = time.monotonic() + timeout
    def send(value):
        process.stdin.write(json.dumps(value).encode()+b'\n')
        process.stdin.flush()
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'dynamiclake_ai_agents','version':'2.0.0-beta.3'}}})
        initialized = False
        while time.monotonic() < deadline and not (cancel and cancel.is_set()):
            if not selector.select(.2):
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > 256_000:
                raise ValueError('Account response too large')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n',1)
                value = json.loads(line)
                if value.get('id') == 1 and 'result' in value and not initialized:
                    initialized = True
                    send({'method':'initialized'})
                    send({'id':2,'method':'account/rateLimits/read'})
                elif value.get('id') == 2:
                    if 'error' in value:
                        raise ValueError('Quota unavailable for this account')
                    return quota_snapshots(value.get('result',{}))
        raise TimeoutError('Account read timed out')
    finally:
        selector.close()
        process.stdin.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()


class UsageMonitor:
    def __init__(self):
        self.snapshots=[]
        self.health='Disabled'
        self.status={'codex':'Disabled','opencode':'Disabled'}
        self.last_attempt={'codex':-1000,'opencode':-1000}
        self.workers={}
        self.generation=0
        self.cancel=threading.Event()
        self.lock=threading.Lock()

    @property
    def worker(self):
        return self.workers.get('codex')

    def refresh(self,enabled,force=False,provider=None):
        if not enabled:
            self.cancel.set()
            with self.lock:
                if self.health!='Disabled':self.generation+=1
                self.snapshots=[];self.health='Disabled'
                self.status={key:'Disabled' for key in self.status}
            return
        self.cancel.clear()
        readers={'codex':read_codex_quota,'opencode':read_opencode_quota}
        for key,reader in readers.items():
            if provider and provider!=key:continue
            running=self.workers.get(key)
            if running and running.is_alive():continue
            if not force and time.monotonic()-self.last_attempt[key]<300:continue
            self.last_attempt[key]=time.monotonic()
            generation=self.generation
            def work(key=key,reader=reader,generation=generation):
                try:
                    values=reader(cancel=self.cancel)
                    with self.lock:
                        if generation==self.generation:
                            self.snapshots=[v for v in self.snapshots if v.provider!=key]+values
                            self.status[key]='Connected' if values else 'No quota data returned'
                except FileNotFoundError:
                    if generation==self.generation:self.status[key]='CLI not installed'
                except (OSError,ValueError,TimeoutError):
                    if generation==self.generation:self.status[key]='Usage unavailable; check sign-in or CLI version'
            self.status[key]='Checking usage…'
            worker=threading.Thread(target=work,daemon=True)
            self.workers[key]=worker;worker.start()
        self.health='Account usage'

    def close(self):
        with self.lock:self.generation+=1
        self.cancel.set()
        for worker in self.workers.values():
            if worker.is_alive():worker.join(timeout=2)


def opencode_binary():
    from pathlib import Path
    candidate=Path('/Applications/OpenCode.app/Contents/Resources/opencode-cli')
    return str(candidate) if candidate.is_file() else shutil.which('opencode')


def read_opencode_quota(timeout=20,cancel=None):
    """Ask OpenCode itself; never open auth stores or guess a remote private API."""
    import signal
    import tempfile
    from agent_models import opencode_quota_snapshots
    if cancel and cancel.is_set():raise TimeoutError('OpenCode usage read cancelled')
    binary=opencode_binary()
    if not binary:raise FileNotFoundError('OpenCode CLI unavailable')
    # A private CLI-owned server avoids starting/reconfiguring the user's managed service.
    with tempfile.TemporaryDirectory(prefix='dynamiclake-usage-') as cwd:
        process=subprocess.Popen([binary,'api','experimental.usage.limits','--standalone'],cwd=cwd,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
        data=bytearray();deadline=time.monotonic()+timeout
        try:
            while time.monotonic()<deadline and not (cancel and cancel.is_set()):
                if not selector.select(.2):
                    if process.poll() is not None:break
                    continue
                chunk=os.read(process.stdout.fileno(),65536)
                if not chunk:break
                data.extend(chunk)
                if len(data)>1_000_000:raise ValueError('OpenCode quota response too large')
            if process.poll() is None:
                try:process.wait(timeout=.2)
                except subprocess.TimeoutExpired:raise TimeoutError('OpenCode quota read timed out')
            if cancel and cancel.is_set():raise TimeoutError('OpenCode quota read cancelled')
            if process.returncode:raise ValueError('OpenCode usage API unavailable')
            return opencode_quota_snapshots(json.loads(data))
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
            process.stdout.close()
