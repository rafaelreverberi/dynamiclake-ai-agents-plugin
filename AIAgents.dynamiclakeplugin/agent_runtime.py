"""Session reconciliation, action routing and DynamicLake connection lifecycle."""
from __future__ import annotations
from dataclasses import replace
import json
import math
import os
import signal
import subprocess
import time
from agent_bridge import HookBridge
from agent_models import AgentCapabilities, identity
from agent_presentation import Presentation
from agent_providers import LocalJSONLProvider, OpenCodeProvider
from agent_usage import UsageMonitor
from agent_setup import SetupService
from agent_paths import package_root


def settings(legacy):
    result = legacy.plugin_settings()
    for key,default in [('enableHooks',True),('interactiveApprovals',False),
                        ('hideFileNames',False),('hideProjectNames',False),('enableUsageTracking',True),
                        ('hideSetupButton',False),('alwaysShowUsage',False),
                        ('codexApprovals',False),
                        ('showTaskSteps',True),('showToolDescriptions',True),('notifyCompletion',True),
                        ('notifyPermissions',True),('notifyErrors',True),('showAgentLogos',False),('enableNotifications',True)]:
        result[key] = legacy.setting_bool(key,default,result)
    if not result['enableNotifications']:
        for key in ('notifyCompletion','notifyPermissions','notifyErrors'):result[key]=False
    return result


class ProviderRegistry:
    def __init__(self, legacy):
        self.legacy = legacy
        self.providers = [LocalJSONLProvider('codex',legacy.codex_home()/'sessions',legacy),
                          LocalJSONLProvider('claude',legacy.claude_home()/'projects',legacy),OpenCodeProvider(legacy)]
        self.health = {}

    def collect(self, values):
        enabled = {s.key for s in self.legacy.enabled_sources(values)}
        sessions = {}
        for p in self.providers:
            if p.key not in enabled:
                self.health[p.key] = 'Disabled'
                continue
            try:
                for state in p.sessions():
                    sessions[state.activity_id] = state
                self.health[p.key] = p.health
            except Exception:
                # Provider drift must not break other integrations; no raw exceptions in diagnostics.
                self.health[p.key] = 'Metadata unavailable / incompatible'
        return sessions


