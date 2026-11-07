"""Explicit in-plugin setup: inspect, preview, then apply a fixed integration action."""
import json
from pathlib import Path
import threading
import time
from integrations import update_config, owned, MARKER, provider_config

ACTIONS={'claude_usage':(True,True),'claude_hooks':(True,False),'remove_claude_usage':(False,True),'remove_claude_hooks':(False,False),
         'codex_hooks':(True,False),'remove_codex_hooks':(False,False)}


class SetupService:
    def __init__(self,config=None,codex_config=None):
        self.config=Path(config) if config else provider_config('claude')
        self.codex_config=Path(codex_config) if codex_config else provider_config('codex')
        self.worker=None
        self.result=''
        self.last_action=None
        self.pending=None
        self.pending_until=0

    def summary(self):
        result={'usage':False,'hooks':False,'approval_hook':False,'custom_usage':False,'readable':True}
        try:
            if not self.config.exists():return result
            if self.config.stat().st_size>1_000_000:raise ValueError()
            value=json.loads(self.config.read_text())
            if not isinstance(value,dict):raise ValueError()
            line=value.get('statusLine')
            import shlex
            own=isinstance(line,dict) and isinstance(line.get('command'),str) and MARKER in shlex.split(line['command'])
            result['usage']=own
            result['custom_usage']=line is not None and not own
            hooks=value.get('hooks',{})
            result['hooks']=isinstance(hooks,dict) and any(owned(h,'claude') for entries in hooks.values() if isinstance(entries,list) for h in entries)
            entries=hooks.get('PermissionRequest') if isinstance(hooks,dict) else None
            result['approval_hook']=isinstance(entries,list) and any(owned(h,'claude') for h in entries)
        except (OSError,ValueError,TypeError):result['readable']=False
        return result

    def codex_hooks_installed(self):
        try:
            with self.codex_config.open('rb') as stream:
                value=json.loads(stream.read(1_000_001))
            entries=value['hooks']['PermissionRequest']
            return isinstance(entries,list) and any(owned(h,'codex') for h in entries)
        except (OSError,ValueError,TypeError,KeyError):
            return False

    @property
    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def preview(self,action):
        if action not in ACTIONS or self.busy:return False
        self.pending=action;self.pending_until=time.monotonic()+120;self.result=''
        return True

    def confirm(self,action):
        if action!=self.pending or time.monotonic()>self.pending_until or self.busy:return False
        self.pending=None
        install,usage=ACTIONS[action]
        self.result='Connecting…' if install else 'Removing integration…'
        self.last_action=action
        if action.endswith('codex_hooks'):
            provider,path='codex',self.codex_config
        else:
            provider,path='claude',self.config
        def work():
            try:
                changed=update_config(path,provider,install,usage=usage,keep_usage=not install and not usage)
                if provider=='codex':
                    self.result='Hook installed. Trust it in Codex and enable Codex approvals in Plugin Settings.' if install else 'Codex approval hook removed.'
                else:
                    self.result=('Connected. Open a Claude session; limits arrive after its next response.' if usage else 'Hooks installed. Restart Claude Code and enable Claude activity hooks and Claude approvals in Plugin Settings.') if install else 'Integration removed. Other Claude settings are preserved.'
                if not changed:self.result='Already configured.' if install else 'This integration was not installed.'
            except ValueError:
                self.result='Existing configuration preserved. Manual setup is needed.'
            except OSError:self.result='Could not update the provider configuration.'
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
        return True

    def view(self):
        return {**self.summary(),'codex_hooks':self.codex_hooks_installed(),'last_action':self.last_action,
                'busy':self.busy,'result':self.result,'pending':self.pending if time.monotonic()<self.pending_until else None}

    def close(self):
        if self.worker and self.worker.is_alive():self.worker.join(timeout=2)
