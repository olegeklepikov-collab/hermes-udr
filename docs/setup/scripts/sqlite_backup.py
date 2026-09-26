"""Online SQLite backup into a new file; does not replace a live database."""
import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('source',type=Path)
p.add_argument('destination',type=Path)
a=p.parse_args()
source=a.source.resolve(strict=True);target=a.destination.absolute()
if target.exists() or target.is_symlink():raise SystemExit('Destination must be a new path')
target.parent.mkdir(parents=True,exist_ok=True)
with target.open('xb'):pass
try:
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Integrity check failed')
    print(json.dumps({'status':'backed_up','sqlite_library':sqlite3.sqlite_version,'integrity':'ok','source_modified':False}))
except BaseException:
    # Keep the partial copy for diagnosis; never overwrite or remove the source.
    raise
