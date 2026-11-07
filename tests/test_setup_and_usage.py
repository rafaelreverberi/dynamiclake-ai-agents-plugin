"""Guided setup, responsive callbacks, OpenCode quota contract and spacing."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from test_v2 import legacy, session
from agent_models import AgentPermissionRequest, opencode_quota_snapshots
from agent_setup import SetupService
from agent_runtime import Controller
from agent_presentation import Presentation
from agent_usage import UsageMonitor, read_opencode_quota


def limits():
    reset=(time.time()+3600)*1000
    return {'data':{'workspace':{'id':'private-workspace','name':'private-name'},'go':{
        'rolling':{'percent':25,'limited':False,'resetsAt':reset},
        'weekly':{'percent':40,'limited':False,'resetsAt':reset},
        'monthly':{'percent':50,'limited':False,'resetsAt':reset}},'budgets':[]}}


class OpenCodeUsageTests(unittest.TestCase):
    def test_go_windows_and_epoch_units(self):
        result=opencode_quota_snapshots(limits())
        self.assertEqual([v.remaining_percent for v in result],[75,60,50])
        self.assertEqual([v.window for v in result],['Go · 5-hour','Go · Weekly','Go · Monthly'])
        self.assertLess(result[0].resets_at,time.time()+3700)
        self.assertNotIn('private-',str(result))

    def test_free_or_missing_usage_never_becomes_unlimited_or_zero(self):
        for payload in [{'data':None},{'data':{'go':None,'budgets':[]}},{'data':{'budgets':'invalid'}}]:
            self.assertEqual(opencode_quota_snapshots(payload),[])
        p=limits();p['data']['go']['rolling']['percent']=True
        self.assertEqual(len(opencode_quota_snapshots(p)),2)

    def test_model_specific_budgets_not_misrepresented_as_global(self):
        budget={'coverage':'models','per':'model','limit':10,'spent':5,'resetsAt':1800000000000}
        self.assertEqual(opencode_quota_snapshots({'data':{'budgets':[budget]}}),[])
        budget.update(coverage='all',per='set',shared=True)
        result=opencode_quota_snapshots({'data':{'budgets':[budget]}})
        self.assertEqual(result[0].used_percent,50)
        self.assertIn('Workspace budget',result[0].window)
        self.assertIn('not a Go',result[0].source)

    def test_actual_cli_process_contract_is_read_only_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'opencode'
            script.write_text('#!'+os.sys.executable+'\nimport sys,json\nassert sys.argv[1:]==["api","experimental.usage.limits","--standalone"]\nprint('+repr(json.dumps(limits()))+')\n')
            script.chmod(0o755)
            with patch('agent_usage.opencode_binary',return_value=str(script)):
                result=read_opencode_quota(timeout=3)
        self.assertEqual(len(result),3)

    def test_slow_opencode_does_not_delay_codex_or_ui(self):
        entered=threading.Event()
        def slow(cancel=None):entered.set();cancel.wait(2);return []
        with patch('agent_usage.read_opencode_quota',side_effect=slow),patch('agent_usage.read_codex_quota',return_value=[]):
            monitor=UsageMonitor();start=time.monotonic();monitor.refresh(True)
            self.assertLess(time.monotonic()-start,.2)
            self.assertTrue(entered.wait(.5))
            monitor.close()
            self.assertFalse(any(w.is_alive() for w in monitor.workers.values()))

    def test_disabling_usage_discards_inflight_results(self):
        entered=threading.Event()
        def read(cancel=None):
            entered.set();cancel.wait(1)
            return opencode_quota_snapshots(limits())
        with patch('agent_usage.read_opencode_quota',side_effect=read):
            monitor=UsageMonitor();monitor.refresh(True,provider='opencode')
            self.assertTrue(entered.wait(.5))
            monitor.refresh(False);monitor.workers['opencode'].join(timeout=2)
            self.assertEqual(monitor.snapshots,[])


class GuidedSetupTests(unittest.TestCase):
    def test_preview_cancel_and_single_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'settings.json';config.write_text('{"theme":"keep"}')
            setup=SetupService(config)
            self.assertFalse(setup.confirm('claude_usage'))
            self.assertTrue(setup.preview('claude_usage'))
            self.assertEqual(json.loads(config.read_text()),{'theme':'keep'})
            setup.pending=None
            self.assertFalse(setup.confirm('claude_usage'))
            setup.preview('claude_usage');self.assertTrue(setup.confirm('claude_usage'));setup.close()
            self.assertFalse(setup.confirm('claude_usage'))
            self.assertTrue(setup.summary()['usage'])
            self.assertEqual(json.loads(config.read_text())['theme'],'keep')

    def test_expired_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'settings.json';setup=SetupService(config)
            setup.preview('claude_usage');setup.pending_until=0
            self.assertFalse(setup.confirm('claude_usage'));self.assertFalse(config.exists())

    def test_custom_display_preserved_in_guided_setup(self):
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'settings.json';before='{"statusLine":{"command":"keep-me","type":"command"}}';config.write_text(before)
            setup=SetupService(config);self.assertTrue(setup.summary()['custom_usage'])
            setup.preview('claude_usage');setup.confirm('claude_usage');setup.close()
            self.assertEqual(config.read_text(),before)
            self.assertIn('preserved',setup.result)

    def test_remove_hooks_keeps_separate_usage_collector(self):
        with tempfile.TemporaryDirectory() as d:
            setup=SetupService(Path(d)/'settings.json')
            for action in ('claude_usage','claude_hooks','remove_claude_hooks'):
                setup.preview(action);setup.confirm(action);setup.close()
            self.assertTrue(setup.summary()['usage']);self.assertFalse(setup.summary()['hooks'])

    def test_configuration_lock_has_bounded_wait(self):
        import fcntl
        from integrations import update_config
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'settings.json';path.write_text('{}')
            with path.with_name(path.name+'.dynamiclake.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                with patch('integrations.LOCK_WAIT_SECONDS',.05):
                    with self.assertRaises(TimeoutError):update_config(path,'claude',True)
            self.assertEqual(path.read_text(),'{}')

    def test_codex_setup_previews_approval_hook(self):
        p=Presentation(legacy);p.page='setup';p.setup_provider='codex'
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):view=p.lake([],[],[],{}, {})
        self.assertIn('setup:codex_hooks',json.dumps(view))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'hooks.json'
            setup=SetupService(codex_config=path)
            self.assertTrue(setup.preview('codex_hooks'))
            self.assertFalse(path.exists())
            self.assertTrue(setup.confirm('codex_hooks'))
            setup.worker.join(2)
            self.assertTrue(setup.codex_hooks_installed())
            self.assertEqual(list(json.loads(path.read_text())['hooks']),['PermissionRequest'])


class CallbackLayoutTests(unittest.TestCase):
    def test_ui_click_publishes_without_monitoring_refresh(self):
        c=Controller(legacy);sent=[];c.client.send=sent.append
        c.client.read_available=lambda timeout:[{'type':'action','surface':'lake','activityID':'lake','actionID':'tab:usage'}]
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,imageAssets'}),patch.object(c.registry,'collect',side_effect=AssertionError('UI must not poll providers')):
            c.handle_callbacks()
        self.assertTrue(any(m['type']=='lake' for m in sent))
        self.assertEqual(c.presentation.page,'usage')

    def test_padding_keeps_content_and_right_details_inset(self):
        p=Presentation(legacy);s=session()
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):view=p.lake([s],[],[],{}, {})
        for c in view['lake']['content']:
            self.assertGreaterEqual(c['padding']['leading'],16)
            self.assertGreaterEqual(c['padding']['trailing'],16)
        detail_column=view['lake']['content'][1]['children'][-1]
        self.assertGreaterEqual(detail_column['padding']['trailing'],12)

    def test_setup_callback_needs_visible_preview_to_write(self):
        c=Controller(legacy);c.client.send=lambda message:None
        c.client.read_available=lambda timeout:[{'type':'action','surface':'lake','activityID':'lake','actionID':'setup-confirm:claude_usage'}]
        with patch.object(c.setup,'confirm') as confirm:c.handle_callbacks();confirm.assert_not_called()

    def test_approval_popup_leaves_decisions_in_the_open_lake(self):
        for provider in ('codex','claude'):
            with self.subTest(provider=provider), patch.dict(os.environ,{
                'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout,presentSneakPeek'
            }):
                controller=Controller(legacy)
                sent=[]
                controller.client.send=sent.append
                active=session(provider=provider,phase='permission')
                active.permission_id='live-request'
                controller.sessions[active.activity_id]=active
                request=AgentPermissionRequest(active.permission_id,provider,active.id,'Bash','project','{}',time.monotonic()+10)
                message=controller.presentation.activity(active,'create',{},notify=True,permission=request)
                self.assertEqual(message['presentSneakPeek'],8)
                preview=message['surfaces']['sneakPeek']
                self.assertNotIn('actionID',json.dumps(preview))
                self.assertEqual(preview['leftSlot']['source'],'inlineData')

                def dispatch(message):
                    controller.client.read_available=lambda timeout:[message]
                    controller.handle_callbacks()

                with patch.object(controller.bridge,'permissions',return_value=[request]), \
                     patch.object(controller.bridge,'decide',return_value=True) as decide:
                    dispatch({'type':'action','surface':'sneakPeek','activityID':active.activity_id,'actionID':'deny:live-request'})
                    decide.assert_not_called()
                    dispatch({'type':'lakeOpened','activityID':active.activity_id})
                    lake=sent[-1]['lake']
                    self.assertEqual(lake['content'][1]['children'][0]['source'],'inlineData')
                    self.assertIn('Approve once',json.dumps(lake['bottom']))
                    self.assertIn('Deny',json.dumps(lake['bottom']))
                    dispatch({'type':'lakeClosed'})
                    dispatch({'type':'action','surface':'lake','activityID':'lake','actionID':'deny:live-request'})
                    decide.assert_not_called()
                    dispatch({'type':'lakeOpened','activityID':active.activity_id})
                    dispatch({'type':'action','surface':'lake','activityID':'lake','actionID':'deny:live-request'})
                    decide.assert_called_once_with(request.id,'deny')

    def test_idle_usage_stays_available_without_an_idle_activity(self):
        controller=Controller(legacy)
        sent=[]
        controller.client.send=sent.append
        quota=opencode_quota_snapshots(limits())
        active=session(provider='opencode')
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}), \
             patch('agent_runtime.settings',return_value={**controller.values,'alwaysShowUsage':True,
                                                           'hideSetupButton':True,'enableUsageTracking':True}), \
             patch.object(controller.bridge,'start'), patch.object(controller.usage,'refresh'), \
             patch.object(controller.registry,'collect',side_effect=[{}, {active.activity_id:active}, {}]), \
             patch.object(controller.usage,'snapshots',quota):
            controller.refresh_sources()
            self.assertIn('75% left',json.dumps(sent))
            self.assertNotIn('tab:setup',json.dumps(sent))
            controller.refresh_sources()
            self.assertIn('OpenCode',json.dumps(sent))
            controller.refresh_sources()
        self.assertEqual([m['activityID'] for m in sent if m['type']=='create'],[active.activity_id])
        lakes=[m['lake'] for m in sent if m['type']=='lake']
        self.assertEqual([lake['content'][0]['children'][1]['text'] for lake in lakes],['Usage','Progress','Usage'])
        idle_rows=lakes[0]['glance']['content']
        self.assertEqual([len(row['children']) for row in idle_rows],[3,4])
        tiles=[child for row in idle_rows for child in row['children'] if child['type']=='vstack']
        self.assertEqual([tile['children'][1]['text'] for tile in tiles],['Codex','Claude','OpenCode'])
        self.assertEqual([tile['children'][2]['text'] for tile in tiles],['Unavailable','Unavailable','75% left'])
        self.assertEqual([image['size'] for tile in tiles for image in tile['children'][0]['children']],[38,18]*3)
        self.assertIn('Running Tasks',json.dumps(lakes[1]['content']))
        self.assertNotIn('Running Tasks',json.dumps(lakes[1]['glance']))

    def test_native_settings_defaults(self):
        path=Path(__file__).resolve().parents[1]/'AIAgents.dynamiclakeplugin/plugin.json'
        manifest=json.loads(path.read_text())
        settings={s['id']:s for s in manifest['settings']}
        self.assertIn('enableNotifications',settings)
        for key in ('alwaysShowUsage','hideSetupButton','codexApprovals'):
            self.assertIs(settings[key]['default'],False)


if __name__=='__main__':unittest.main()
