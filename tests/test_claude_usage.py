"""Official Claude statusLine stdin quota, private IPC and explicit setup fixtures."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from test_v2 import PACKAGE, legacy, session
from agent_bridge import HookBridge, normalize_event
from agent_models import claude_quota_snapshots, AgentUsageSnapshot, AgentPermissionRequest
from agent_presentation import Presentation
from integrations import update_config


def payload():
    return {'session_id':'fixture','rate_limits':{'five_hour':{'used_percentage':64,'resets_at':time.time()+3600},'seven_day':{'used_percentage':12,'resets_at':time.time()+86400}},
            'context_window':{'used_percentage':99},'prompt':'private prompt','cost':{'total_cost_usd':12345}}


class ClaudeUsageTests(unittest.TestCase):
    def test_real_quota_not_context_percentage(self):
        values=claude_quota_snapshots(payload())
        self.assertEqual([v.remaining_percent for v in values],[36,88])
        self.assertEqual([v.provider for v in values],['claude','claude'])
        self.assertIn('statusLine',values[0].source)
        normalized=normalize_event({'provider':'claude','event':'Usage','data':payload()})
        self.assertNotIn('private',str(normalized));self.assertNotIn('12345',str(normalized))

    def test_missing_and_invalid_quota_is_not_zero(self):
        self.assertEqual(claude_quota_snapshots({'context_window':{'used_percentage':99}}),[])
        self.assertEqual(claude_quota_snapshots({'rate_limits':{'five_hour':{'used_percentage':True}}}),[])
        self.assertEqual(claude_quota_snapshots({'rate_limits':None}),[])

    def test_collector_subprocess_does_not_create_fake_session(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ,{'AI_AGENTS_BRIDGE_DIR':d}):
                bridge=HookBridge(usage_enabled=lambda:True);bridge.start()
                try:
                    result=subprocess.run([sys.executable,str(PACKAGE/'agent_hook.py'),'claude','Usage'],input=json.dumps(payload()),text=True,capture_output=True,timeout=3,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                    self.assertEqual(result.returncode,0)
                    self.assertIn('36% 5-hour left',result.stdout)
                    self.assertEqual(result.stderr,'')
                    self.assertEqual(bridge.drain(),[])
                    self.assertEqual(len(bridge.usage),2)
                finally:bridge.close()

    def test_disabled_usage_does_not_collect(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ,{'AI_AGENTS_BRIDGE_DIR':d}):
                bridge=HookBridge();bridge.start()
                try:
                    with socket.socket(socket.AF_UNIX) as c:
                        c.settimeout(2);c.connect(str(bridge.path))
                        c.sendall(json.dumps({'provider':'claude','event':'Usage','data':payload()}).encode()+b'\n')
                        self.assertEqual(json.loads(c.recv(2048)),{})
                    bridge.drain();self.assertEqual(bridge.usage,[])
                finally:bridge.close()

    def test_usage_installer_preserves_existing_status_line(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';original={'statusLine':{'type':'command','command':'my-existing-display'},'theme':'keep'}
            p.write_text(json.dumps(original));before=p.read_bytes()
            with self.assertRaises(ValueError):update_config(p,'claude',True,usage=True)
            self.assertEqual(p.read_bytes(),before)
            self.assertFalse(list(p.parent.glob('*backup*')))

    def test_usage_install_idempotent_and_reversible(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';original={'theme':'keep'};p.write_text(json.dumps(original))
            self.assertTrue(update_config(p,'claude',True,usage=True))
            self.assertFalse(update_config(p,'claude',True,usage=True))
            self.assertTrue(update_config(p,'claude',False,usage=True))
            self.assertEqual(json.loads(p.read_text()),original)

    def test_expired_window_stays_unknown_until_new_data(self):
        p=Presentation(legacy)
        expired=AgentUsageSnapshot('claude','5-hour',64,resets_at=time.time()-1,updated_at=time.time())
        self.assertIsNone(p.quota_choice('claude',[expired]))

    def test_permission_review_survives_session_selection_refresh(self):
        p=Presentation(legacy);s=session(provider='claude');p.page='permission';p.permission_id='request'
        request=AgentPermissionRequest('request','claude',s.id,'Bash','project','{"command":"swift build"}',time.monotonic()+90)
        p.choose([s])
        with patch.dict(os.environ,{'DYNAMICLAKE_PLUGIN_FEATURES':'lake,lakeLayout'}):m=p.lake([s],[request],[],{},{})
        buttons=m['lake']['bottom'][0]['children']
        self.assertEqual([b['actionID'] for b in buttons],['deny:request','allow:request'])

    def test_disabling_hooks_releases_permission_when_usage_stays_enabled(self):
        from agent_runtime import Controller
        import threading
        c=Controller(legacy)
        event=threading.Event()
        request=AgentPermissionRequest('pending','claude','s','Bash','project','{}',time.monotonic()+90,event)
        c.bridge.pending['pending']=request
        c.bridge.start=lambda:None
        c.client.send=lambda message:None
        c.registry.collect=lambda values:{}
        c.usage.refresh=lambda enabled:None
        with patch.object(legacy,'plugin_settings',return_value={'enableUsageTracking':True,'enableHooks':False,'interactiveApprovals':True}):
            c.refresh_sources()
        self.assertTrue(event.is_set())
        self.assertEqual(c.bridge.permissions(),[])


if __name__=='__main__':unittest.main()
