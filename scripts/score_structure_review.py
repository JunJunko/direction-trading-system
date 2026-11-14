import argparse
import hashlib
import json
from pathlib import Path
from structure_review_metrics import evaluate

parser = argparse.ArgumentParser()
parser.add_argument('pack', type=Path)
parser.add_argument('reviews', nargs='*', type=Path)
args = parser.parse_args()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
manifest = read(args.pack/'manifest.json')
for name, expected in manifest['file_hashes'].items():
    if hashlib.sha256((args.pack/name).read_bytes()).hexdigest() != expected:
        raise ValueError('Locked sample or prediction changed: '+name)
reviews = [read(path) for path in args.reviews]
for review in reviews:
    if review.get('pack_id') != manifest['pack_id']:
        raise ValueError('Review belongs to a different pack')
    if review.get('view_mode', 'blind') != 'blind':
        raise ValueError('Algorithm-annotated reviews are inspection notes, not independent blind labels')
result = evaluate(read(args.pack/'cases-private.json'),
                  read(args.pack/'predictions-private.json'), reviews,
                  read(args.pack/'calendar.json')['open_dates'])
(args.pack/'assessment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
