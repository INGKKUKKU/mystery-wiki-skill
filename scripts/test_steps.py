"""설정 창의 단계별 모델과 생각 깊이."""
import json, tempfile, unittest
from pathlib import Path
from test_live import fixture, live


class StepsTest(unittest.TestCase):
    def test_each_step_keeps_its_own_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'w'; fixture(root)
            conf = json.loads((root / 'wiki.json').read_text(encoding='utf-8')); conf.update(quality='빠르게'); conf.pop('steps', None)
            (root / 'wiki.json').write_text(json.dumps(conf, ensure_ascii=False), encoding='utf-8')
            self.assertEqual(live.chosen(root, 'codex', False, '', 'premise')[1], 'medium')      # 처음 값: 사건 구상은 깊은 차례
            self.assertEqual(live.chosen(root, 'codex', False, '', 'body')[1], 'low')
            L = live.Live(root, 'codex')
            L.ops('steps', json.dumps({'premise': {'model': 'm1', 'effort': 'high'}, 'nope': {'effort': 'x'}, 'body': {}}))
            saved = json.loads((root / 'wiki.json').read_text(encoding='utf-8'))['steps']
            self.assertEqual(saved, {'premise': {'model': 'm1', 'effort': 'high'}})                # 모르는 단계와 빈 값은 버린다
            self.assertEqual(live.chosen(root, 'codex', True, '', 'premise')[:2], ('m1', 'high'))
            self.assertEqual(live.chosen(root, 'codex', True, '', 'critic')[1], 'medium')         # 따져 보기는 따라 바뀌지 않는다
            self.assertEqual([s['key'] for s in L.settings()['steps']][:2], ['premise', 'design'])
            L.ops('steps', '{}')
            self.assertNotIn('steps', json.loads((root / 'wiki.json').read_text(encoding='utf-8')))
            self.assertEqual(live.step_of('spine2-again'), 'body'); self.assertEqual(live.step_of('doc3'), 'around')


if __name__ == '__main__':
    unittest.main()
