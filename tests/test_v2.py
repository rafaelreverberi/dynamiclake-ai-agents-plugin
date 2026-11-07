"""Synthetic fixtures only: no accounts, transcripts or real provider settings."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]/'AIAgents.dynamiclakeplugin'
sys.path.insert(0,str(PACKAGE))
import agent_models as models
from agent_providers import IncrementalSession, LocalJSONLProvider, OpenCodeProvider, Timeline
from agent_bridge import HookBridge, normalize_event
from agent_presentation import Presentation
from agent_runtime import Controller
from integrations import update_config

spec=importlib.util.spec_from_file_location('monitor_v2',PACKAGE/'ai-agents-monitor.py')
legacy=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=legacy
spec.loader.exec_module(legacy)


def write_event(path,kind,payload):
    with path.open('a') as out:
        out.write(json.dumps({'type':kind,'timestamp':legacy.datetime.now(legacy.timezone.utc).isoformat(),'payload':payload})+'\n')


def session(id='s',provider='codex',phase='tool',project='private-project'):
    return models.AgentSession(provider,id,project,phase,'Working',time.time())


class ReaderTests(unittest.TestCase):
    def test_codex_native_command_steps_and_thinking(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'session.jsonl'
            write_event(path,'session_meta',{'id':'session'})
            write_event(path,'event_msg',{'type':'task_started','turn_id':'turn'})
            write_event(path,'event_msg',{'type':'item_completed','item':{'type':'Reasoning','id':'thinking'}})
            write_event(path,'response_item',{'type':'custom_tool_call','name':'exec','call_id':'wrapper'})
            write_event(path,'event_msg',{'type':'item_completed','item':{
                'type':'CommandExecution','id':'command','status':'completed','exit_code':0,
                'parsed_cmd':[{'type':'read','path':'/private/Settings.swift'}]}})
            write_event(path,'response_item',{'type':'reasoning'})
            state=IncrementalSession(path,'codex',legacy).read()
        self.assertEqual([(s.label,s.status) for s in state.steps],[('Read Settings.swift','completed')])
        view=Presentation(legacy)
        timeline=json.dumps(view.timeline(state,{'hideFileNames':True}))
        self.assertIn('Read file',timeline)
        self.assertIn('Thinking',timeline)
        self.assertNotIn('Settings.swift',timeline)

    def test_codex_summary_counts_only_completed_patch_changes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'session.jsonl'
            write_event(path,'session_meta',{'id':'session'})
            write_event(path,'event_msg',{'type':'task_started','turn_id':'turn'})
            changes={'/private/example':{'type':'update','unified_diff':'--- a\n+++ b\n@@ -1 +1,2 @@\n-old\n+new\n+second\n'}}
            for status in ('completed','failed'):
                write_event(path,'event_msg',{'type':'item_completed','item':{
                    'type':'FileChange','id':status,'status':status,'changes':changes}})
            state=IncrementalSession(path,'codex',legacy).read()
        view=Presentation(legacy)
        self.assertEqual(view.task_summary(state,{}),'Recent edits · +2 / −1 lines')

    def test_concurrent_codex_sessions_and_new_session_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for sid in ['a','b']:
                p=root/(sid+'.jsonl')
                write_event(p,'session_meta',{'id':sid,'cwd':'/tmp/'+sid})
                write_event(p,'event_msg',{'type':'task_started','turn_id':sid})
            provider=LocalJSONLProvider('codex',root,legacy)
            states=provider.sessions()
            self.assertEqual({s.id for s in states},{'a','b'})
            self.assertEqual(len({s.activity_id for s in states}),2)
            before=sum(r.bytes_read for r in provider.readers.values())
            provider.sessions()
            self.assertEqual(before,sum(r.bytes_read for r in provider.readers.values()))
            write_event(root/'c.jsonl','session_meta',{'id':'c'})
            provider.last_scan=-100
            self.assertEqual(len(provider.sessions()),3)

    def test_partial_line_corruption_rotation_and_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'one.jsonl'
            p.write_bytes(b'{broken}\n{"type":"session_meta","payload":{"id":"s"}}\n')
            r=IncrementalSession(p,'codex',legacy)
            self.assertEqual(r.read().id,'s')
            part=json.dumps({'type':'event_msg','timestamp':legacy.datetime.now(legacy.timezone.utc).isoformat(),'payload':{'type':'task_started'}}).encode()
            with p.open('ab') as f:f.write(part[:20])
            self.assertEqual(r.read().phase,'paused')
            with p.open('ab') as f:f.write(part[20:]+b'\n')
            self.assertEqual(r.read().phase,'running')
            p.write_text('{"type":"session_meta","payload":{"id":"new"}}\n')
            self.assertEqual(r.read().id,'new')
            p.rename(p.with_suffix('.old'))
            write_event(p,'session_meta',{'id':'rotated'})
            self.assertEqual(r.read().id,'rotated')

    def test_completion_metadata_cannot_revive(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.jsonl'
            write_event(p,'event_msg',{'type':'task_started'})
            write_event(p,'event_msg',{'type':'task_complete'})
            r=IncrementalSession(p,'codex',legacy)
            old=r.read()
            write_event(p,'event_msg',{'type':'thread_settings_applied'})
            now=r.read()
            self.assertEqual(now.updated_at,old.updated_at)
            self.assertEqual(now.phase,'completed')

    def test_long_log_infers_latest_turn_without_old_header_turn(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.jsonl'
            write_event(p,'session_meta',{'id':'s'})
            write_event(p,'event_msg',{'type':'task_started','turn_id':'old'})
            with p.open('a') as f:f.write('{"padding":"'+('x'*600000)+'"}\n')
            write_event(p,'event_msg',{'type':'task_complete','turn_id':'new'})
            r=IncrementalSession(p,'codex',legacy)
            self.assertEqual(r.read().phase,'completed')
            self.assertLessEqual(r.bytes_read,608000)

    def test_claude_real_tool_result_and_completion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'claude.jsonl'
            def append(v):
                with p.open('a') as f:f.write(json.dumps({'sessionId':'c','timestamp':legacy.datetime.now(legacy.timezone.utc).isoformat(),**v})+'\n')
            append({'type':'assistant','message':{'content':[{'type':'tool_use','id':'call','name':'Read','input':{'file_path':'/tmp/secret.txt'}}]}})
            r=IncrementalSession(p,'claude',legacy)
            self.assertEqual(r.read().steps[0].status,'running')
            append({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'call','is_error':True,'content':'private output'}]}})
            s=r.read()
            self.assertEqual(s.steps[0].status,'failed')
            self.assertNotIn('private output',str(s))
            append({'type':'assistant','message':{'stop_reason':'end_turn','content':[{'type':'text','text':'private answer'}]}})
            self.assertEqual(r.read().phase,'completed')

    def test_tool_output_is_not_automatically_success(self):
        t=Timeline()
        t.consume('codex',{'type':'response_item','payload':{'type':'function_call','call_id':'c','name':'functions.exec_command','arguments':'{"cmd":"secret"}'}})
        t.consume('codex',{'type':'response_item','payload':{'type':'function_call_output','call_id':'c','output':'Tool returned'}})
        self.assertEqual(t.steps[0].status,'observed')
        self.assertNotIn('secret',str(t.steps))

    def test_open_code_error_is_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'opencode.db';db.write_text('not sqlite')
            with patch.dict(os.environ,{'OPENCODE_DB':str(db)}):
                provider=OpenCodeProvider(legacy)
                self.assertEqual(provider.sessions(),[])
                self.assertIn('incompatible',provider.health)

    def test_missing_provider_does_not_fail(self):
        p=LocalJSONLProvider('codex',Path('/missing/no-sessions'),legacy)
        self.assertEqual(p.sessions(),[])
        self.assertIn('no local sessions',p.health)


class ModelTests(unittest.TestCase):
    def test_quota_used_remaining_multiple_windows(self):
        result={'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300,'resetsAt':1800000000},'secondary':{'usedPercent':5,'windowDurationMins':10080}}}
        q=models.quota_snapshots(result,time.time())
        self.assertEqual(len(q),2)
        self.assertEqual(q[0].remaining_percent,80)
        self.assertIn('5-hour',q[0].window)
        self.assertEqual(q[1].resets_at,None)
        self.assertFalse(q[0].stale)

    def test_unknown_invalid_and_stale_quota(self):
        for value in [None,-2,101,True,float('nan'),'20']:
            self.assertEqual(models.quota_snapshots({'rateLimits':{'primary':{'usedPercent':value}}}),[])
        q=models.quota_snapshots({'rateLimits':{'primary':{'usedPercent':0}}},1)[0]
        self.assertTrue(q.stale)
        self.assertEqual(q.remaining_percent,100)
        self.assertEqual(models.quota_snapshots({}),[])

    def test_unknown_work_has_no_percentage(self):
        p=Presentation(legacy)
        m=p.activity(session(),'create',{})
        self.assertNotIn('value',m['surfaces']['compactLiveActivity']['rightSlot'])
        self.assertEqual(m['size'],'small')

    def test_permission_lifetime_and_interruption(self):
        s=session(phase='permission');s.updated_at=1;s.permission_id='pending'
        self.assertTrue(s.visible())
        s.permission_id=None
        self.assertFalse(s.visible())
        s=session(phase='interrupted');self.assertFalse(s.visible())


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'AI_AGENTS_BRIDGE_DIR':self.tmp.name})
        self.env.start()
        self.bridge=HookBridge(lambda:True)
        self.bridge.start()
        self.clients=[]

    def tearDown(self):
        for c in self.clients:c.close()
        self.bridge.close()
        self.env.stop();self.tmp.cleanup()

    def request(self,sid='s',event='PermissionRequest',provider='claude'):
        c=socket.socket(socket.AF_UNIX);c.settimeout(3);c.connect(str(self.bridge.path));self.clients.append(c)
        data={'provider':provider,'event':event,'data':{'session_id':sid,'conversation_id':sid,'tool_name':'Bash','tool_input':{'command':'swift build'},'cwd':'/tmp/project'}}
        c.sendall(json.dumps(data).encode()+b'\n')
        for _ in range(50):
            if self.bridge.permissions():break
            time.sleep(.01)
        return c

    def test_approve_original_request_and_replay_rejected(self):
        c=self.request();p=self.bridge.permissions()[0]
        self.assertEqual(p.session_id,'s')
        self.assertTrue(self.bridge.decide(p.id,'allow'))
        self.assertFalse(self.bridge.decide(p.id,'allow'))
        self.assertEqual(json.loads(c.recv(2048))['decision'],'allow')

    def test_concurrent_permission_sessions_cannot_cross_route(self):
        a=self.request('a');b=self.request('b')
        for _ in range(50):
            if len(self.bridge.permissions())==2:break
            time.sleep(.01)
        ps={p.session_id:p for p in self.bridge.permissions()}
        self.assertTrue(self.bridge.decide(ps['b'].id,'deny'))
        self.assertEqual(json.loads(b.recv(2048)),{'decision':'deny'})
        self.assertEqual([p.session_id for p in self.bridge.permissions()],['a'])
        self.bridge.cancel_permissions()
        self.assertEqual(json.loads(a.recv(2048)),{})

    def test_expired_request_falls_back(self):
        c=self.request();p=self.bridge.permissions()[0];p.deadline=0
        self.assertFalse(self.bridge.decide(p.id,'allow'))
        self.assertEqual(json.loads(c.recv(2048)),{})

    def test_provider_disconnect_removes_request(self):
        c=self.request();c.close()
        for _ in range(50):
            if not self.bridge.permissions():break
            time.sleep(.02)
        self.assertFalse(self.bridge.permissions())

    def test_shutdown_unblocks_hook(self):
        c=self.request();self.bridge.close()
        self.assertEqual(json.loads(c.recv(2048)),{})

    def test_malformed_and_oversized_input(self):
        for raw in [b'{bad}\n',b'x'*64001+b'\n']:
            c=socket.socket(socket.AF_UNIX);c.settimeout(2);c.connect(str(self.bridge.path));self.clients.append(c)
            c.sendall(raw)
            self.assertEqual(json.loads(c.recv(2048)),{})
        self.assertEqual(self.bridge.permissions(),[])

    def test_private_permissions_and_second_listener(self):
        self.assertEqual(self.bridge.path.stat().st_mode & 0o777,0o600)
        with self.assertRaises(OSError):HookBridge().start()
        self.assertTrue(self.bridge.path.exists())

    def test_hook_normalization_discards_prompt_output_email(self):
        e=normalize_event({'provider':'claude','event':'PreToolUse','data':{'session_id':'s','tool_name':'Shell','tool_input':{'command':'secret'},'prompt':'private','output':'private','user_email':'person'}})
        self.assertNotIn('private',str(e));self.assertNotIn('secret',str(e));self.assertNotIn('person',str(e))

    def test_oversized_action_cannot_be_approved(self):
        with self.assertRaises(ValueError):
            normalize_event({'provider':'claude','event':'PermissionRequest','data':{'session_id':'s','tool_input':{'command':'x'*1600}}})

    def test_hook_stdio_round_trip_returns_documented_decision(self):
        import subprocess
        payload={'session_id':'stdio-session','hook_event_name':'PermissionRequest','tool_name':'Bash','tool_input':{'command':'swift build'},'prompt':'discard me'}
        p=subprocess.Popen([sys.executable,str(PACKAGE/'agent_hook.py'),'claude','PermissionRequest'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        try:
            p.stdin.write(json.dumps(payload).encode());p.stdin.close()
            for _ in range(100):
                pending=self.bridge.permissions()
                if pending:break
                time.sleep(.01)
            self.assertTrue(pending)
            self.assertTrue(self.bridge.decide(pending[0].id,'allow'))
            output=p.stdout.read();p.wait(timeout=3)
            self.assertEqual(json.loads(output),{'hookSpecificOutput':{'hookEventName':'PermissionRequest','decision':{'behavior':'allow'}}})
            self.assertEqual(p.stderr.read(),b'')
        finally:
            if p.poll() is None:p.kill();p.wait()
            p.stdout.close();p.stderr.close()

    def test_codex_approval_is_independent_of_claude(self):
        self.bridge.codex_approvals=lambda:True
        self.bridge.approvals=lambda:False
        client=self.request(provider='codex')
        permission=self.bridge.permissions()[0]
        self.assertEqual(permission.provider,'codex')
        self.bridge.cancel_permissions('claude')
        self.assertTrue(self.bridge.decide(permission.id,'allow'))
        self.assertEqual(json.loads(client.recv(2048)),{'decision':'allow'})

    def test_removed_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_event({'provider':'cursor','event':'stop','data':{'conversation_id':'c'}})

    def test_restart_cannot_replay_old_permission(self):
        c=self.request();old=self.bridge.permissions()[0].id
        self.bridge.close();self.assertEqual(json.loads(c.recv(2048)),{})
        self.bridge=HookBridge(lambda:True);self.bridge.start()
        self.assertFalse(self.bridge.decide(old,'allow'))


class IntegrationTests(unittest.TestCase):
    def test_install_idempotent_uninstall_preserves_other_hooks(self):
        for provider in ['claude']:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'config.json';before={'theme':'keep','hooks':{'custom':[{'command':'unrelated'}]}}
                p.write_text(json.dumps(before))
                self.assertTrue(update_config(p,provider,True))
                installed=json.loads(p.read_text())
                self.assertFalse(update_config(p,provider,True))
                installed['anotherSetting']='later';p.write_text(json.dumps(installed))
                self.assertTrue(update_config(p,provider,False))
                after=json.loads(p.read_text())
                self.assertEqual(after['hooks'],before['hooks'])
                self.assertEqual(after['anotherSetting'],'later')
                self.assertEqual(after['theme'],'keep')

    def test_malformed_config_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';p.write_text('{bad}')
            with self.assertRaises(ValueError):update_config(p,'claude',True)
            self.assertEqual(p.read_text(),'{bad}')

    def test_symlink_config_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';target=Path(d)/'target';target.write_text('{}');p.symlink_to(target)
            with self.assertRaises(ValueError):update_config(p,'claude',True)
            self.assertEqual(target.read_text(),'{}')


class PresentationTests(unittest.TestCase):
    def test_privacy_on_every_surface(self):
        p=Presentation(legacy);s=session();s.steps=[models.AgentTaskStep('x','Read private.swift','running','private.swift')]
        values={'hideProjectNames':True,'hideFileNames':True}
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):
            a=p.activity(s,'create',values)
            p.page='session';p.selected=s.activity_id
            lake=p.lake([s],[],[],{},values)
        wire=json.dumps([a,lake]);self.assertNotIn('private-project',wire);self.assertNotIn('private.swift',wire)

    def test_surface_feature_gates(self):
        p=Presentation(legacy)
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake'}):
            m=p.lake([session()],[],[],{},{});self.assertEqual(set(m['lake']),{'title','subtitle'})
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':''}):
            m=p.activity(session(phase='completed'),'update',{},notify=True)
            self.assertNotIn('presentSneakPeek',m)

    def test_layout_budget_with_many_sessions_and_approvals(self):
        p=Presentation(legacy)
        permissions=[models.AgentPermissionRequest(str(i),'claude',str(i),'Bash','project','{}',time.monotonic()+90) for i in range(16)]
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):
            m=p.lake([session(str(i)) for i in range(64)],permissions,[],{}, {})
        def count(c):return 1+sum(count(x) for x in c.get('children',[]))
        self.assertLessEqual(sum(count(c) for c in m['lake']['content']+m['lake'].get('bottom',[])),160)
        self.assertIn('Next session',json.dumps(m))
        self.assertTrue(m['lake']['hideHeader'])

    def test_minimized_image_is_mandatory_even_with_old_logo_switch_off(self):
        p=Presentation(legacy)
        for provider in ('claude','codex','opencode'):
            for phase in ('tool','failed','permission','completed'):
                m=p.activity(session(provider=provider,phase=phase),'create',{'showAgentLogos':False})
                for surface in ('compactLiveActivity','extraLiveActivity','sneakPeek'):
                    self.assertEqual(m['surfaces'][surface]['leftSlot']['source'],'inlineData')
                if phase!='tool':self.assertIn('rightSlot',m['surfaces']['sneakPeek'])

    def test_three_remaining_rings_with_actual_logos_and_no_status_screen(self):
        p=Presentation(legacy);p.page='usage'
        q=models.AgentUsageSnapshot('codex','codex · 5-hour',38,updated_at=time.time())
        sent=[]
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,imageAssets'}):
            m=p.lake([],[],[q],{}, {'enableUsageTracking':True},sent.append)
        def walk(value):
            yield value
            for child in value.get('children',[]):yield from walk(child)
        components=[c for root in m['lake']['content'] for c in walk(root)]
        labels=[c.get('text','') for c in components]
        self.assertIn('62% left',labels)
        self.assertEqual(labels.count('Unavailable'),2)
        self.assertEqual(len([c for c in components if c.get('type')=='zstack']),3)
        self.assertFalse(any(c.get('actionID')=='tab:diagnostics' for c in components))
        self.assertEqual(len({m['asset']['id'] for m in sent}),6)

    def test_quota_updates_reregister_only_changed_ring(self):
        p=Presentation(legacy);p.page='usage';sent=[]
        q=models.AgentUsageSnapshot('codex','codex · Weekly',20,updated_at=time.time())
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,imageAssets'}):
            p.lake([],[],[q],{}, {},sent.append)
            sent.clear()
            p.lake([],[],[q],{}, {},sent.append)
            self.assertEqual(sent,[])
            q.used_percent=25
            p.lake([],[],[q],{}, {},sent.append)
        self.assertEqual([m['asset']['id'] for m in sent],['quota-ring-codex'])

    def test_usage_unavailable_never_zero(self):
        p=Presentation(legacy);p.page='usage'
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):m=p.lake([],[],[],{}, {})
        labels=[c.get('text','') for tile in m['lake']['content'][1]['children'] for c in tile.get('children',[])]
        self.assertEqual(labels.count('Unavailable'),3)
        self.assertFalse(any('0%' in label for label in labels))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.c=Controller(legacy);self.sent=[];self.c.client.send=self.sent.append
        self.c.client.read_available=lambda timeout:[]
        self.c.bridge.start=lambda:None
        self.c.usage.refresh=lambda enabled:None

    def test_two_sessions_deduplicate_and_independent_completion(self):
        a,b=session('a'),session('b')
        self.c.registry.collect=lambda values:{s.activity_id:s for s in [a,b]}
        self.c.refresh_sources();self.c.refresh_sources()
        self.assertEqual(len([m for m in self.sent if m['type']=='create']),1)
        self.assertEqual(len(self.c.sessions),2)
        self.assertEqual(len([m for m in self.sent if m['type']=='update']),0)
        if a.activity_id not in self.c.published:a,b=b,a
        a.updated_at=0
        self.c.refresh_sources()
        dismissed=[m['activityID'] for m in self.sent if m['type']=='dismiss']
        self.assertIn(a.activity_id,dismissed);self.assertNotIn(b.activity_id,dismissed)
        self.assertEqual(set(self.c.published),{b.activity_id})

    def test_callback_wrong_session_and_replay_cannot_approve(self):
        self.c.presentation.page='permission';self.c.presentation.permission_id='valid'
        self.c.client.read_available=lambda timeout:[{'type':'action','surface':'lake','activityID':'wrong','actionID':'allow:valid'}]
        with patch.object(self.c.bridge,'decide') as decide:
            self.c.handle_callbacks();decide.assert_not_called()
        self.c.client.read_available=lambda timeout:[{'type':'action','surface':'lake','activityID':'lake','actionID':'allow:wrong'}]
        with patch.object(self.c.bridge,'decide') as decide:
            self.c.handle_callbacks();decide.assert_not_called()

    def test_hidden_project_setting_republishes(self):
        a=session();self.c.registry.collect=lambda values:{a.activity_id:a}
        self.c.refresh_sources()
        with patch.object(legacy,'plugin_settings',return_value={'hideProjectNames':True}):self.c.refresh_sources()
        update=[m for m in self.sent if m['type']=='update'][-1]
        self.assertNotIn('private-project',json.dumps(update))

    def test_dismissed_turn_stays_hidden_until_next_turn(self):
        a=session();a.turn_id='turn-one'
        self.c.registry.collect=lambda values:{a.activity_id:a}
        self.c.refresh_sources()
        self.c.client.read_available=lambda timeout:[{'type':'action','activityID':a.activity_id,'actionID':'dismiss','surface':'sneakPeek'}]
        self.c.handle_callbacks()
        self.c.client.read_available=lambda timeout:[]
        a.updated_at=time.time()+1
        self.c.refresh_sources()
        self.assertEqual(len([m for m in self.sent if m['type']=='create']),1)
        a.turn_id='turn-two'
        self.c.refresh_sources()
        self.assertEqual(len([m for m in self.sent if m['type']=='create']),2)

    def test_invalid_settings_root_degrades_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_text('[]')
            with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_SETTINGS_PATH':str(p)}):
                self.assertEqual(legacy.plugin_settings(),{})


class UsageLifecycleTests(unittest.TestCase):
    def test_shutdown_cancels_worker_and_discards_result(self):
        from agent_usage import UsageMonitor
        entered=threading.Event()
        def read(cancel=None):
            entered.set()
            cancel.wait(1)
            return [models.AgentUsageSnapshot('codex','test',10)]
        with patch('agent_usage.read_codex_quota',side_effect=read):
            monitor=UsageMonitor();monitor.refresh(True,provider='codex')
            self.assertTrue(entered.wait(1))
            monitor.close()
            self.assertFalse(monitor.worker.is_alive())
            self.assertEqual(monitor.snapshots,[])


class FramingTests(unittest.TestCase):
    def test_fragmented_frames_and_reconnect_reset(self):
        a,b=socket.socketpair();client=legacy.DynamicLakeJSONClient();client.socket=a;a.setblocking(False);client.selector.register(a,1)
        payload=json.dumps({'type':'action','actionID':'dismiss'}).encode();frame=struct.pack('>I',len(payload))+payload
        b.sendall(frame[:2]);self.assertEqual(client.read_available(.1),[])
        b.sendall(frame[2:]);self.assertEqual(client.read_available(.1)[0]['type'],'action')
        b.sendall(frame[:5]);client.read_available(.1);client.close();b.close()
        self.assertEqual(client.buffer,b'');self.assertIsNone(client.expected_length)

    def test_oversized_inbound_frame_rejected(self):
        a,b=socket.socketpair();client=legacy.DynamicLakeJSONClient();client.socket=a;a.setblocking(False);client.selector.register(a,1)
        try:
            b.sendall(struct.pack('>I',300000))
            with self.assertRaises(ValueError):client.read_available(.1)
        finally:client.close();b.close()


if __name__=='__main__':unittest.main()
