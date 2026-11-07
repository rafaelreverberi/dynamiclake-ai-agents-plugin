"""Opt-in, current-user hook IPC. No TCP listener and no event persistence."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import socketserver
import stat
import threading
import time
from agent_models import AgentPermissionRequest, AgentSession, short, claude_quota_snapshots
from agent_providers import operation, Timeline

MAX_MESSAGE = 64_000


def bridge_path():
    return Path(os.environ.get('AI_AGENTS_BRIDGE_DIR', str(Path.home() / 'Library/Application Support/DynamicLake-AI-Agents'))) / 'hooks.sock'


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise PermissionError('Hook directory must be owned by this user with mode 0700')


def normalize_event(value):
    provider = value.get('provider')
    if provider not in ('claude','codex'):
        raise ValueError('Unsupported hook provider')
    event = value.get('event')
    raw = value.get('data')
    if not isinstance(raw, dict):
        raise ValueError('Missing hook data')
    allowed = {'claude': {'SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','PermissionRequest','Stop','SessionEnd','Usage'},
               'codex': {'PermissionRequest'}}
    if event not in allowed[provider]:
        raise ValueError('Unknown hook event')
    session = raw.get('session_id')
    if not isinstance(session, str) or not 1 <= len(session) <= 200:
        raise ValueError('Missing session identifier')
    if event=='Usage':
        return {'provider':'claude','event':'Usage','session':session,'usage':claude_quota_snapshots(raw)}
    cwd = raw.get('cwd') or ''
    tool = short(raw.get('tool_name'), 70)
    inputs = raw.get('tool_input')
    label, file, add, delete = operation(tool, inputs)
    preview = ''
    if event == 'PermissionRequest':
        # Only memory, only for explicit permission review; no tool input is executed here.
        preview = json.dumps(inputs, ensure_ascii=True, separators=(',', ':')) if isinstance(inputs, dict) else ''
        if not preview or len(preview) > 1500:
            # Never approve from an incomplete action preview.
            raise ValueError('Action too large; review in agent')
    return {'provider': provider, 'event': event, 'session': session, 'project': short(Path(str(cwd)).name),
            'tool': tool, 'label': label, 'file': file, 'additions': add, 'deletions': delete,
            'turn':short(raw.get('turn_id') or raw.get('prompt_id'),200),
            'call': short(raw.get('tool_use_id'), 200), 'preview': preview,
            'interrupted':raw.get('status') in ('aborted','interrupted'),
            'failed': event in ('PostToolUseFailure',) or raw.get('status') == 'error'}


class HookBridge:
    def __init__(self, approvals=lambda: False, usage_enabled=lambda: False, events_enabled=lambda: True,
                 codex_approvals=lambda: False):
        self.approvals = approvals
        self.usage_enabled=usage_enabled
        self.events_enabled=events_enabled
        self.codex_approvals=codex_approvals
        self.usage=[]
        self.events = queue.Queue(maxsize=256)
        self.pending = {}
        self.lock = threading.Lock()
        self.sessions = {}
        self.timelines = {}
        self.server = None
        self.path = bridge_path()
        self.health = 'Disabled'
        self.usage=[]
        self.slots = threading.BoundedSemaphore(24)

    def start(self):
        private_directory(self.path.parent)
        if self.path.exists() or self.path.is_symlink():
            # Never unlink an active listener (including another plugin instance).
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.settimeout(.2)
                probe.connect(str(self.path))
            except (ConnectionRefusedError, FileNotFoundError):
                if not stat.S_ISSOCK(self.path.lstat().st_mode):
                    raise PermissionError('Hook path is not a socket')
                self.path.unlink()
            else:
                raise OSError('Hook bridge is already running')
            finally:
                probe.close()
        bridge = self

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
            def process_request(self, request, address):
                if not bridge.slots.acquire(blocking=False):
                    request.close()
                    return
                try:
                    super().process_request(request, address)
                except Exception:
                    bridge.slots.release()
                    raise
            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    bridge.slots.release()
            def handle_error(self, request, address):
                pass  # Never print hook payloads or paths from exceptions.

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                permission = None
                try:
                    raw = self.rfile.readline(MAX_MESSAGE + 1)
                    if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
                        raise ValueError('Oversized hook frame')
                    event = normalize_event(json.loads(raw))
                    if ((event['provider']!='claude' and not bridge.approval_enabled(event['provider']))
                        or (event['event']=='Usage' and not bridge.usage_enabled())
                        or (event['provider']=='claude' and event['event']!='Usage' and not bridge.events_enabled())):
                        self.wfile.write(b'{}\n')
                        return
                    if event['event'] == 'PermissionRequest' and bridge.approval_enabled(event['provider']):
                        with bridge.lock:
                            if len(bridge.pending) >= 16:
                                raise ValueError('Permission queue full')
                            signal = threading.Event()
                            permission = AgentPermissionRequest(secrets.token_hex(24), event['provider'], event['session'], event['tool'], event['project'], event['preview'], time.monotonic()+90, signal)
                            bridge.pending[permission.id] = permission
                        event['permission'] = permission.id
                    bridge.events.put_nowait(event)
                    if permission:
                        # Check peer liveness: cancelled native prompts must lose their action buttons.
                        while not permission.transport.wait(.2):
                            if time.monotonic() >= permission.deadline:
                                break
                            self.request.setblocking(False)
                            try:
                                if self.request.recv(1, socket.MSG_PEEK) == b'':
                                    break
                            except BlockingIOError:
                                pass
                            finally:
                                self.request.settimeout(2)
                        decision = permission.decision if time.monotonic() < permission.deadline else None
                        response = {'decision': decision} if decision else {}
                    else:
                        response = {}
                    self.wfile.write(json.dumps(response).encode() + b'\n')
                    self.wfile.flush()
                except (OSError, ValueError, TypeError, queue.Full):
                    try:
                        self.wfile.write(b'{}\n')
                    except OSError:
                        pass
                finally:
                    if permission:
                        with bridge.lock:
                            bridge.pending.pop(permission.id, None)
        self.server = Server(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.health = 'Listening · current user only'

    def permissions(self):
        with self.lock:
            return [p for p in self.pending.values() if p.deadline > time.monotonic() and p.decision is None]

    def approval_enabled(self,provider):
        return {'claude':self.approvals,'codex':self.codex_approvals}[provider]()

    def decide(self, request_id, decision):
        if decision not in ('allow', 'deny'):
            return False
        with self.lock:
            p = self.pending.get(request_id)
            if not p or p.decision or p.deadline <= time.monotonic() or not self.approval_enabled(p.provider):
                return False
            p.decision = decision
            p.transport.set()
            return True

    def cancel_permissions(self,provider=None):
        with self.lock:
            for p in self.pending.values():
                if provider and p.provider!=provider:
                    continue
                p.decision = None
                p.deadline = 0
                p.transport.set()

    def drain(self):
        for _ in range(256):
            try:
                e = self.events.get_nowait()
            except queue.Empty:
                break
            if e['event']=='Usage':
                self.usage=e['usage'] if self.usage_enabled() else []
                continue
            key = (e['provider'], e['session'])
            timeline = self.timelines.setdefault(key, Timeline())
            event = e['event']
            if event in ('UserPromptSubmit',):
                timeline.steps.clear()
            if event in ('PreToolUse',):
                timeline.start(e['call'], e['tool'], {})
                if timeline.steps and timeline.steps[-1].id == e['call']:
                    s = timeline.steps[-1]
                    s.label,s.file_name,s.additions,s.deletions = e['label'],e['file'],e['additions'],e['deletions']
            if event in ('PostToolUse','PostToolUseFailure'):
                timeline.finish(e['call'], e['failed'])
            phase = 'interrupted' if e['interrupted'] else ('failed' if e['failed'] else ('completed' if event in ('Stop',) else ('paused' if event in ('SessionEnd','SessionStart') else 'tool')))
            if event == 'PermissionRequest':
                phase = 'permission'
            previous_turn = self.sessions[key].turn_id if key in self.sessions else None
            turn = e['turn'] or (str(time.time_ns()) if event in ('UserPromptSubmit',) else previous_turn)
            self.sessions[key] = AgentSession(e['provider'], e['session'], e['project'], phase,
                'Waiting for permission' if phase == 'permission' else ('Complete' if phase == 'completed' else e['label']), time.time(), list(timeline.steps), turn_id=turn)
        if len(self.sessions)>256:
            protected={(p.provider,p.session_id) for p in self.permissions()}
            removable=sorted((k for k in self.sessions if k not in protected),key=lambda k:self.sessions[k].updated_at)
            for key in removable[:len(self.sessions)-256]:
                self.sessions.pop(key,None)
                self.timelines.pop(key,None)
        # Only live hook requests keep a session pinned. Native prompt fallback can go stale.
        pending = {(p.provider,p.session_id):p.id for p in self.permissions()}
        for key,s in list(self.sessions.items()):
            s.permission_id = pending.get(key)
            if key[0]!='claude' and not s.permission_id:
                self.sessions.pop(key,None)
                self.timelines.pop(key,None)
                continue
            if time.time() - s.updated_at > 600 and not s.permission_id:
                self.sessions.pop(key, None)
                self.timelines.pop(key, None)
        return list(self.sessions.values())

    def close(self):
        self.cancel_permissions()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.path.unlink(missing_ok=True)
        self.health = 'Disabled'
        self.usage=[]
