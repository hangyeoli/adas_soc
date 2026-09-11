"""Generate an operation ranking from camera benchmark JSON."""
import argparse
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('benchmark', type=Path)
args = parser.parse_args()
data = json.loads(args.benchmark.read_text(encoding='utf-8'))
stats = data['stats']
total = stats['fpga_total_ms']['mean']
ops = sorted(((k,v) for k,v in stats.items() if k.startswith('op_')), key=lambda item:-item[1]['mean'])
rows = []
for rank,(name,v) in enumerate(ops,1):
    rows.append(dict(rank=rank,operation=name[3:-3],mean_ms=v['mean'],p50_ms=v['p50'],
                     p95_ms=v['p95'],p99_ms=v['p99'],percent=100*v['mean']/total))
with args.benchmark.with_name('latency-ranking.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
lines = ['# Camera 100-frame latency ranking', '',
         f"Measured frames: {data['frames']}; FPGA mean: {total:.3f} ms.", '',
         '| Rank | Operation | Mean ms | P50 ms | P95 ms | P99 ms | Share |',
         '| --- | --- | --- | --- | --- | --- | --- |']
for r in rows:
    lines.append(f"| {r['rank']} | {r['operation']} | {r['mean_ms']:.3f} | {r['p50_ms']:.3f} | {r['p95_ms']:.3f} | {r['p99_ms']:.3f} | {r['percent']:.2f}% |")
lines += ['',f"Top 3 share: {sum(r['percent'] for r in rows[:3]):.2f}%.",
          f"Top 5 share: {sum(r['percent'] for r in rows[:5]):.2f}%.", '',
          '| Stage | Mean | P50 | P95 | P99 |','| --- | --- | --- | --- | --- |']
for name,v in stats.items():
    if not name.startswith('op_'):
        columns = ['unavailable' if v[k] is None else f'{v[k]:.3f}' for k in ('mean','p50','p95','p99')]
        lines.append('| '+name+' | '+' | '.join(columns)+' |')
lines += ['',*data['notes']]
args.benchmark.with_name('latency-ranking.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines))
