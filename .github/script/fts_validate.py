"""Use the repository's real mysqltest runner and unchanged official benchmark."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path.cwd()
LABEL = sys.argv[1]
OUT = Path(os.environ['RUNNER_TEMP']) / 'fts-results' / LABEL
OUT.mkdir(parents=True, exist_ok=True)
SPEC = importlib.util.spec_from_file_location('official_mysqltest', ROOT / '.github/script/seekdb/mysqltest_for_seekdb.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
SUITE = ROOT / 'tools/deploy/mysql_test/test_suite/fts_index'
CASES = [RUNNER.MysqltestCase('fts_index.' + p.stem, p, SUITE / 'r/mysql' / (p.stem + '.result'))
         for p in sorted((SUITE / 't').glob('*.test'))]
assert len(CASES) == 15 and all(c.result_file.exists() for c in CASES)
# Only select the FTS suite; leave statement execution and exact comparison to
# the official runner and its real mysqltest executable.
RUNNER.discover_cases = lambda repo_root: CASES
CLIENT = ROOT / 'deps/3rd/u01/obclient'
os.environ['LD_LIBRARY_PATH'] = ':'.join(str(CLIENT / p) for p in ('lib', 'lib64')) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
args = SimpleNamespace(
    seekdb=str(ROOT / 'build_release/src/observer/seekdb'),
    obclient=str(CLIENT / 'bin/obclient'), mysqltest=str(CLIENT / 'bin/mysqltest'),
    base_dir=str(OUT / 'regression-instance'), work_dir=str(OUT / 'regressions'),
    host='127.0.0.1', port=2881, slice_index=0, slice_count=1,
)
regression_code = RUNNER.command_run(args)

def execute(command, **kwargs):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)

sdb = ROOT / '.github/script/seekdb/sdb.py'
instance = OUT / 'benchmark-instance'
benchmark_code = 0
try:
    execute([sys.executable, sdb, 'start', '--binary', args.seekdb, '--base-dir', instance])
    execute([sys.executable, sdb, 'wait-ready', '--base-dir', instance, '--client', 'mysql'])
    env = os.environ.copy()
    env.update(MYSQL='mysql -h127.0.0.1 -P2881 -uroot -N -s -A --default-character-set=utf8mb4',
               MYSQL_VERBOSE='mysql -h127.0.0.1 -P2881 -uroot -A --default-character-set=utf8mb4',
               LABEL=LABEL, ROWS='20000', BATCH='500', ROUNDS='3000', QUERY_ROUNDS='200',
               SAMPLES='3', WARMUP='30', SKIP_LOAD='0', OUTPUT=str(OUT / 'report.txt'))
    assert not (OUT / 'report.txt').exists()
    execute(['bash', 'tools/benchmark/fts_large_bench.sh'], env=env)
    with (OUT / 'score.json').open('w') as output:
        execute([sys.executable, 'tools/benchmark/fts_large_bench_score.py', OUT / 'report.txt', '--json'], stdout=output)
    print((OUT / 'report.txt').read_text(), flush=True)
    print((OUT / 'score.json').read_text(), flush=True)
except Exception as error:
    benchmark_code = 1
    (OUT / 'benchmark-error.txt').write_text(str(error))
    print('Benchmark failed:', error, flush=True)
finally:
    subprocess.run([sys.executable, str(sdb), 'stop', '--base-dir', str(instance)], check=False)
summary = {'label': LABEL, 'regression_exit_code': regression_code, 'benchmark_exit_code': benchmark_code}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
raise SystemExit(bool(regression_code or benchmark_code))
