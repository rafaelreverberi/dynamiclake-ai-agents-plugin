"""Two native views: focused progress and three-provider quota rings."""
from __future__ import annotations
import base64
import hashlib
import math
import time
import textwrap
from datetime import datetime, timezone
from agent_models import format_minutes, short
from agent_artwork import quota_ring

NAMES={'codex':'Codex','claude':'Claude','opencode':'OpenCode'}
COLORS={'codex':'blue','claude':'orange','opencode':'cyan'}
SYMBOLS={'codex':'terminal.fill','claude':'sparkles','opencode':'chevron.left.forwardslash.chevron.right'}


def text(value,secondary=False,**kw):
    return {'type':'text','text':short(value,180),**({'style':'compact','tint':'gray'} if secondary else {}),**kw}


def image(symbol,tint='gray',**kw):
    return {'type':'image','source':'sfSymbol','systemImage':symbol,'tint':tint,**kw}


def button(title,action,symbol,tint='gray',**kw):
    return {'type':'button','title':title,'actionID':action,'systemImage':symbol,'shape':'roundedRect','tint':tint,**kw}


def row(*children,**kw):
    return {'type':'hstack','spacing':12,'children':list(children),**kw}


def column(*children,**kw):
    return {'type':'vstack','spacing':8,'children':list(children),**kw}


def status(phase):
    return {'completed':'success','failed':'failed','permission':'warning','paused':'paused','interrupted':'paused'}.get(phase,'inProgress')


def rank(s):
    return ({'permission':0,'failed':1,'completed':3,'paused':4}.get(s.phase,2),s.provider,s.activity_id)


