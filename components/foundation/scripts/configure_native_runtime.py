"""Create an explicit native runtime binding; never installs services or echoes secrets."""
from __future__ import annotations
import argparse,getpass,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hermes_foundation_bridge.platform_io import private_directory,private_file
from hermes_foundation_bridge.native_runtime import load_native_runtime,assert_private_file

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--foundation-root',type=Path,required=True)
 p.add_argument('--node',type=Path,required=True)
 p.add_argument('--graph-python',type=Path,required=True)
 p.add_argument('--agentmemory-url',default='http://127.0.0.1:3111')
 p.add_argument('--neo4j-uri',default='bolt://127.0.0.1:7687')
 p.add_argument('--neo4j-user',default='neo4j')
 p.add_argument('--neo4j-password-file',type=Path,required=True)
 a=p.parse_args()
 for path in (a.foundation_root,a.neo4j_password_file):
  if not path.is_absolute() or path.is_symlink():p.error('Absolute, non-symlink paths are required')
 for path in (a.node,a.graph_python):
  if not path.is_absolute() or not path.is_file():p.error('Executable paths must be absolute existing files')
 target=a.foundation_root/'native-runtime.json'
 if target.exists():p.error('native-runtime.json exists; review it rather than overwrite')
 a.foundation_root.mkdir(parents=True,exist_ok=True,mode=0o700);private_directory(a.foundation_root)
 if not a.neo4j_password_file.exists():
  value=getpass.getpass('Neo4j password (not echoed): ')
  if not value or len(value)>1024:p.error('Empty or oversized password')
  a.neo4j_password_file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  private_directory(a.neo4j_password_file.parent)
  fd=os.open(a.neo4j_password_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  try:
   private_file(fd);os.write(fd,(value+'\n').encode());os.fsync(fd)
  finally:os.close(fd)
 assert_private_file(a.neo4j_password_file)
 config={'schema_version':1,'mode':'native','node_path':str(a.node),'python_path':str(a.graph_python),'agentmemory_url':a.agentmemory_url,'neo4j_uri':a.neo4j_uri,'neo4j_user':a.neo4j_user,'neo4j_password_file':str(a.neo4j_password_file)}
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  private_file(fd);os.write(fd,(json.dumps(config,indent=2)+'\n').encode());os.fsync(fd)
 finally:os.close(fd)
 load_native_runtime(a.foundation_root)
 print(json.dumps({'status':'configured','mode':'native','secrets_printed':False,'services_started':False}))
 return 0
if __name__=='__main__':raise SystemExit(main())
