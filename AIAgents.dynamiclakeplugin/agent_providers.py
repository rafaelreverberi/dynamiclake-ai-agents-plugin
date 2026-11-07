"""Bounded, incremental local metadata adapters. Provider files are read-only."""
from __future__ import annotations
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from agent_models import AgentSession, AgentTaskStep, AgentCapabilities, short

MAX_READ = 512_000
MAX_LINE = 220_000
MAX_SESSIONS = 64


def obj(line):
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def operation(name, inputs):
    """Retain only a basename and factual operation; discard prompts/output/commands."""
    inputs = inputs if isinstance(inputs, dict) else obj(inputs)
    name = str(name or '').split('.')[-1]
    file = short(Path(str(inputs.get('file_path') or inputs.get('path') or inputs.get('filePath') or '')).name, 70)
    labels = {'Read': 'Read file', 'read': 'Read file', 'Edit': 'Edit file', 'edit': 'Edit file',
              'Write': 'Write file', 'write': 'Write file', 'Bash': 'Run command', 'Shell': 'Run command',
              'shell':'Run command','terminal':'Run command','command':'Run command','exec':'Run command','exec_command': 'Run command', 'shell_command': 'Run command', 'bash': 'Run command',
              'apply_patch': 'Edit files', 'Grep': 'Search code', 'Glob': 'Find files', 'grep': 'Search code',
              'read_file': 'Read file', 'write_file': 'Write file', 'edit_file': 'Edit file',
              'list_files':'List files', 'search':'Search code', 'view_image':'Inspect image',
              'web__run':'Browse web', 'request_user_input_async':'Request input', 'update_plan':'Update plan'}
    label = labels.get(name, 'Run tool')
    # No shell preview: arguments can contain secrets even in ordinary builds.
    if file and label in ('Read file', 'Edit file', 'Write file'):
        label = label.replace('file', file)
    additions = deletions = None
    old=inputs.get('old_string',inputs.get('oldString'))
    new=inputs.get('new_string',inputs.get('newString'))
    if name in ('Edit','edit') and isinstance(old,str) and isinstance(new,str):
        additions=len(new.splitlines())
        deletions=len(old.splitlines())
    return label, file, additions, deletions