class Presentation:
    def __init__(self,legacy):
        self.legacy=legacy
        self.page='progress'
        self.selected=None
        self.permission_id=None
        self.registered=set()
        self.asset_versions={}
        self.quota_window='5-hour'
        self.usage_provider=None
        self.setup_provider=None

    @property
    def features(self):
        import os
        return set(os.environ.get('DYNAMICLAKE_PLUGIN_FEATURES','').split(','))

    def asset(self,name,data,send=None):
        if 'imageAssets' in self.features and send:
            version=hashlib.sha256(data).hexdigest()
            if name not in self.registered or self.asset_versions.get(name)!=version:
                send({'schemaVersion':1,'type':'asset','asset':{'id':name,'mimeType':'image/png','base64Data':base64.b64encode(data).decode()}})
                self.registered.add(name)
                self.asset_versions[name]=version
            return {'type':'image','source':'asset','assetID':name}
        return {'type':'image','source':'inlineData','mimeType':'image/png','base64Data':base64.b64encode(data).decode()}

    def logo(self,provider,settings,send=None):
        source=next(s for s in self.legacy.ALL_SOURCES if s.key==provider)
        logo=self.legacy.source_logo(source,settings)
        if logo:
            data=base64.b64decode(logo['base64Data'])
            name='agent-'+self.legacy.selected_logo_name(source,settings).replace('.png','')
            return self.asset(name,data,send)
        return image(SYMBOLS[provider],COLORS[provider])

    def choose(self,sessions):
        ordered=sorted(sessions,key=rank)
        if not ordered:return None
        current=next((s for s in ordered if s.activity_id==self.selected),None)
        # Keep selection stable, but an actionable approval/error takes precedence over active/finished work.
        if current is None or rank(ordered[0])[0]<rank(current)[0]:current=ordered[0]
        self.selected=current.activity_id
        return current

    def step_label(self,step,settings):
        return step.label.replace(step.file_name,'file') if settings.get('hideFileNames',False) and step.file_name else step.label

    def detail(self,s,settings):
        if not settings.get('showToolDescriptions',True):return 'Working' if s.phase not in ('completed','failed','permission') else s.detail
        if s.steps and s.phase not in ('completed','failed','permission','thinking','responding'):
            step=s.steps[-1]
            if s.provider!='codex' or step.status=='running':
                return self.step_label(step,settings)
        return s.detail

    def activity(self,s,command,settings,send=None,notify=False,permission=None):
        logo=self.logo(s.provider,settings,send)
        tint={'completed':'green','failed':'red','permission':'orange'}.get(s.phase,COLORS[s.provider])
        right={'type':'status','status':status(s.phase),'tint':tint} if s.phase in ('completed','failed','permission') else {'type':'progress','tint':tint}
        project=s.project if not settings.get('hideProjectNames',False) else 'Project hidden'
        msg={'schemaVersion':1,'type':command,'activityID':s.activity_id,'title':'AI Agents','size':'small',
             'priority':'high' if s.permission_id else 'normal','surfaces':{
                 'compactLiveActivity':{'leftSlot':logo,'rightSlot':right},'extraLiveActivity':{'leftSlot':logo},
                 'sneakPeek':{'leftSlot':logo,'center':text(NAMES[s.provider]+' · '+project+' · '+self.detail(s,settings),style='marquee')}}}
        if s.phase in ('completed','failed','permission'):
            msg['surfaces']['sneakPeek']['rightSlot']=right.copy()
        if permission:
            msg['surfaces']['sneakPeek']={
                'leftSlot':logo,
                'center':text(f'{NAMES[s.provider]} needs approval · Open to review',style='marquee'),
                'rightSlot':image('hand.raised.fill','orange')}
        if notify and 'presentSneakPeek' in self.features:
            flag={'completed':'notifyCompletion','failed':'notifyErrors','permission':'notifyPermissions'}.get(s.phase)
            if flag and settings.get(flag,True):msg['presentSneakPeek']=8 if permission else 2
        return msg

    def usage_summary(self,usage):
        values=[]
        for provider,name in NAMES.items():
            quota=self.quota_choice(provider,usage)
            if quota:
                values.append(f'{name} {quota.remaining_percent:g}% left · {quota.window}')
        return ' / '.join(values) or 'No account limits available'

    def navigation(self,title,settings):
        setup=[] if settings.get('hideSetupButton') else [
            button('Setup','tab:setup','gearshape','green' if title=='Setup' else 'gray',shape='circle',size=28)]
        return row(image('list.bullet.circle' if title=='Progress' else ('gearshape' if title=='Setup' else 'gauge'),'gray',size=20),
                   text(title,weight='bold'),{'type':'spacer'},*setup,
                   button('Progress','tab:progress','checklist','green' if title=='Progress' else 'gray',shape='circle',size=28),
                   button('Usage','tab:usage','gauge','green' if title=='Usage' else 'gray',shape='circle',size=28))

    def timeline(self,s,settings):
        thinking=s.phase=='thinking' and settings.get('showToolDescriptions',True)
        steps=s.steps[-(2 if thinking else 3):] if settings.get('showTaskSteps',True) else []
        if not steps:return [row(image('sparkle',COLORS[s.provider],size=16),text(self.detail(s,settings)))]
        result=[]
        for step in steps:
            symbol={'completed':'checkmark','failed':'exclamationmark.triangle.fill','running':'play.fill','observed':'circle'}.get(step.status,'circle')
            result.append(row(image(symbol,COLORS[s.provider],size=16),text(self.step_label(step,settings)),spacing=8))
        if thinking:result.append(row(image('sparkle',COLORS[s.provider],size=16),text('Thinking'),spacing=8))
        return result

    def progress_content(self,s,sessions,permissions,usage,settings,send):
        if s is None:return [column(image('checkmark.circle','gray',size=32),text('Ready when you are',weight='semibold'),text('Your next agent task appears here.',True),alignment='center',padding=16)]
        accent=COLORS[s.provider]
        task=(s.task or s.project) if not settings.get('hideProjectNames',False) else 'Working on your task'
        identity=row({**self.logo(s.provider,settings,send),'size':32},text(NAMES[s.provider],style='large',weight='bold'),spacing=10)
        summary=[identity]
        quota=self.quota_choice(s.provider,usage)
        if quota:
            stale=' · Last known' if quota.stale else ''
            summary.append(row(image('gauge',accent,size=15),
                               text(f'{quota.remaining_percent:g}% left · {quota.window}{stale}',True),spacing=6))
        summary.extend([row(image('circle.fill',accent,size=12),
                            text(self.detail(s,settings),tint=accent,weight='semibold'),spacing=6),
                        text(task,True),
                        text('Running Tasks · '+self.session_summary(sessions),True)])
        content=[row(column(*summary,spacing=7),{'type':'spacer'},
                     column(*self.timeline(s,settings),spacing=8,padding={'leading':12,'trailing':12}),
                     alignment='top',padding={'top':10})]
        if s.steps and s.steps[-1].additions is not None:
            step=s.steps[-1]
            content.append(row(text(self.step_label(step,settings),True),
                               text('+'+str(step.additions),tint='green'),
                               text('−'+str(step.deletions or 0),tint='orange'),text('input lines',True),spacing=6))
        p=next((p for p in permissions if p.id==s.permission_id),None)
        if p:content.append(button('Review permission','permission:'+p.id,'hand.raised.fill','orange'))
        if len(sessions)>1:
            content.append(row(button('Previous session','cycle:previous','chevron.left',shape='plain',size=18),
                text(str(len(sessions))+' sessions',True),button('Next session','cycle:next','chevron.right',shape='plain',size=18),{'type':'spacer'},
                {'type':'status','status':status(s.phase),'tint':accent,'size':16}))
        return content

    def session_summary(self,sessions):
        waiting=sum(s.phase=='permission' for s in sessions)
        finished=sum(s.phase in ('completed','failed') for s in sessions)
        active=len(sessions)-waiting-finished
        parts=[f'{active} active']
        if waiting:parts.append(f'{waiting} waiting')
        if finished:parts.append(f'{finished} finished')
        return ' · '.join(parts)

    def task_summary(self,s,settings):
        edits=[step for step in s.steps if step.status=='completed' and step.additions is not None]
        added=sum(step.additions for step in edits)
        removed=sum(step.deletions or 0 for step in edits)
        if added or removed:
            return f'Recent edits · +{added} / −{removed} lines'
        return '' if settings.get('hideProjectNames',False) else s.task or s.project

    def quota_choice(self,provider,usage):
        windows=[u for u in usage if u.provider==provider and u.used_percent is not None and (u.resets_at is None or u.resets_at>time.time())]
        return next((u for u in windows if self.quota_window.lower() in u.window.lower()),windows[0] if windows else None)

    def quota_tile(self,provider,usage,settings,send,compact=False):
        quota=self.quota_choice(provider,usage)
        remaining=quota.remaining_percent if quota else None
        ring=self.asset('quota-ring-'+provider,quota_ring(provider,round(remaining,1) if quota else None),send)
        ring['size']=38 if compact else 80
        logo={**self.logo(provider,settings,send),'size':18 if compact else 32}
        if not compact:
            action={'actionID':'quota:'+provider,'title':NAMES[provider]+' usage details'}
            ring.update(action)
            logo.update(action)
        label=f'{remaining:g}% left' if quota else 'Unavailable'
        if compact and quota and quota.stale:
            label+=' · Stale'
        name=text(NAMES[provider],weight='bold')
        if compact:name['style']='compact'
        labels=[name,text(label,True,weight='semibold')]
        if quota and not compact:
            labels.append(text(quota.window.split('·')[-1].strip(),True))
            if quota.stale:labels.append(text('Stale',True))
        return column({'type':'zstack','alignment':'center','children':[ring,logo]},
                      *labels,alignment='center',spacing=2 if compact else 5)

    def glance_usage(self,usage,settings,send):
        claude,codex,opencode=[self.quota_tile(provider,usage,settings,send,compact=True)
                               for provider in ('claude','codex','opencode')]
        return [row({'type':'spacer'},codex,{'type':'spacer'},spacing=4),
                row({'type':'spacer'},claude,opencode,{'type':'spacer'},alignment='top',spacing=14)]

    def usage_content(self,usage,settings,send):
        available=[label for label in ('5-hour','weekly','monthly') if any(label in u.window.lower() and (u.resets_at is None or u.resets_at>time.time()) for u in usage)]
        if available and self.quota_window not in available:self.quota_window=available[0]
        tiles=[self.quota_tile(provider,usage,settings,send) for provider in ('claude','codex','opencode')]
        content=[row({'type':'spacer'},tiles[0],{'type':'spacer'},tiles[1],{'type':'spacer'},tiles[2],{'type':'spacer'},alignment='top',padding={'top':8,'bottom':4})]
        if available:
            controls=[button({'5-hour':'5-hour','weekly':'Weekly','monthly':'Monthly'}[label],'window:'+label,'clock' if label=='5-hour' else 'calendar',
                'blue' if self.quota_window==label else 'gray',size=24) for label in available]
            if len(controls)>1:content.append(row({'type':'spacer'},*controls,{'type':'spacer'}))
        elif not settings.get('enableUsageTracking',False):content.append(text('Enable Account usage in Plugin Settings.',True))
        return content

    def copy_lines(self,value):
        return [text(line,True) for line in textwrap.wrap(value,60)]

    def setup_content(self,health,settings,send):
        setup=health.get('setup',{})
        usage=health.get('usage',{})
        provider=self.setup_provider
        pending=setup.get('pending')
        if pending:
            remove=pending.startswith('remove_')
            codex=pending.endswith('codex_hooks')
            agent='Codex' if codex else 'Claude'
            title=f'Remove this {agent} integration?' if remove else {
                'claude_usage':'Connect Claude usage?',
                'claude_hooks':'Install Claude approval and activity hooks?',
                'codex_hooks':'Install Codex approval hook?'}[pending]
            lines=[title,'Updates ~/.codex/hooks.json.' if codex else 'Updates ~/.claude/settings.json.',
                   'Existing unrelated hooks are preserved. A private backup is saved before changes.']
            if pending=='claude_usage':lines+=['Adds a local Claude display that forwards only usage limits.','An existing custom display will not be replaced.']
            elif pending=='claude_hooks':lines+=['Adds tool events and supported permission requests.','Approval controls stay optional in Plugin Settings.']
            elif pending=='codex_hooks':lines+=['Adds a PermissionRequest hook. Codex asks you to trust it before running it.']
            else:lines+=['Only this plugin’s entries are removed.']
            return [text(lines[0],weight='bold'),*self.copy_lines(' '.join(lines[1:])),
                row(button('Cancel','setup:cancel','xmark'),button('Remove' if remove else 'Connect','setup-confirm:'+pending,'checkmark','blue',role='confirm'))]
        if provider not in NAMES:
            cards=[]
            descriptions={'claude':'Connect usage and optional activity or approval hooks.','codex':'Check your account limits and configure optional approvals.','opencode':'Read Console and Go limits through OpenCode itself.'}
            for key in ('claude','codex','opencode'):
                cards.append(column(row({**self.logo(key,settings,send),'size':28},text(NAMES[key],weight='bold'),{'type':'spacer'},button('Setup '+NAMES[key],'setup-provider:'+key,'chevron.right',COLORS[key])),text(descriptions[key],True),spacing=4,padding={'bottom':8}))
            return [{'type':'scroll','softFade':'both','children':cards}]
        lines=[];controls=[]
        if provider=='claude':
            lines.append(text('Claude Code approvals',weight='semibold'))
            lines+=self.copy_lines('The local PermissionRequest hook supports one-time approval or denial. After installing it, restart Claude Code and enable Claude activity hooks and Claude approvals in Plugin Settings.')
            controls.append(button('Remove approval and activity hooks' if setup.get('approval_hook') else 'Install approval and activity hooks',
                                   'setup:remove_claude_hooks' if setup.get('approval_hook') else 'setup:claude_hooks','hand.raised','orange'))
            if setup.get('custom_usage'):
                lines+=self.copy_lines('Your custom Claude display is preserved. The automatic usage setup will not replace it; see the manual guide.')
                controls.append(button('Instructions','guide:local','book','orange'))
            elif setup.get('usage'):
                lines+=self.copy_lines('Usage input is installed. Limits arrive after the next Claude response on an eligible account.')
                controls.append(button('Remove usage input','setup:remove_claude_usage','minus.circle'))
            else:
                lines+=self.copy_lines('Connect Claude usage once. This adds a small local display in Claude and forwards its actual 5-hour and weekly limits.')
                controls.append(button('Connect Claude usage','setup:claude_usage','link','orange'))
        elif provider=='codex':
            lines+=self.copy_lines('Sign in using Codex itself. Activity is monitored automatically.')
            lines+=self.copy_lines('Account read: '+usage.get('codex','Not checked'))
            controls=[button('Check usage','check:codex','arrow.clockwise','blue'),button('Open Codex','open-provider:codex','arrow.up.forward.app')]
            installed=setup.get('codex_hooks')
            lines+=self.copy_lines('For optional approvals, trust the installed hook in Codex using /hooks, then enable Codex approvals in Plugin Settings.')
            controls.append(button('Remove approval hook' if installed else 'Install approval hook',
                                   'setup:remove_codex_hooks' if installed else 'setup:codex_hooks','hand.raised','blue'))
        else:
            lines+=self.copy_lines('A recent OpenCode CLI reads its Console limits using its own sign-in. No API key is requested by this plugin.')
            lines+=self.copy_lines('Free models have daily request limits. Go plans have 5-hour, weekly and monthly allowances; model costs vary.')
            lines+=self.copy_lines('The experimental API returns Go allowances and Console budgets. It may not return free-model daily counters.')
            lines+=self.copy_lines('External providers have their own quotas; they are not an OpenCode Go allowance.')
            lines+=self.copy_lines('Account read: '+usage.get('opencode','Not checked'))
            controls=[button('Check usage','check:opencode','arrow.clockwise','cyan'),button('Open Console','guide:console','globe'),button('Limit guide','guide:opencode','book')]
        if not settings.get('enableUsageTracking',False):lines+=self.copy_lines('First enable Usage & limits in Plugin Settings.')
        if provider in ('claude','codex') and provider in (setup.get('last_action') or ''):
            if setup.get('result'):lines+=self.copy_lines(setup['result'])
            if setup.get('busy'):controls=[{'type':'status','status':'inProgress','tint':COLORS[provider]}]
        if health.get('notice'):lines+=self.copy_lines(health['notice'])
        children=controls+lines if provider=='claude' else lines+controls
        return [row({**self.logo(provider,settings,send),'size':28},text('Setup '+NAMES[provider],weight='bold'),{'type':'spacer'},button('Back','setup-provider:all','chevron.left',shape='plain')),
            {'type':'scroll','softFade':'both','children':children}]

    def inset(self,components,amount=16):
        for component in components:
            padding=component.get('padding',{})
            if isinstance(padding,(int,float)):padding={edge:padding for edge in ('top','bottom','leading','trailing')}
            component['padding']={**padding,'leading':min(40,padding.get('leading',0)+amount),'trailing':min(40,padding.get('trailing',0)+amount)}
        return components

    def lake(self,sessions,permissions,usage,health,settings,send=None):
        sessions=sorted((s for s in sessions if s.provider in NAMES),key=rank)
        permission=next((p for p in permissions if p.id==self.permission_id),None) if self.page=='permission' else None
        s=self.choose(sessions) if permission is None else None
        page=self.page if self.page in ('usage','setup') else 'progress'
        always=settings.get('alwaysShowUsage',False)
        if page=='setup' and settings.get('hideSetupButton'):page='progress'
        if page=='progress' and not s and not permission and always:page='usage'
        title={'usage':'Usage','setup':'Setup'}.get(page,'Progress')
        if 'lakeLayout' not in self.features:
            subtitle=self.usage_summary(usage) if page=='usage' else self.detail(s,settings) if s else 'AI Agents'
            return {'schemaVersion':1,'type':'lake','lake':{'title':text(title),'subtitle':text(subtitle)}}
        content=[self.navigation(title,settings)]
        lake={'hideHeader':True,'content':content}
        if permission:
            p=permission
            logo={**self.logo(p.provider,settings,send),'size':32}
            content.extend([row(logo,text(NAMES[p.provider]+' needs approval',style='large',weight='bold'),
                                {'type':'spacer'},image('hand.raised.fill','orange',size=22)),
                text(p.tool+' · '+(p.project if not settings.get('hideProjectNames') else 'Project hidden'),True),
                {'type':'scroll','softFade':'both','children':[{'type':'text','text':p.preview[i:i+32],'style':'compact'} for i in range(0,len(p.preview),32)]}])
            lake['bottom']=[row(button('Deny','deny:'+p.id,'xmark','gray',role='destructive'),button('Approve once','allow:'+p.id,'checkmark','blue',role='confirm'))]
        elif page=='setup':
            content.extend(self.setup_content(health,settings,send))
        elif page=='usage':
            content.extend(self.usage_content(usage,settings,send))
            if self.usage_provider in NAMES:
                u=self.quota_choice(self.usage_provider,usage)
                if u:
                    details=[text(NAMES[u.provider]+' · '+u.window,weight='semibold'),text(f'{u.used_percent:g}% used · {u.remaining_percent:g}% left',True)]
                    if u.resets_at:
                        try:
                            reset=datetime.fromtimestamp(u.resets_at,timezone.utc).astimezone()
                        except (OverflowError,OSError,ValueError):
                            pass
                        else:
                            remaining=max(0,math.ceil((u.resets_at-time.time())/60))
                            details.append(text('Resets in '+format_minutes(remaining),True))
                            details.append(text(reset.strftime('%d %b, %H:%M %Z'),True))
                    updated=datetime.fromtimestamp(u.updated_at,timezone.utc).astimezone()
                    details.append(text(u.source+' · '+updated.strftime('%H:%M %Z'),True))
                else:
                    explanation={'claude':'Connect the optional Claude usage input to show its limits.','codex':'No quota data is available for this account.','opencode':'No Console limits have been returned. Connect OpenCode Console, then check usage.'}
                    details=[text(NAMES[self.usage_provider],weight='semibold'),*self.copy_lines(explanation[self.usage_provider])]
                    if not settings.get('hideSetupButton'):
                        details.append(button('Setup '+NAMES[self.usage_provider],'setup-provider:'+self.usage_provider,'gearshape',COLORS[self.usage_provider]))
                lake['bottom']=details
        else:
            content.extend(self.progress_content(s,sessions,permissions,usage,settings,send))
        glance_session=s
        if permission:
            glance_session=next((session for session in sessions if session.permission_id==permission.id),None)
        if glance_session:
            provider=glance_session.provider
            glance=[row({**self.logo(provider,settings,send),'size':28},
                        column(text(NAMES[provider],weight='bold'),text(self.detail(glance_session,settings),True)))]
            summary=self.task_summary(glance_session,settings)
            if summary:glance.append(text(summary,True))
        else:
            glance=self.glance_usage(usage,settings,send)
        self.inset(content)
        if 'bottom' in lake:self.inset(lake['bottom'])
        lake['glance']={'hideHeader':True,'content':self.inset(glance,8)}
        return {'schemaVersion':1,'type':'lake','lake':lake}
