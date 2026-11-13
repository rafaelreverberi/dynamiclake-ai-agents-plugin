#!/usr/bin/env python3
"""Explicit, reversible hook installation. Never invoked by the monitor."""
from __future__ import annotations
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import time
from agent_paths import package_root

EVENTS = {'claude':['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','PermissionRequest','Stop','SessionEnd'],
          'codex':['PermissionRequest']}

MARKER = 'dynamiclake-ai-agents-hook'
LOCK_WAIT_SECONDS=2


def hook_command(provider,event):
    # Shell quoting protects paths including spaces. Keep the marker so older
    # entries are still recognized and replaced on explicit reinstall.
    entry = [str(package_root() / Path(sys.executable).name), '--hook'] if getattr(sys, 'frozen', False) else [
        sys.executable, str(package_root() / 'agent_hook.py')]
    return shlex.join([*entry,provider,event,MARKER])


def owned(item, provider):
    if not isinstance(item,dict):
        return False
    hooks = item.get('hooks',[])
    return bool(hooks) and all(isinstance(h,dict) and isinstance(h.get('command'),str) and MARKER in shlex.split(h['command']) for h in hooks)


def update_config(path,provider,install,usage=False,keep_usage=False):
    if usage and provider!='claude':
        raise ValueError('Usage setup is only available for Claude')
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlinked provider configuration')
    path.parent.mkdir(parents=True,exist_ok=True)
    lock_path = path.with_name(path.name+'.dynamiclake.lock')
    flags = os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)
    with os.fdopen(os.open(lock_path,flags,0o600),'w') as lock:
        deadline=time.monotonic()+LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise TimeoutError('Provider setup is busy; try again')
                time.sleep(.025)
        original = path.read_bytes() if path.exists() else b'{}'
        if len(original)>1_000_000:
            raise ValueError('Configuration too large')
        config = json.loads(original)
        if not isinstance(config,dict) or not isinstance(config.get('hooks',{}),dict):
            raise ValueError('Incompatible hook configuration; no changes made')
        result = copy.deepcopy(config)
        hooks = result.get('hooks',{}) if usage else result.setdefault('hooks',{})
        if usage:
            current=result.get('statusLine')
            is_ours=isinstance(current,dict) and isinstance(current.get('command'),str) and MARKER in shlex.split(current['command'])
            if install:
                if 'statusLine' in result and not is_ours:
                    raise ValueError('Existing statusLine preserved; usage collector was not installed')
                result['statusLine']={'type':'command','command':hook_command('claude','Usage')}
            elif is_ours:result.pop('statusLine',None)
        if provider=='claude' and not install and not usage and not keep_usage:
            current=result.get('statusLine')
            if isinstance(current,dict) and isinstance(current.get('command'),str) and MARKER in shlex.split(current['command']):result.pop('statusLine',None)
        for event in ([] if usage else EVENTS[provider]):
            items = hooks.get(event,[])
            if not isinstance(items,list):
                raise ValueError('Incompatible event hooks; no changes made')
            items = [h for h in items if not owned(h,provider)]
            if install:
                hook = {'type':'command','command':hook_command(provider,event),'timeout':95 if event=='PermissionRequest' else 3}
                items.append({'hooks':[hook]})
            if items:
                hooks[event] = items
            else:
                hooks.pop(event,None)
        if result==config:
            return False
        # Exact backup is private; uninstall removes only our entries, preserving later edits.
        if path.exists():
            backup = path.with_name(path.name+f'.dynamiclake-backup-{time.time_ns()}')
            with os.fdopen(os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:
                out.write(original)
        fd,temporary = tempfile.mkstemp(prefix='.dynamiclake-',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as out:
                json.dump(result,out,indent=2)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','uninstall','install-usage','uninstall-usage'])
    parser.add_argument('provider',choices=list(EVENTS))
    args=parser.parse_args(argv)
    path = provider_config(args.provider)
    update_config(path,args.provider,args.action in ('install','install-usage'),usage=args.action.endswith('-usage'))
    print('Hook configuration updated. Existing unrelated hooks preserved. Restart the provider session.')


def provider_config(provider):
    if provider=='codex':
        return Path(os.environ.get('CODEX_HOME','~/.codex')).expanduser()/'hooks.json'
    return Path(os.environ.get('CLAUDE_HOME','~/.claude')).expanduser()/'settings.json'


if __name__=='__main__':
    main()
