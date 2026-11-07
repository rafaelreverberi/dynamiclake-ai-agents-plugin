#!/usr/bin/env python3
"""Provider hook client: stdin JSON -> private IPC -> documented hook stdout."""
import json
import socket
import sys
sys.dont_write_bytecode = True
from agent_bridge import bridge_path, MAX_MESSAGE


def run(provider, event):
    permission = provider in ('claude','codex') and event == 'PermissionRequest'
    try:
        data = sys.stdin.buffer.read(MAX_MESSAGE + 1)
        if len(data) > MAX_MESSAGE:
            return {}
        value = json.loads(data)
        if not isinstance(value,dict):
            return {}
        # Strip transcripts, prompts, output, email and model metadata before IPC.
        value = {key: value[key] for key in ('session_id','cwd','tool_name','tool_input','tool_use_id','status','prompt_id','turn_id') if key in value}
        if not permission and isinstance(value.get('tool_input'),dict):
            value['tool_input'] = {k:v for k,v in value['tool_input'].items() if k in ('file_path','path')}
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(92 if permission else 1)
            client.connect(str(bridge_path()))
            client.sendall(json.dumps({'provider':provider,'event':event,'data':value}).encode()+b'\n')
            reply = client.makefile('rb').readline(2048)
        result = json.loads(reply)
        if permission and result.get('decision') in ('allow','deny'):
            return {'hookSpecificOutput': {'hookEventName':'PermissionRequest','decision':{'behavior':result['decision']}}}
    except (OSError, ValueError, TypeError):
        pass
    # An empty decision hands control back to the native prompt.
    return {}


def run_usage():
    from agent_models import claude_quota_snapshots
    try:
        raw=sys.stdin.buffer.read(MAX_MESSAGE+1)
        if len(raw)>MAX_MESSAGE:return 'Claude'
        value=json.loads(raw)
        if not isinstance(value,dict):return 'Claude'
        snapshots=claude_quota_snapshots(value)
        rates={}
        for u in snapshots:
            rates['five_hour' if u.window=='5-hour' else 'seven_day']={'used_percentage':u.used_percent,'resets_at':u.resets_at}
        payload={'provider':'claude','event':'Usage','data':{'session_id':value.get('session_id'),'rate_limits':rates}}
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(.5)
                client.connect(str(bridge_path()))
                client.sendall(json.dumps(payload).encode()+b'\n')
                client.makefile('rb').readline(2048)
        except OSError:pass
        return 'Claude'+(' · '+' · '.join(f'{u.remaining_percent:g}% {u.window} left' for u in snapshots) if snapshots else '')
    except (OSError,ValueError,TypeError):return 'Claude'


if __name__=='__main__':
    if sys.argv[1:3]==['claude','Usage']:print(run_usage())
    else:print(json.dumps(run(*sys.argv[1:3])))