class Controller:
    def __init__(self, legacy):
        self.legacy = legacy
        self.client = legacy.DynamicLakeJSONClient(os.environ.get('DYNAMICLAKE_JSON_SOCKET'))
        self.registry = ProviderRegistry(legacy)
        self.presentation = Presentation(legacy)
        self.usage = UsageMonitor()
        self.setup=SetupService()
        self.values = settings(legacy)
        self.bridge = HookBridge(lambda: self.connected and self.values.get('enableHooks',True) and self.values.get('interactiveApprovals',False) and self.legacy.env_bool('AI_AGENTS_ENABLE_CLAUDE',True) and 'lakeLayout' in self.presentation.features,
            usage_enabled=lambda:self.values.get('enableUsageTracking',True) and self.legacy.env_bool('AI_AGENTS_ENABLE_CLAUDE',True),
            events_enabled=lambda:self.values.get('enableHooks',True),
            codex_approvals=lambda:self.connected and self.values.get('codexApprovals',False) and self.legacy.env_bool('AI_AGENTS_ENABLE_CODEX',True) and 'lakeLayout' in self.presentation.features)
        self.published = {}
        self.phases = {}
        self.dismissed = {}
        self.sessions = {}
        self.lake_signature = None
        self.stopping = False
        self.retry_bridge_at = 0
        self.notice = ''
        self.connected = False
        self.reconciled = False

    def refresh_sources(self):
        self.values = settings(self.legacy)
        if self.values['hideSetupButton'] and self.presentation.page=='setup':
            self.presentation.page='progress'
            self.setup.pending=None
        hooks = any(self.values[key] for key in ('enableHooks','enableUsageTracking','codexApprovals'))
        if hooks and not self.bridge.server and time.monotonic() >= self.retry_bridge_at:
            try:
                self.bridge.start()
            except (OSError, ValueError):
                self.bridge.health = 'Bridge unavailable; native prompts remain active'
                self.retry_bridge_at = time.monotonic()+30
        if not hooks and self.bridge.server:
            self.bridge.close()
        for provider in ('claude','codex'):
            if not self.bridge.approval_enabled(provider):
                self.bridge.cancel_permissions(provider)
        current = self.registry.collect(self.values)
        enabled = {s.key for s in self.legacy.enabled_sources(self.values)}
        for s in self.bridge.drain():
            if s.provider in enabled:
                previous = current.get(s.activity_id)
                if previous and s.permission_id:
                    continue
                if not previous or s.updated_at >= previous.updated_at:
                    current[s.activity_id] = s
        for permission in self.bridge.permissions():
            key = identity(permission.provider,permission.session_id)
            if key in current and permission.provider in enabled:
                current[key] = replace(current[key],phase='permission',detail='Waiting for permission',permission_id=permission.id)
        stale = self.number('staleSeconds',self.legacy.STALE_SECONDS,15,600)
        completed = self.number('completionSeconds',self.legacy.COMPLETED_VISIBLE_SECONDS,0,120)
        self.sessions = {key:s for key,s in current.items() if s.visible(stale,completed)}
        if not self.reconciled:
            for source in self.legacy.ALL_SOURCES:
                self.client.send(self.legacy.dismiss_message(source.activity_id))
            # Clean up the ambient activity published by beta.4.
            self.client.send(self.legacy.dismiss_message('ai-agents-usage'))
            self.reconciled = True
        self.dismissed={key:turn for key,turn in self.dismissed.items() if key in self.sessions}
        eligible=[state for key,state in self.sessions.items() if self.dismissed.get(key)!=(state.turn_id or state.id) or state.permission_id]
        chosen=self.presentation.choose(eligible)
        for key in list(self.published):
            if chosen is None or key!=chosen.activity_id:
                self.client.send(self.legacy.dismiss_message(key))
                self.published.pop(key,None)
        if chosen:
            key,s=chosen.activity_id,chosen
            permission=next((p for p in self.bridge.permissions() if p.id==s.permission_id),None)
            msg=self.presentation.activity(s,'update' if key in self.published else 'create',self.values,self.client.send,permission=permission)
            signature=json.dumps({k:v for k,v in msg.items() if k!='type'},sort_keys=True)
            phase_key=s.phase+':'+(s.permission_id or '')
            if self.published.get(key)!=signature:
                notify=(key in self.phases or s.permission_id is not None) and self.phases.get(key)!=phase_key
                self.client.send(self.presentation.activity(s,msg['type'],self.values,self.client.send,notify,permission))
                self.published[key]=signature
            self.phases[key]=phase_key
        self.phases = {k:v for k,v in self.phases.items() if k in self.sessions}
        self.usage.refresh(self.values['enableUsageTracking'])
        if not self.values['enableUsageTracking']:self.bridge.usage=[]
        self.publish_lake()

    def number(self, key, default, minimum, maximum):
        n = self.values.get(key,default)
        if isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n):
            return min(max(n,minimum),maximum)
        return default

    def capabilities(self):
        return {
            'codex': AgentCapabilities(quota=True,permissions=bool(self.bridge.server and self.bridge.codex_approvals())),
            'claude': AgentCapabilities(quota=True,permissions=bool(self.bridge.server and self.bridge.approvals())),
            'opencode': AgentCapabilities(quota=True),
        }

    def publish_lake(self):
        if 'lake' not in self.presentation.features:
            return
        health={'usage':dict(self.usage.status),'notice':self.notice}
        if self.presentation.page=='setup':health['setup']=self.setup.view()
        visible=[state for key,state in self.sessions.items() if self.dismissed.get(key)!=(state.turn_id or state.id) or state.permission_id]
        usage=self.usage.snapshots+self.bridge.usage if self.values['enableUsageTracking'] else []
        msg = self.presentation.lake(visible,self.bridge.permissions(),usage,health,self.values,self.client.send)
        sig = json.dumps(msg,sort_keys=True)
        if sig != self.lake_signature:
            self.client.send(msg)
            self.lake_signature = sig

    def handle_callbacks(self,timeout=0):
        render=False
        for message in self.client.read_available(timeout):
            if not isinstance(message,dict):
                continue
            kind = message.get('type')
            if kind == 'error' or message.get('ok') is False:
                self.notice = 'Host rejected a command; see compatibility notes'
                continue
            if kind == 'lakeOpened':
                activity = message.get('activityID')
                if activity in self.sessions:
                    self.presentation.selected=activity
                    request=self.sessions[activity].permission_id
                    if request and any(p.id==request for p in self.bridge.permissions()):
                        self.presentation.page,self.presentation.permission_id='permission',request
                    else:
                        self.presentation.page='progress'
                self.lake_signature = None
                render=True
                continue
            if kind == 'lakeClosed' and self.presentation.page == 'permission':
                self.presentation.page='progress'
                self.presentation.permission_id=None
                render=True
                continue
            if kind != 'action':
                continue
            action, activity = message.get('actionID'),message.get('activityID')
            if not isinstance(action,str):
                continue
            surface = message.get('surface')
            if action.startswith('dismiss') and activity in self.sessions:
                s = self.sessions[activity]
                if not s.permission_id:
                    self.dismissed[activity] = s.turn_id or s.id
                    self.client.send(self.legacy.dismiss_message(activity))
                    self.published.pop(activity,None)
            elif surface == 'lake' and activity == 'lake':
                render=True
                verb,_,value = action.partition(':')
                if self.values['hideSetupButton'] and (verb.startswith('setup') or (verb=='tab' and value=='setup')):
                    continue
                if verb == 'tab' and value in ('progress','usage','setup'):
                    self.presentation.page = value
                    self.setup.pending=None
                elif verb=='cycle' and value in ('previous','next'):
                    from agent_presentation import rank
                    available=sorted(self.sessions.values(),key=rank)
                    if available:
                        index=next((i for i,s in enumerate(available) if s.activity_id==self.presentation.selected),0)
                        self.presentation.selected=available[(index+(1 if value=='next' else -1))%len(available)].activity_id
                        self.presentation.page='progress'
                elif verb=='window' and value in ('5-hour','weekly','monthly'):
                    self.presentation.quota_window=value
                elif verb=='quota' and value in ('claude','codex'):
                    self.presentation.usage_provider=None if self.presentation.usage_provider==value else value
                elif verb=='setup-provider' and value in ('all','claude','codex','opencode'):
                    self.presentation.page='setup'
                    self.presentation.setup_provider=None if value=='all' else value
                    self.setup.pending=None;self.notice=''
                elif verb=='setup' and self.presentation.page=='setup':
                    if value=='cancel':self.setup.pending=None
                    else:self.setup.preview(value)
                elif verb=='setup-confirm' and self.presentation.page=='setup':
                    self.setup.confirm(value)
                elif verb=='check' and value in ('codex','opencode'):
                    if self.values.get('enableUsageTracking',True):self.usage.refresh(True,force=True,provider=value)
                    else:self.notice='Enable Usage & limits in Plugin Settings first.'
                elif verb=='guide':self.open_guide(value)
                elif verb=='open-provider' and value in ('codex','opencode'):self.open_agent(value)
                elif verb=='session' and value in self.sessions:
                    self.presentation.page,self.presentation.selected='progress',value
                elif verb == 'permission' and value in {p.id for p in self.bridge.permissions()}:
                    self.presentation.page,self.presentation.permission_id = 'permission',value
                elif verb in ('allow','deny') and self.presentation.page == 'permission' and self.presentation.permission_id == value:
                    ok = self.bridge.decide(value,verb)
                    self.notice = 'Decision queued; awaiting agent confirmation' if ok else 'Request expired or unavailable'
                    self.presentation.page = 'progress'
                    self.presentation.permission_id=None
                elif verb == 'open' and value in self.sessions:
                    self.open_agent(self.sessions[value].provider)
                self.lake_signature = None
        # View actions use cached state immediately; they never wait for provider polling.
        if render:self.publish_lake()

    def open_guide(self,key):
        links={'console':'https://opencode.ai/console','opencode':'https://opencode.ai/docs/console/go','claude':'https://code.claude.com/docs/en/statusline'}
        target=links.get(key)
        if key=='local':
            guide=package_root()/'docs/SETUP.md'
            if not guide.exists():guide=package_root().parent/'docs/SETUP.md'
            if guide.exists():target=str(guide)
        if target:
            try:subprocess.run(['/usr/bin/open',target],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
            except (OSError,subprocess.TimeoutExpired):self.notice='Open the setup guide from the package README.'

    def open_agent(self, provider):
        bundles = {'codex':'com.openai.codex','opencode':'ai.opencode.desktop'}
        # CLI sessions may live in any terminal. Do not guess a terminal/session or execute a command.
        bundle = bundles.get(provider)
        if not bundle:
            self.notice = 'Return to the original '+('Claude Code' if provider=='claude' else 'OpenCode')+' terminal'
            return
        try:
            result = subprocess.run(['/usr/bin/open','-b',bundle],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
            self.notice = 'Opened agent app; choose the session there' if result.returncode == 0 else 'Agent app unavailable; return to its terminal'
        except (OSError,subprocess.TimeoutExpired):
            self.notice = 'Agent app unavailable; return to its terminal'

    def run(self):
        def stop(*_):
            self.stopping = True
        signal.signal(signal.SIGTERM,stop)
        signal.signal(signal.SIGINT,stop)
        backoff = 1
        try:
            while not self.stopping:
                try:
                    if not self.connected:
                        self.client.connect()
                        self.connected = True
                        self.published.clear()
                        self.presentation.registered.clear()
                        self.lake_signature = None
                        self.reconciled = False
                    self.handle_callbacks()
                    self.refresh_sources()
                    backoff = 1
                    # Active: 1 s; idle: 3 s, with callbacks still processed every 200 ms.
                    until = time.monotonic()+(1 if self.sessions else 3)
                    while not self.stopping and time.monotonic()<until:
                        self.handle_callbacks(timeout=min(.2,max(0,until-time.monotonic())))
                except (OSError, ConnectionError, ValueError, RuntimeError):
                    self.client.close()
                    self.connected = False
                    self.bridge.cancel_permissions()
                    self.published.clear()
                    until = time.monotonic()+backoff
                    while not self.stopping and time.monotonic()<until:
                        time.sleep(.2)
                    backoff = min(30,backoff*2)
        finally:
            self.bridge.close()
            self.usage.close()
            self.setup.close()
            if self.connected:
                try:
                    self.client.send({'schemaVersion':1,'type':'dismiss'})
                except OSError:
                    pass
            self.client.close()
        return 0
