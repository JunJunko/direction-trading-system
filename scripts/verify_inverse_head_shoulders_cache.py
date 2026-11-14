"""Compare complete real-market event tapes before and after cache optimization."""
import gzip
import hashlib
import json
import sys
from pathlib import Path


def main(before, after):
    before, after = Path(before), Path(after)
    matched, incomplete, events = [], [], 0
    for old in sorted((before / 'signal-events').glob('*.jsonl.gz')):
        if old.stat().st_size == 0:
            incomplete.append(old.name)
            continue
        try:
            with gzip.open(old, 'rt', encoding='utf-8') as f:
                expected = [json.loads(line) for line in f]
        except (EOFError, OSError, json.JSONDecodeError):
            incomplete.append(old.name)
            continue
        with gzip.open(after / 'signal-events' / old.name, 'rt', encoding='utf-8') as f:
            actual = [json.loads(line) for line in f]
        assert actual == expected, old.name
        matched.append(old.name.removesuffix('.jsonl.gz'))
        events += len(expected)
    assert len(matched) >= 300
    relative = 'source/src/trading_system/strategies/inverse_head_shoulders.py'
    result = dict(status='passed', comparison='all warmup and evaluation events, every field, complete tapes only',
        original_run=str(before.resolve()), cached_run=str(after.resolve()), matched_stocks=len(matched),
        matched_events=events, incomplete_original_tapes=len(incomplete), symbols=matched,
        original_strategy_sha256=hashlib.sha256((before / relative).read_bytes()).hexdigest(),
        cached_strategy_sha256=hashlib.sha256((after / relative).read_bytes()).hexdigest())
    (after / 'cache-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='symbols'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
