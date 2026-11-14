"""Human reference labels are independent of algorithm predictions and P&L."""
from collections import Counter
from datetime import datetime


def evaluate(cases, predictions, reviews, calendar):
    by_id = {c['id']: c for c in cases}
    days = {day: i for i, day in enumerate(calendar)}
    if len(by_id) != len(cases):
        raise ValueError('Duplicate review IDs')
    allowed = {'yes', 'no', 'unclear', ''}
    indexed = {}
    for review in reviews:
        reviewer = review.get('reviewer', '').strip()
        if not reviewer:
            raise ValueError('Reviewer name required')
        if reviewer in indexed:
            raise ValueError('Duplicate reviewer; revisions must replace earlier files')
        indexed[reviewer] = {}
        for label in review.get('labels', []):
            identity = label['id']
            if identity not in by_id or identity in indexed[reviewer]:
                raise ValueError('Unknown or duplicate label ID')
            for field in ('double_bottom', 'retest'):
                if label.get(field, '') not in allowed:
                    raise ValueError('Invalid reference label')
            date = label.get('confirmed_date', '').replace('-', '')
            if date:
                datetime.strptime(date, '%Y%m%d')
                if date not in days or date > by_id[identity]['as_of']:
                    raise ValueError('Confirmation date must be an observed trading day')
                if label.get('retest') != 'yes':
                    raise ValueError('Confirmation date requires a yes retest label')
            if label.get('double_bottom') != 'yes' and label.get('retest') == 'yes':
                raise ValueError('A double-bottom retest requires an identified double bottom')
            indexed[reviewer][identity] = dict(label, confirmed_date=date)
    primary = [c for c in cases if not c.get('repeat_of')]
    result = dict(primary_cases=len(primary), reviewers=list(indexed),
                  consensus_counts={}, models={}, repeat_consistency={})
    consensus = {}
    for field in ('double_bottom', 'retest'):
        accepted, counts = {}, Counter()
        for case in primary:
            values = [labels.get(case['id'], {}).get(field, '') for labels in indexed.values()]
            if len(values) < 2 or any(v == '' for v in values):
                counts['missing_independent_labels'] += 1
            elif any(v == 'unclear' for v in values):
                counts['unclear'] += 1
            elif len(set(values)) != 1:
                counts['disagreement'] += 1
            else:
                counts['agreed_' + values[0]] += 1
                accepted[case['id']] = values[0]
        consensus[field] = accepted
        result['consensus_counts'][field] = dict(counts)
    for model in ('legacy', 'structured'):
        metrics = {}
        for field in ('double_bottom', 'retest'):
            confusion = Counter(tp=0, fp=0, tn=0, fn=0)
            for identity, reference in consensus[field].items():
                predicted = bool(predictions[identity][model][field])
                confusion['tp' if predicted and reference == 'yes' else
                          'fp' if predicted else 'fn' if reference == 'yes' else 'tn'] += 1
            tp, fp, fn = confusion['tp'], confusion['fp'], confusion['fn']
            metrics[field] = dict(confusion, evaluated=sum(confusion.values()),
                                 precision=tp/(tp+fp) if tp+fp else None,
                                 recall=tp/(tp+fn) if tp+fn else None)
        delays = []
        for case in primary:
            identity = case['id']
            if consensus['retest'].get(identity) != 'yes':
                continue
            dates = [labels[identity].get('confirmed_date') for labels in indexed.values()]
            predicted = predictions[identity][model].get('confirmed_date')
            if all(dates) and len(set(dates)) == 1 and predicted:
                delays.append(days[predicted]-days[dates[0]])
        metrics['confirmation_delay_sessions'] = delays
        result['models'][model] = metrics
    for reviewer, labels in indexed.items():
        pairs = []
        for case in cases:
            parent = case.get('repeat_of')
            if not parent or parent not in labels or case['id'] not in labels:
                continue
            for field in ('double_bottom', 'retest'):
                a, b = labels[parent].get(field, ''), labels[case['id']].get(field, '')
                if a and b:
                    pairs.append(a == b)
        result['repeat_consistency'][reviewer] = dict(comparisons=len(pairs),
                                                    agreements=sum(pairs))
    result['status'] = ('labels_incomplete' if len(indexed) < 2 or
                        any(c.get('missing_independent_labels', 0) for c in result['consensus_counts'].values())
                        else 'reference_labels_collected')
    result['limitations'] = [
        'Human consensus is a reference, not objective ground truth.',
        'Stratified small sample; precision/recall do not estimate market-wide rates.',
        'Known research snapshot; not an untouched holdout.',
        'No return, entry execution or hourly-data validation; no automatic promotion.'
    ]
    return result
