"""New Desktop schema, coexistence/migration, lifecycle and inline tool regression fixtures."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from test_v2 import legacy
from agent_providers import OpenCodeProvider


class OpenCodeDesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'opencode.db'
        self.env=patch.dict(os.environ,{'OPENCODE_DB':str(self.db)})
        self.env.start()
        self.now=int(time.time()*1000)
        self.c=sqlite3.connect(self.db)
        self.c.executescript('''
        CREATE TABLE session_v2(id TEXT PRIMARY KEY,directory TEXT,title TEXT,time_updated INTEGER,time_archived INTEGER,time_busy INTEGER,time_idle INTEGER,idle_outcome TEXT);
        CREATE TABLE session_message(id TEXT PRIMARY KEY,session_id TEXT,type TEXT,seq INTEGER,time_created INTEGER,time_updated INTEGER,data TEXT);
        CREATE TABLE session_part(message_id TEXT,session_id TEXT,ordinal INTEGER,type TEXT,call_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
        ''')

    def tearDown(self):
        self.c.close();self.env.stop();self.tmp.cleanup()

    def add_session(self,sid='s',age=0):
        self.c.execute('INSERT INTO session_v2 VALUES(?,?,?,?,NULL,?,NULL,NULL)',(sid,'/tmp/project','Fix cart total',self.now-age,self.now))
        self.c.commit()

    def message(self,kind,data,sid='s',seq=1):
        self.c.execute('INSERT INTO session_message VALUES(?,?,?,?,?,?,?)',(sid+'-'+str(seq),sid,kind,seq,self.now+seq,self.now+seq,json.dumps(data)))
        self.c.commit()

    def tool(self,name='read',status='running',file='CartStore.swift'):
        return {'type':'tool','id':'call-1','name':name,'state':{'status':status,'input':{'file_path':'/tmp/'+file},'content':[{'type':'text','text':'must not retain'}]},'time':{'created':self.now}}

    def test_new_desktop_detected_inline_tool_and_title(self):
        self.add_session()
        self.message('assistant',{'time':{'created':self.now},'content':[self.tool()]})
        provider=OpenCodeProvider(legacy);states=provider.sessions()
        self.assertIn('Desktop v2',provider.health)
        self.assertEqual(len(states),1)
        self.assertEqual(states[0].phase,'tool')
        self.assertEqual(states[0].task,'Fix cart total')
        self.assertEqual(states[0].steps[0].label,'Read CartStore.swift')
        self.assertNotIn('must not retain',str(states))

    def test_old_session_with_new_message_is_found(self):
        self.add_session(age=7200000)
        self.message('assistant',{'content':[self.tool()]})
        self.assertEqual(len(OpenCodeProvider(legacy).sessions()),1)

    def test_idle_outcomes_are_authoritative(self):
        for outcome,phase in [('succeeded','completed'),('failed','failed'),('interrupted','interrupted')]:
            sid=outcome;self.add_session(sid)
            self.message('assistant',{'content':[self.tool(status='completed')]},sid)
            self.message('idle',{'outcome':outcome,'time':{'created':self.now}},sid,2)
        states={s.id:s for s in OpenCodeProvider(legacy).sessions()}
        self.assertEqual([states[s].phase for s in ('succeeded','failed','interrupted')],['completed','failed','interrupted'])
        self.assertFalse(states['interrupted'].visible())

    def test_completed_tool_does_not_finish_turn(self):
        self.add_session()
        self.message('assistant',{'finish':'tool-calls','time':{'completed':self.now},'content':[self.tool(status='completed')]})
        state=OpenCodeProvider(legacy).sessions()[0]
        self.assertEqual(state.phase,'thinking')
        self.assertEqual(state.steps[0].status,'completed')

    def test_migrated_legacy_row_does_not_duplicate_or_replace_v2(self):
        self.add_session()
        self.message('idle',{'outcome':'interrupted'})
        self.c.executescript('''CREATE TABLE session(id TEXT,directory TEXT,title TEXT,time_updated INTEGER,time_archived INTEGER);
        CREATE TABLE message(id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
        CREATE TABLE part(id TEXT,message_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);''')
        self.c.execute('INSERT INTO session VALUES(?,?,?,?,NULL)',('s','/tmp/old','old',self.now+100))
        self.c.execute('INSERT INTO message VALUES(?,?,?,?,?)',('old','s',self.now,self.now+100,'{"role":"user"}'));self.c.commit()
        states=OpenCodeProvider(legacy).sessions()
        self.assertEqual(len(states),1)
        self.assertEqual(states[0].phase,'interrupted')

    def test_session_part_storage_and_concurrent_sessions(self):
        for sid in ('a','b'):
            self.add_session(sid)
            self.message('assistant',{'time':{'created':self.now},'content':[]},sid)
            part=self.tool();part.pop('type')
            self.c.execute('INSERT INTO session_part VALUES(?,?,?,?,?,?,?,?)',(sid+'-1',sid,0,'tool','call-1',self.now,self.now+10,json.dumps(part)))
        self.c.commit()
        states=OpenCodeProvider(legacy).sessions()
        self.assertEqual({s.id for s in states},{'a','b'})
        self.assertTrue(all(s.phase=='tool' and len(s.steps)==1 for s in states))

    def test_metadata_update_does_not_revive_idle(self):
        self.add_session()
        self.message('idle',{'outcome':'succeeded'},seq=1)
        self.message('agent_selected',{'agent':'ignored'},seq=2)
        state=OpenCodeProvider(legacy).sessions()[0]
        self.assertEqual(state.updated_at,(self.now+1)/1000)
        self.assertEqual(state.phase,'completed')

    def test_channel_database_discovery(self):
        self.add_session();self.message('idle',{'outcome':'succeeded'})
        self.c.close()
        data=Path(self.tmp.name)/'opencode';data.mkdir()
        self.db.rename(data/'opencode-next.db')
        self.c=sqlite3.connect(data/'opencode-next.db')
        with patch.dict(os.environ,{'XDG_DATA_HOME':self.tmp.name}):
            with patch.dict(os.environ,clear=False):
                os.environ.pop('OPENCODE_DB',None)
                self.assertEqual(len(OpenCodeProvider(legacy).sessions()),1)


if __name__=='__main__':unittest.main()
