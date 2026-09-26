"""Real process boundaries for Graphiti transport and isolated Dolt SQL commits."""

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.provision_dolt_sql import provision
from tests.common import native_runtime_fixture

OBSERVATIONS = []
GRAPH_CLIENT = r"""
import hashlib,json,sys
from pathlib import Path
from hermes_foundation_bridge.graphiti_adapter import GraphitiAdapter
root=Path(sys.argv[1]);operation=sys.argv[2];a=GraphitiAdapter(root)
artifact=sys.argv[3] if len(sys.argv)>3 else 'A';fact=sys.argv[4] if len(sys.argv)>4 else 'F'
try:
 if operation=='init':result=a.migrate({'schema_version':1,'apply':True})
 elif operation=='tombstone':result=a.tombstone_request({'schema_version':1,'artifact_id':artifact})
 else:result=a.put_fact({'schema_version':1,'project_id':'P','fact_id':fact,'text':'controlled fact','text_hash':hashlib.sha256(b'controlled fact').hexdigest(),'source_ref':'originals/control','artifact_id':artifact})
except Exception as error:result={'status':'error','code':getattr(error,'code',type(error).__name__)}
print(json.dumps(result))
"""
GRAPH_PROVIDER = r"""
import json,os,sqlite3,sys,time
from pathlib import Path
root=Path(os.environ['STAGE4_GRAPH_PROVIDER']);request=json.load(sys.stdin);op=request['operation'];p=request['payload']
if op=='health':out={'status':'healthy','graphiti_version':'0.30.2','neo4j_version':'5.26.31'}
elif op=='migrate':out={'status':'applied'}
else:
 with sqlite3.connect(root/'provider.sqlite3') as db:
  if op=='put_fact':
   db.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?)',(p['fact_id'],json.dumps(p),1))
   out={'status':'written','rows':[{'fact_id':p['fact_id'],'text_hash':p['text_hash'],'active':True}]}
  elif op=='tombstone':
   changed=db.execute("UPDATE facts SET active=0 WHERE active=1 AND json_extract(payload,'$.artifact_id')=?",(p['artifact_id'],)).rowcount
   out={'status':'propagated','deactivated_count':changed}
  else:raise AssertionError(op)
  db.execute('INSERT INTO effects VALUES(?)',(op,));db.commit()
 if (root/'mode').read_text()=='lose_after_commit':os._exit(71)
 if (root/'mode').read_text()=='hold-'+p['artifact_id']:
  (root/'entered').write_text(op);time.sleep(1.5)
print(json.dumps(out))
"""
DOLT_CLIENT = r"""
import json,os,sys
from pathlib import Path
from hermes_foundation_bridge.canonical import sha256_json
from hermes_foundation_bridge.dolt_sql import AUTHORITY_MANIFEST,DoltSQLAdapter
root,port,mode,label=sys.argv[1:];AUTHORITY_MANIFEST['port']=int(port)
a=DoltSQLAdapter(Path(root));original=a._connect
class Cursor:
 def __init__(self,c):self.c=c
 def __enter__(self):self.c.__enter__();return self
 def __exit__(self,*args):return self.c.__exit__(*args)
 def __getattr__(self,n):return getattr(self.c,n)
 def execute(self,sql,*args):
  if mode=='kill' and label=='before_commit' and sql.startswith('CALL DOLT_COMMIT'):os._exit(73)
  result=self.c.execute(sql,*args)
  if mode=='kill' and label=='after_commit' and sql.startswith('CALL DOLT_COMMIT'):os._exit(73)
  return result
class Connection:
 def __init__(self,c):self.c=c
 def __getattr__(self,n):return getattr(self.c,n)
 def cursor(self):return Cursor(self.c.cursor())
a._connect=lambda database:Connection(original(database))
body={'value':1};key='OBJECT-'+label;op='OP-'+label
result=a.put({'schema_version':1,'database':'kw_core','project_id':'PROCESS-FAULT','object_id':key,'expected_revision':0,'content_hash':sha256_json(body),'schema_id':'CONTROL','object':body,'operation_id':op,'run_id':'CONTROL-RUN'})
read=a.get({'schema_version':1,'database':'kw_core','project_id':'PROCESS-FAULT','object_id':key})
with original('kw_core') as connection,connection.cursor() as c:
 c.execute('SELECT COUNT(*) AS n FROM dolt_log WHERE message=%s',(f'op:{op} run:CONTROL-RUN object:{key} rev:1',));commits=c.fetchone()['n']
print(json.dumps({'write':result,'read':read,'matching_commit_count':commits}))
"""