class Timeline:
    def __init__(self):
        self.steps = []
        self.codex_items = False

    def start(self, call_id, name, inputs):
        if not isinstance(call_id, str) or not call_id or any(s.id == call_id for s in self.steps):
            return
        label, file, added, deleted = operation(name, inputs)
        self.steps.append(AgentTaskStep(call_id, label, 'running', file, added, deleted))
        self.steps = self.steps[-8:]

    def finish(self, call_id, failed=False, known=True):
        for step in self.steps:
            if step.id == call_id:
                step.status = 'failed' if failed else ('completed' if known else 'observed')

    def codex_completed_item(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            return
        self.codex_items = True
        kind, item_id = item.get('type'), item['id']
        if kind == 'FileChange':
            changes = item.get('changes')
            if item.get('status') != 'completed' or not isinstance(changes, dict):
                return
            added = removed = 0
            for change in changes.values():
                if not isinstance(change, dict):
                    continue
                change_type = change.get('type')
                content = change.get('content')
                if isinstance(content, str):
                    if change_type == 'add':
                        added += len(content.splitlines())
                    elif change_type == 'delete':
                        removed += len(content.splitlines())
                diff = change.get('unified_diff')
                if change_type == 'update' and isinstance(diff, str):
                    in_hunk = False
                    for line in diff.splitlines():
                        if line.startswith('@@ '):
                            in_hunk = True
                        elif in_hunk:
                            added += line.startswith('+')
                            removed += line.startswith('-')
            step_id = 'codex-file-change:'+item_id
            if not any(step.id == step_id for step in self.steps):
                self.steps = [*self.steps,AgentTaskStep(step_id,'Edit files','completed',additions=added,deletions=removed)][-8:]
            return
        if kind == 'CommandExecution':
            parsed = item.get('parsed_cmd')
            commands = parsed[:8] if isinstance(parsed, list) else []
            operations = [
                (command['type'], {'path': command.get('path') or command.get('name')})
                for command in commands
                if isinstance(command, dict) and command.get('type') in ('read', 'search', 'list_files')
            ] or [('exec_command', {})]
        elif kind == 'ImageView':
            operations = [('view_image', {})]
        elif kind == 'McpToolCall':
            operations = [(item.get('tool'), {})]
        else:
            return
        outcome = item.get('status')
        code = item.get('exit_code')
        failed = outcome == 'failed' or (type(code) is int and code != 0)
        for index, (name, inputs) in enumerate(operations):
            step_id = f'codex-item:{item_id}:{index}'
            self.start(step_id, name, inputs)
            self.finish(step_id, failed=failed, known=outcome=='completed' or type(code) is int or kind=='ImageView')

    def consume(self, provider, record):
        p = record.get('payload', {})
        if not isinstance(p, dict):
            return
        if provider == 'codex':
            if record.get('type') == 'event_msg' and p.get('type') == 'task_started':
                self.steps.clear()
            elif record.get('type') == 'event_msg' and p.get('type') == 'item_completed':
                self.codex_completed_item(p.get('item'))
            if record.get('type') == 'response_item':
                kind = p.get('type')
                if kind in ('function_call', 'custom_tool_call'):
                    name = p.get('name')
                    if self.codex_items and (name=='exec' or p.get('namespace')=='mcp__cua_repl'):
                        return
                    self.start(p.get('call_id'), name, p.get('arguments', p.get('input')))
                elif kind in ('function_call_output', 'custom_tool_call_output'):
                    output = p.get('output')
                    # A returned tool result is not necessarily success.
                    parsed = obj(output) if isinstance(output, str) else (output if isinstance(output, dict) else {})
                    code = parsed.get('exit_code')
                    self.finish(p.get('call_id'), failed=isinstance(code, int) and code != 0, known=isinstance(code, int))
        elif provider == 'claude' and not record.get('isSidechain'):
            message = record.get('message', {})
            if not isinstance(message, dict):
                return
            content = message.get('content', [])
            if not isinstance(content, list):
                return
            if record.get('type') == 'user' and not any(isinstance(c, dict) and c.get('type') == 'tool_result' for c in content):
                self.steps.clear()
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get('type') == 'tool_use':
                    self.start(c.get('id'), c.get('name'), c.get('input'))
                if c.get('type') == 'tool_result':
                    self.finish(c.get('tool_use_id'), c.get('is_error') is True)


class IncrementalSession:
    def __init__(self, path, provider, legacy):
        self.path, self.provider, self.legacy = path, provider, legacy
        self.offset = 0
        self.inode = None
        self.modified = None
        self.parser = None
        self.timeline = Timeline()
        self.pending = b''
        self.dropping = False
        self.bytes_read = 0
        self.turn_id = None
        self.cached_state = None

    def read(self):
        stat = self.path.stat()
        if self.cached_state is not None and stat.st_ino == self.inode and stat.st_size == self.offset and stat.st_mtime_ns == self.modified:
            return self.cached_state
        reset = self.parser is None or self.inode != stat.st_ino or stat.st_size < self.offset or (stat.st_size == self.offset and self.modified != stat.st_mtime_ns)
        if reset:
            self.parser = self.legacy.CodexSessionParser() if self.provider == 'codex' else self.legacy.ClaudeSessionParser(self.path)
            self.timeline = Timeline()
            self.turn_id = None
            self.pending = b''
            self.offset = 0
            self.dropping = False
            if stat.st_size > MAX_READ:
                with self.path.open('rb') as stream:
                    header = stream.read(96_000)
                self.bytes_read += len(header)
                for line in header.split(b'\n')[:-1]:
                    r = obj(line)
                    if self.provider == 'codex' and r.get('type') in ('session_meta', 'turn_context'):
                        self.parser.consume(line.decode('utf-8', 'replace'))
                    elif self.provider == 'claude':
                        self.parser.session_id = r.get('sessionId') or self.parser.session_id
                        self.parser.cwd = r.get('cwd') or self.parser.cwd
                self.offset = stat.st_size - MAX_READ
                self.dropping = True
                if self.provider == 'codex':
                    self.parser.may_infer_turn = True
        self.inode, self.modified = stat.st_ino, stat.st_mtime_ns
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            data = stream.read(MAX_READ)
            self.offset = stream.tell()
        self.bytes_read += len(data)
        lines = (self.pending + data).split(b'\n')
        self.pending = lines.pop()
        for line in lines:
            if self.dropping:
                self.dropping = False
                continue
            if len(line) > MAX_LINE:
                continue
            text = line.decode('utf-8', 'replace')
            record = obj(text)
            payload = record.get('payload',{})
            if self.provider=='codex' and isinstance(payload,dict) and record.get('type')=='event_msg' and payload.get('type')=='task_started':
                self.turn_id = str(payload.get('turn_id') or record.get('timestamp') or self.offset)
            if self.provider=='claude' and record.get('type')=='user' and not record.get('isSidechain'):
                message = record.get('message',{})
                content = message.get('content') if isinstance(message,dict) else None
                tool_result = isinstance(content,list) and any(isinstance(c,dict) and c.get('type')=='tool_result' for c in content)
                if not tool_result and not record.get('toolUseResult'):
                    self.turn_id = str(record.get('uuid') or record.get('timestamp') or self.offset)
            self.parser.consume(text)
            self.timeline.consume(self.provider, record)
        if len(self.pending) > MAX_LINE:
            self.pending = b''
            self.dropping = True
        parsed = self.parser.snapshot()
        timestamp = parsed['updated_at']
        self.cached_state = AgentSession(self.provider, parsed['session_id'] or self.path.stem,
                            short(parsed['project_name']), parsed['phase'], short(parsed['detail']),
                            timestamp.timestamp() if timestamp else 0,
                            list(self.timeline.steps), parsed['total_tokens'] or None, turn_id=self.turn_id, task=short(parsed.get('title')))
        return self.cached_state


class LocalJSONLProvider:
    capabilities = AgentCapabilities()

    def __init__(self, key, root, legacy):
        self.key, self.root, self.legacy = key, root, legacy
        self.capabilities = AgentCapabilities(quota=key=='codex')
        self.readers = {}
        self.last_scan = -100
        self.health = 'Not checked'

    def sessions(self):
        now = time.monotonic()
        if now - self.last_scan > 10:
            self.last_scan = now
            paths = []
            for path in self.root.rglob('*.jsonl'):
                try:
                    modified = path.stat().st_mtime
                    if modified > time.time() - 600:
                        paths.append((modified, path))
                except OSError:
                    pass
            paths.sort(key=lambda item: item[0], reverse=True)
            selected = {p for _,p in paths[:MAX_SESSIONS]}
            self.readers = {p: self.readers.get(p) or IncrementalSession(p, self.key, self.legacy) for p in selected}
        states = []
        for path, reader in list(self.readers.items()):
            try:
                states.append(reader.read())
            except (OSError, ValueError, TypeError, OverflowError):
                self.readers.pop(path, None)
        self.health = 'Local metadata' if self.root.exists() else 'Not installed / no local sessions'
        return states


class OpenCodeProvider:
    """Read old and new Desktop storage, preferring v2 over migrated legacy rows."""
    key = 'opencode'
    capabilities = AgentCapabilities()

    def __init__(self, legacy):
        self.legacy = legacy
        self.health = 'Not checked'
        self.cached = []
        self.stamp = None
        self.last_query = 0

    def databases(self):
        if os.environ.get('OPENCODE_DB'):
            return [self.legacy.opencode_database()]
        root = Path(os.environ.get('XDG_DATA_HOME','~/.local/share')).expanduser()/'opencode'
        return sorted(root.glob('opencode*.db'))[:8]

    def _read(self, con, v2, has_v2):
        # Identifiers are fixed schema names, never supplied by files or callbacks.
        st, mt, pt = ('session_v2','session_message','session_part') if v2 else ('session','message','part')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if st not in tables or mt not in tables:
            return []
        columns = {r[1] for r in con.execute('PRAGMA table_info('+st+')')}
        archived = 's.time_archived IS NULL' if 'time_archived' in columns else '1'
        old_shadow = ' AND s.id NOT IN (SELECT id FROM session_v2)' if has_v2 and not v2 else ''
        cutoff = int((time.time()-600)*1000)
        part_columns={r[1] for r in con.execute('PRAGMA table_info('+pt+')')} if pt in tables else set()
        recent_parts = (' UNION ALL SELECT session_id,time_updated FROM '+pt+' WHERE time_updated>?') if 'session_id' in part_columns else ''
        params = (cutoff,cutoff,cutoff) if recent_parts else (cutoff,cutoff)
        query = ('WITH recent(id,touched) AS (SELECT id,time_updated FROM '+st+' WHERE time_updated>? '
                 'UNION ALL SELECT session_id,time_updated FROM '+mt+' WHERE time_updated>?'+recent_parts+') '
                 'SELECT s.*,MAX(recent.touched) AS activity_at FROM '+st+' s JOIN recent ON recent.id=s.id '
                 'WHERE '+archived+old_shadow+' GROUP BY s.id ORDER BY activity_at DESC LIMIT 64')
        result=[]
        for row in con.execute(query,params).fetchall():
            order = 'seq DESC' if v2 else 'time_created DESC,id DESC'
            records = con.execute('SELECT id,'+('type,' if v2 else '')+'time_updated,substr(data,1,220000) AS data FROM '+mt+' WHERE session_id=? ORDER BY '+order+' LIMIT 12',(row['id'],)).fetchall()
            messages=[]
            parts=[]
            for record in records:
                data=obj(record['data'])
                kind = record['type'] if v2 else data.get('role')
                messages.append((kind,data,record))
                if kind=='assistant':
                    content=data.get('content',[])
                    if v2 and isinstance(content,list):
                        parts.extend((p,record['id']) for p in content if isinstance(p,dict))
                    if pt in tables:
                        part_order = 'ordinal DESC' if v2 else 'time_created DESC,id DESC'
                        extra=con.execute('SELECT '+('type,call_id,' if v2 else '')+'time_updated,substr(data,1,220000) AS data FROM '+pt+' WHERE message_id=? ORDER BY '+part_order+' LIMIT 8',(record['id'],)).fetchall()
                        for part in reversed(extra):
                            pd=obj(part['data'])
                            pd['_updated_at']=part['time_updated']
                            if v2:
                                pd.setdefault('type',part['type'])
                                pd.setdefault('id',part['call_id'])
                            parts.append((pd,record['id']))
            # Keep the timeline within this turn; an earlier turn's edits are not new work.
            first=next((kind for kind,_,_ in messages if kind in ('user','assistant','idle')),None)
            boundary=None
            for index,(kind,_,_) in enumerate(messages):
                if v2 and kind=='idle':
                    if first=='idle':first=None
                    else:boundary=index;break
                elif not v2 and kind=='user':
                    boundary=index+1;break
            if boundary is not None:
                messages=messages[:boundary]
                allowed={record['id'] for _,_,record in messages}
                parts=[(part,mid) for part,mid in parts if mid in allowed]
            phase,detail='paused','Idle'
            meaningful=next(((kind,data,record) for kind,data,record in messages if kind in ('user','assistant','idle')),None)
            if meaningful:
                kind,data,record=meaningful
                if kind=='idle':
                    phase={'succeeded':'completed','failed':'failed','interrupted':'interrupted'}.get(data.get('outcome'),'paused')
                    detail={'completed':'Complete','failed':'Failed','interrupted':'Interrupted'}.get(phase,'Idle')
                else:
                    current_parts=[p for p,mid in parts if mid==record['id']]
                    data={**data,'role':kind}
                    normalized_part=current_parts[-1] if current_parts else None
                    if normalized_part and v2:
                        normalized_part={**normalized_part,'tool':normalized_part.get('name')}
                    phase,detail,_=self.legacy.opencode_phase(data,normalized_part)
            steps=[]
            seen=set()
            # Messages arrive newest first; reverse only the message groups, preserving content order.
            for _,_,record in reversed(messages):
                for part,mid in parts:
                    if mid!=record['id'] or part.get('type')!='tool':continue
                    call=str(part.get('id') or part.get('callID') or part.get('call_id') or (mid+':'+str(len(steps))))
                    if call in seen:continue
                    seen.add(call)
                    state=part.get('state')
                    if not isinstance(state,dict):continue
                    label,file,added,deleted=operation(part.get('name') or part.get('tool'),state.get('input'))
                    state_name={'completed':'completed','error':'failed','running':'running','streaming':'running'}.get(state.get('status'),'observed')
                    metadata=state.get('metadata')
                    edits=metadata.get('files') if isinstance(metadata,dict) else None
                    if state_name=='completed' and isinstance(edits,list) and edits and all(
                        isinstance(edit,dict) and all(type(edit.get(key)) is int and edit[key]>=0
                                                      for key in ('additions','deletions'))
                        for edit in edits
                    ):
                        added=sum(edit['additions'] for edit in edits)
                        deleted=sum(edit['deletions'] for edit in edits)
                    steps.append(AgentTaskStep(call,label,state_name,file,added,deleted))
            tokens=None
            for kind,data,_ in messages:
                if kind!='assistant':continue
                usage=data.get('tokens')
                if isinstance(usage,dict):
                    tokens=usage.get('total')
                    if tokens is None and all(isinstance(usage.get(k),int) for k in ('input','output')):
                        tokens=usage['input']+usage['output']
                    break
            user_filter="type='user'" if v2 else "json_extract(data,'$.role')='user'"
            user_row=con.execute('SELECT id FROM '+mt+' WHERE session_id=? AND '+user_filter+' ORDER BY '+order+' LIMIT 1',(row['id'],)).fetchone()
            user=user_row['id'] if user_row else None
            updated=meaningful[2]['time_updated'] if meaningful else row['activity_at']
            if meaningful and meaningful[0]=='assistant':
                updated=max([updated]+[part.get('_updated_at',0) for part,mid in parts if mid==meaningful[2]['id']])
            result.append(AgentSession(self.key,row['id'],short(Path(row['directory'] or '').name),phase,detail,
                updated/1000,steps[-8:],tokens,turn_id=user,task=short(row['title']) if 'title' in columns else ''))
        return result

    def sessions(self):
        try:
            databases=self.databases()
            if not databases:
                self.health='No local database'
                return []
            stamp=tuple((str(db),db.stat().st_mtime_ns,Path(str(db)+'-wal').stat().st_mtime_ns if Path(str(db)+'-wal').exists() else 0) for db in databases)
            if stamp==self.stamp and time.monotonic()-self.last_query<10:return self.cached
            combined={}
            formats=set()
            for db in databases:
                with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as con:
                    con.row_factory=sqlite3.Row
                    deadline=time.monotonic()+.25
                    con.set_progress_handler(lambda: int(time.monotonic()>deadline),2000)
                    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    has_v2='session_v2' in tables and 'session_message' in tables
                    for v2 in (False,True):
                        if (v2 and not has_v2) or (not v2 and 'session' not in tables):continue
                        states=self._read(con,v2,has_v2)
                        formats.add('Desktop v2' if v2 else 'legacy')
                        for state in states:
                            previous=combined.get(state.id)
                            if previous is None or state.updated_at>previous.updated_at:combined[state.id]=state
            self.cached=sorted(combined.values(),key=lambda s:s.updated_at,reverse=True)[:64]
            self.stamp,self.last_query=stamp,time.monotonic()
            self.health='SQLite read-only · '+', '.join(sorted(formats))
            return self.cached
        except FileNotFoundError:
            self.health='No local database'
        except (sqlite3.Error,OSError,ValueError,TypeError,KeyError):
            self.health='Database unavailable / incompatible'
        return self.cached
