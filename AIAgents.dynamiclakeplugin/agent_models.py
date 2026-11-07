"""Provider-neutral state. No transcripts or credentials belong in these models."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import math
import time


def short(value, limit=100):
    return ' '.join(str(value or '').split())[:limit]


def identity(provider, session):
    return f'ai-agents.{provider}.' + hashlib.sha256(str(session).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class AgentCapabilities:
    monitoring: bool = True
    tool_events: bool = True
    permissions: bool = False
    quota: bool = False
    open_session: bool = False


@dataclass
class AgentTaskStep:
    id: str
    label: str
    status: str = 'running'  # running, completed, failed, observed (outcome unknown)
    file_name: str = ''
    additions: int | None = None
    deletions: int | None = None


@dataclass
class AgentUsageSnapshot:
    provider: str
    window: str
    used_percent: float | None = None
    resets_at: float | None = None
    updated_at: float = 0
    source: str = 'Unavailable'
    plan: str | None = None

    @property
    def remaining_percent(self):
        return None if self.used_percent is None else 100 - self.used_percent

    @property
    def stale(self):
        return not self.updated_at or time.time() - self.updated_at > 600


@dataclass
class AgentSession:
    provider: str
    id: str
    project: str
    phase: str
    detail: str
    updated_at: float
    steps: list[AgentTaskStep] = field(default_factory=list)
    tokens: int | None = None
    permission_id: str | None = None
    turn_id: str | None = None
    task: str = ''

    @property
    def activity_id(self):
        return identity(self.provider, self.id)

    def visible(self, stale=90, completed=20):
        if self.permission_id:
            return True
        if self.phase in ('paused', 'idle', 'interrupted'):
            return False
        return time.time() - self.updated_at <= (completed if self.phase == 'completed' else stale)


@dataclass
class AgentPermissionRequest:
    id: str
    provider: str
    session_id: str
    tool: str
    project: str
    preview: str
    deadline: float
    transport: object = None
    decision: str | None = None


def format_minutes(minutes):
    days, remainder = divmod(minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts = [f'{value} {unit}' for value, unit in ((days, 'd'), (hours, 'h'), (minutes, 'min')) if value]
    return ' '.join(parts) or '0 min'


def quota_snapshots(result, now=None):
    """Only accept actual account/rateLimits/read windows; never infer quotas."""
    now = time.time() if now is None else now
    root = result.get('rateLimitsByLimitId')
    if not isinstance(root, dict) or not root:
        root = {'codex': result.get('rateLimits', {})}
    snapshots = []
    for limit, data in list(root.items())[:16]:
        if not isinstance(data, dict):
            continue
        for name in ('primary', 'secondary'):
            window = data.get(name)
            if not isinstance(window, dict):
                continue
            used = window.get('usedPercent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
                continue
            duration = window.get('windowDurationMins')
            label = name.title()
            if type(duration) is int and duration > 0:
                label = {300: '5-hour', 10080: 'Weekly'}.get(duration) or format_minutes(duration)
            reset = window.get('resetsAt')
            reset = reset if isinstance(reset, (int, float)) and not isinstance(reset, bool) and math.isfinite(reset) and reset > 0 else None
            snapshots.append(AgentUsageSnapshot('codex', short(limit, 24) + ' · ' + label, used, reset, now, 'Codex account/rateLimits/read', short(data.get('planType')) or None))
    return snapshots


def claude_quota_snapshots(payload,now=None):
    """Documented statusLine rate_limits; context-window percentages are not quotas."""
    rates=payload.get('rate_limits')
    if not isinstance(rates,dict):return []
    converted={}
    for key,window,minutes in [('five_hour','primary',300),('seven_day','secondary',10080)]:
        value=rates.get(key)
        if isinstance(value,dict):converted[window]={'usedPercent':value.get('used_percentage'),'resetsAt':value.get('resets_at'),'windowDurationMins':minutes}
    snapshots=quota_snapshots({'rateLimits':converted},now)
    for snapshot in snapshots:
        snapshot.provider='claude'
        snapshot.window=snapshot.window.replace('codex · ','')
        snapshot.source='Claude Code statusLine rate_limits'
    return snapshots


def opencode_quota_snapshots(response,now=None):
    """OpenCode's UsageLimits.Info: Go windows and explicit global monthly budgets."""
    now=time.time() if now is None else now
    info=response.get('data') if isinstance(response,dict) and 'data' in response else response
    if not isinstance(info,dict):return []
    snapshots=[]
    go=info.get('go')
    if isinstance(go,dict):
        for key,label in [('rolling','5-hour'),('weekly','Weekly'),('monthly','Monthly')]:
            meter=go.get(key)
            if not isinstance(meter,dict):continue
            percent,reset=meter.get('percent'),meter.get('resetsAt')
            if isinstance(percent,bool) or not isinstance(percent,(int,float)) or not math.isfinite(percent) or not 0<=percent<=100:continue
            reset=reset/1000 if isinstance(reset,(int,float)) and not isinstance(reset,bool) and math.isfinite(reset) and reset>0 else None
            snapshots.append(AgentUsageSnapshot('opencode','Go · '+label,percent,reset,now,'OpenCode experimental.usage.limits'))
    # A workspace budget is not a Go subscription or a per-model allowance.
    budgets=info.get('budgets')
    for budget in (budgets[:16] if isinstance(budgets,list) else []):
        if not isinstance(budget,dict) or budget.get('coverage')!='all' or budget.get('per')!='set':continue
        limit,spent=budget.get('limit'),budget.get('spent')
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in (limit,spent)) or limit<=0 or spent<0:continue
        reset=budget.get('resetsAt')
        reset=reset/1000 if isinstance(reset,(int,float)) and not isinstance(reset,bool) and math.isfinite(reset) and reset>0 else None
        label='Workspace budget' if budget.get('shared') else 'Member budget'
        snapshots.append(AgentUsageSnapshot('opencode',label+' · Monthly',min(100,spent/limit*100),reset,now,'OpenCode Console budget (not a Go allowance)'))
    return snapshots
