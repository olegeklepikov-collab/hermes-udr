"""Owned loopback transport: accepted bytes survive caller loss without a second send."""

import hashlib
import json
import os
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests import test_profile_transport as fixtures

OBSERVATIONS = []
CLIENT = r"""
import hashlib,json,os,sys,urllib.request
from pathlib import Path
from hermes_foundation_bridge.profile_transport import ProfileTransportService
root,endpoint,mode=sys.argv[1:];service=ProfileTransportService(Path(root))
body=b'Controlled immutable delivery bytes';digest=hashlib.sha256(body).hexdigest();key='CONTROL-TRANSPORT';model='NO-MODEL'
if mode=='first':
 service.delivery_prepare({'schema_version':1,'idempotency_key':key,'artifact_hash':digest,'model_run_id':model,'host_visible_output':True,'accepted_artifact':True})
 # Persist the unresolved outcome before crossing the transport boundary.
 service.delivery_reconcile({'schema_version':1,'idempotency_key':key,'provider_status':'unknown','provider_accepted':False,'model_run_id':model})
 try:
  request=urllib.request.Request(endpoint+'/send',data=body,headers={'X-Artifact-SHA256':digest})
  with urllib.request.urlopen(request,timeout=5) as response:response.read()
 except OSError:pass
 os._exit(73)
with urllib.request.urlopen(endpoint+'/status',timeout=5) as response:observed=json.loads(response.read())
assert observed['artifact_hash']==digest and observed['accepted_count']==1
result=service.delivery_reconcile({'schema_version':1,'idempotency_key':key,'provider_status':'delivered','provider_accepted':True,'model_run_id':model})
assert result['status']=='delivered' and result['model_rerun'] is False
print(json.dumps({'receipt':result,'independent_provider_readback':observed,'resend_performed':False}))
"""


class LocalTransportFaultTests(unittest.TestCase):
    def test_response_loss_and_client_crash_reconcile_from_new_process_without_resend(
        self,
    ):
        for lose_response in (True, False):
            with self.subTest(lose_response=lose_response):
                fixture = fixtures.ProfileTransportTests()
                fixture.setUp()
                fixture.migrate()
                provider = Path(fixture.directory.name) / "provider.sqlite3"
                with closing(sqlite3.connect(provider)) as db, db:
                    db.execute("CREATE TABLE accepted(artifact_hash TEXT, bytes BLOB)")

                class Transport(BaseHTTPRequestHandler):
                    def log_message(self, *_args):
                        pass

                    def do_POST(self, provider=provider, lose_response=lose_response):
                        body = self.rfile.read(int(self.headers["content-length"]))
                        digest = hashlib.sha256(body).hexdigest()
                        assert digest == self.headers["X-Artifact-SHA256"]
                        with closing(sqlite3.connect(provider)) as db, db:
                            db.execute(
                                "INSERT INTO accepted VALUES(?,?)", (digest, body)
                            )
                            db.commit()
                        if lose_response:
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b'{"accepted":true}')

                    def do_GET(self, provider=provider):
                        with closing(sqlite3.connect(provider)) as db, db:
                            rows = db.execute(
                                "SELECT artifact_hash, bytes FROM accepted"
                            ).fetchall()
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(
                            json.dumps(
                                {
                                    "artifact_hash": rows[0][0],
                                    "accepted_count": len(rows),
                                }
                            ).encode()
                        )

                server = ThreadingHTTPServer(("127.0.0.1", 0), Transport)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = f"http://127.0.0.1:{server.server_port}"
                    command = [
                        sys.executable,
                        "-B",
                        "-c",
                        CLIENT,
                        str(fixture.root),
                        endpoint,
                    ]
                    env = {
                        **os.environ,
                        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                        "NO_PROXY": "127.0.0.1",
                    }
                    failed = subprocess.run(
                        [*command, "first"],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(failed.returncode, 73, failed.stderr)
                    with closing(sqlite3.connect(fixture.service.database)) as db, db:
                        before = db.execute(
                            "SELECT state,artifact_hash FROM deliveries WHERE idempotency_key='CONTROL-TRANSPORT'"
                        ).fetchone()
                    self.assertEqual(before[0], "ambiguous_delivery")
                    recovered = subprocess.run(
                        [*command, "resume"],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(recovered.returncode, 0, recovered.stderr)
                    result = json.loads(recovered.stdout)
                    with closing(sqlite3.connect(provider)) as db, db:
                        rows = db.execute(
                            "SELECT artifact_hash,bytes FROM accepted"
                        ).fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][1], b"Controlled immutable delivery bytes")
                    self.assertEqual(rows[0][0], before[1])
                    OBSERVATIONS.append(
                        {
                            "fault_class": "telegram",
                            "transport": "owned_loopback_not_Telegram",
                            "fault_point": "provider_commit_before_response"
                            if lose_response
                            else "response_before_local_ack",
                            "old_process_exit": 73,
                            "persisted_state_before_recovery": before[0],
                            "new_process": result,
                            "accepted_effects": len(rows),
                            "real_telegram_sends": 0,
                        }
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                    fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