class StageFourProcessFaultTests(unittest.TestCase):
    @staticmethod
    def graph_provider_shim(binaries: Path) -> Path:
        if os.name == "nt":
            provider = binaries / "graph_provider.py"
            provider.write_text(GRAPH_PROVIDER, encoding="utf-8")
            shim = binaries / "graph-python.cmd"
            shim.write_text(
                f'@echo off\r\n"{sys.executable}" -B "{provider}"\r\n',
                encoding="utf-8",
            )
        else:
            shim = binaries / "graph-python"
            shim.write_text("#!/usr/bin/env python3\n" + GRAPH_PROVIDER, encoding="utf-8")
            shim.chmod(0o700)
        return shim

    def test_put_tombstone_races_are_bounded_and_independent_artifacts_progress(self):
        for first_action in ("put", "tombstone"):
            with (
                self.subTest(first_action=first_action),
                tempfile.TemporaryDirectory() as temp,
            ):
                base = Path(temp)
                root = base / "foundation"
                (base / "mode").write_text("normal")
                with sqlite3.connect(base / "provider.sqlite3") as db:
                    db.execute(
                        "CREATE TABLE facts(id TEXT PRIMARY KEY,payload TEXT,active INTEGER)"
                    )
                    db.execute("CREATE TABLE effects(operation TEXT)")
                binaries = base / "bin"
                binaries.mkdir()
                shim = self.graph_provider_shim(binaries)
                native_runtime_fixture(root, python_path=str(shim))
                env = {
                    **os.environ,
                    "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                    "STAGE4_GRAPH_PROVIDER": str(base),
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                }
                command = [sys.executable, "-B", "-c", GRAPH_CLIENT, str(root)]

                def call(action, artifact="A", fact="F", command=command, env=env):
                    process = subprocess.run(
                        [*command, action, artifact, fact],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(process.returncode, 0, process.stderr)
                    return json.loads(process.stdout)

                self.assertEqual(call("init")["status"], "applied")
                if first_action == "tombstone":
                    self.assertEqual(call("put")["status"], "written")
                (base / "mode").write_text("hold-A")
                first = subprocess.Popen(
                    [*command, first_action, "A", "F"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    deadline = time.monotonic() + 5
                    while (
                        not (base / "entered").exists() and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    self.assertTrue((base / "entered").exists())
                    started = time.monotonic()
                    # Unrelated artifact B must progress while artifact A's provider is paused.
                    independent = call("put", "B", "F-B")
                    self.assertEqual(independent["status"], "written")
                    self.assertLess(time.monotonic() - started, 1)
                    competing = call(
                        "tombstone" if first_action == "put" else "put", "A", "NEW-F"
                    )
                    self.assertEqual(competing["code"], "graphiti_artifact_busy")
                    stdout, stderr = first.communicate(timeout=10)
                    self.assertEqual(first.returncode, 0, stderr)
                    self.assertIn(
                        json.loads(stdout)["status"], {"written", "propagated"}
                    )
                finally:
                    if first.poll() is None:
                        first.terminate()
                        first.communicate(timeout=10)
                (base / "mode").write_text("normal")
                if first_action == "put":
                    self.assertEqual(call("tombstone")["status"], "propagated")
                else:
                    self.assertEqual(
                        call("put", "A", "NEW-F")["code"],
                        "graphiti_artifact_tombstoned",
                    )
                with sqlite3.connect(base / "provider.sqlite3") as db:
                    facts = dict(db.execute("SELECT id,active FROM facts").fetchall())
                self.assertEqual(facts, {"F": 0, "F-B": 1})
                OBSERVATIONS.append(
                    {
                        "fault_class": "graphiti",
                        "fault_point": first_action + "_concurrent_artifact_lifecycle",
                        "bounded_competitor": competing,
                        "independent_artifact_status": independent["status"],
                        "final_active_flags": facts,
                    }
                )

    def test_graph_put_and_tombstone_reply_loss_preserve_unknown_without_replay(self):
        for operation in ("put", "tombstone"):
            with (
                self.subTest(operation=operation),
                tempfile.TemporaryDirectory() as temp,
            ):
                base = Path(temp)
                root = base / "foundation"
                (base / "mode").write_text("normal")
                with sqlite3.connect(base / "provider.sqlite3") as db:
                    db.execute(
                        "CREATE TABLE facts(id TEXT PRIMARY KEY,payload TEXT,active INTEGER)"
                    )
                    db.execute("CREATE TABLE effects(operation TEXT)")
                binaries = base / "bin"
                binaries.mkdir()
                shim = self.graph_provider_shim(binaries)
                native_runtime_fixture(root, python_path=str(shim))
                env = {
                    **os.environ,
                    "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                    "STAGE4_GRAPH_PROVIDER": str(base),
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                }

                def run(action, root=root, env=env):
                    p = subprocess.run(
                        [sys.executable, "-B", "-c", GRAPH_CLIENT, str(root), action],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(p.returncode, 0, p.stderr)
                    return json.loads(p.stdout)

                self.assertEqual(run("init")["status"], "applied")
                if operation == "tombstone":
                    self.assertEqual(run("put")["status"], "written")
                (base / "mode").write_text("lose_after_commit")
                first = run(operation)
                self.assertEqual(first["status"], "unknown_outcome")
                (base / "mode").write_text("normal")
                second = run(operation)
                self.assertEqual(second["status"], "unknown_outcome")
                self.assertFalse(second["external_call_attempted"])
                with sqlite3.connect(base / "provider.sqlite3") as db:
                    effects = db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
                    rows = db.execute("SELECT active FROM facts").fetchall()
                self.assertEqual(effects, 1 if operation == "put" else 2)
                self.assertEqual(rows, [(1 if operation == "put" else 0,)])
                OBSERVATIONS.append(
                    {
                        "fault_class": "graphiti",
                        "fault_point": operation
                        + "_after_provider_commit_before_response",
                        "first": first,
                        "new_process_repeat": second,
                        "provider_effect_count": effects,
                        "fact_count": len(rows),
                        "active": rows[0][0],
                        "provider": "owned_SQLite_process_stub_not_live_Neo4j",
                    }
                )

    @unittest.skipUnless(
        shutil.which("dolt") and importlib.util.find_spec("pymysql")
        and importlib.util.find_spec("psutil"),
        "Dolt, PyMySQL, and psutil are required",
    )
    def test_real_dolt_sql_process_crash_before_and_after_commit(self):
        from tests import test_dolt_sql as dolt_fixtures

        fixture = dolt_fixtures.DoltSQLAdapterTests()
        fixture.setUp()
        try:
            provision(fixture.root, fixture.admin_secrets, apply=True)
            fixture.start_server()
            env = {
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            }
            for point in ("before_commit", "after_commit"):
                command = [
                    sys.executable,
                    "-B",
                    "-c",
                    DOLT_CLIENT,
                    str(fixture.root),
                    str(fixture.port),
                ]
                killed = subprocess.run(
                    [*command, "kill", point],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(killed.returncode, 73, killed.stderr)
                recovered = subprocess.run(
                    [*command, "replay", point],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                result = json.loads(recovered.stdout)
                self.assertEqual(
                    result["write"]["status"],
                    "committed" if point == "before_commit" else "stale_revision",
                )
                self.assertEqual(result["read"]["object"], {"value": 1})
                self.assertEqual(result["matching_commit_count"], 1)
                OBSERVATIONS.append(
                    {
                        "fault_class": "dolt",
                        "fault_point": point,
                        "killed_exit_code": 73,
                        "new_process": result,
                        "real_isolated_sql_server": True,
                    }
                )
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
