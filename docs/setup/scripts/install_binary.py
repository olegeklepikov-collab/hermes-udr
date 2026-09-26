"""Install one verified CLI binary from a locked archive without overwriting."""
import argparse,hashlib,json,tarfile,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('binary');p.add_argument('directory',type=Path);a=p.parse_args()
lock=json.loads((Path(__file__).resolve().parents[1]/'reference/native-tools.lock.json').read_text(encoding="utf-8"))
expected=lock['assets'][a.archive.name]['sha256']
assert hashlib.sha256(a.archive.read_bytes()).hexdigest()==expected,'Archive hash mismatch'
if Path(a.binary).name!=a.binary:raise SystemExit('Binary basename required')
if a.archive.suffix=='.zip':
 with zipfile.ZipFile(a.archive) as z:
  names=[n for n in z.namelist() if Path(n).name==a.binary and not n.endswith('/')]
  if len(names)!=1:raise SystemExit('Expected exactly one binary')
  payload=z.read(names[0])
else:
 with tarfile.open(a.archive) as t:
  members=[m for m in t.getmembers() if m.isfile() and Path(m.name).name==a.binary]
  if len(members)!=1:raise SystemExit('Expected exactly one binary')
  payload=t.extractfile(members[0]).read()
a.directory.mkdir(parents=True,exist_ok=True);target=a.directory/a.binary
if target.exists():
 if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(payload).digest():raise SystemExit('Different existing binary; not overwritten')
else:
 with target.open('xb') as out:out.write(payload)
 target.chmod(0o755)
print(str(target.resolve()))
