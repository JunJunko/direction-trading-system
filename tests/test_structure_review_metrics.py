import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from structure_review_metrics import evaluate


class ReferenceReviewTests(unittest.TestCase):
    def fixture(self):
        cases = [dict(id='R1', as_of='20240105'), dict(id='R2', as_of='20240105'),
                 dict(id='R3', as_of='20240105', repeat_of='R1')]
        predictions = {c['id']: {m: dict(double_bottom=True, retest=True, confirmed_date='20240104')
                                  for m in ('legacy', 'structured')} for c in cases}
        calendar = ['20240102', '20240103', '20240104', '20240105']
        return cases, predictions, calendar

    def review(self, name, labels):
        return dict(reviewer=name, labels=[dict(id=i, double_bottom='yes', retest=v, confirmed_date='')
                                           for i, v in labels])

    def test_unlabelled_samples_are_not_treated_as_negative_or_passed(self):
        c, p, d = self.fixture()
        result = evaluate(c, p, [], d)
        self.assertEqual(result['status'], 'labels_incomplete')
        self.assertEqual(result['models']['structured']['retest']['evaluated'], 0)
        self.assertIsNone(result['models']['structured']['retest']['precision'])

    def test_disagreement_is_not_resolved_using_algorithm_prediction(self):
        c, p, d = self.fixture()
        result = evaluate(c, p, [self.review('A', [('R1', 'yes')]),
                                self.review('B', [('R1', 'no')])], d)
        self.assertEqual(result['consensus_counts']['retest']['disagreement'], 1)
        self.assertEqual(result['models']['structured']['retest']['evaluated'], 0)

    def test_repeats_do_not_inflate_confusion_matrix(self):
        c, p, d = self.fixture()
        reviews = [self.review(name, [('R1', 'no'), ('R2', 'yes'), ('R3', 'no')]) for name in ('A', 'B')]
        result = evaluate(c, p, reviews, d)
        self.assertEqual(result['models']['structured']['retest']['fp'], 1)
        self.assertEqual(result['models']['structured']['retest']['tp'], 1)
        self.assertEqual(result['repeat_consistency']['A']['agreements'], 2)

    def test_future_reference_date_is_rejected(self):
        c, p, d = self.fixture()
        review = self.review('A', [('R1', 'yes')])
        review['labels'][0]['confirmed_date'] = '20240108'
        with self.assertRaises(ValueError): evaluate(c, p, [review], d)

    def test_confirmation_delay_uses_trading_sessions(self):
        c, p, d = self.fixture()
        reviews = [self.review(name, [('R1', 'yes')]) for name in ('A', 'B')]
        for r in reviews: r['labels'][0]['confirmed_date'] = '20240103'
        result = evaluate(c, p, reviews, d)
        self.assertEqual(result['models']['structured']['confirmation_delay_sessions'], [1])

    def test_inconsistent_w_and_retest_labels_are_rejected(self):
        c, p, d = self.fixture()
        r = self.review('A', [('R1', 'yes')]); r['labels'][0]['double_bottom'] = 'unclear'
        with self.assertRaises(ValueError): evaluate(c, p, [r], d)


if __name__ == '__main__': unittest.main()
