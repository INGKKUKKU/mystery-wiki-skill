"""공유 문서 시험: 세상이 바뀐 사실은 고쳐 쓸 수 있고, 다른 사건의 단서 문장을 지우는 편집은 반영되지 않는다."""
import sys, tempfile, unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / 'assets' / 'tools'))
import fast

DOC = '---\ntype: 인물\n---\n국적 | 포르투갈\n\n그는 붉은 우산을 들고 다녔다.\n'
PIECES = '| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 |\n| 1 | 진실 | 다른 문서 | 우산 | 사람 | 본문 | 붉은 우산 |\n'


class SharedDocTest(unittest.TestCase):
    def test_other_cases_clue_survives_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'docs').mkdir(); (root / 'plan' / 'A').mkdir(parents=True); (root / 'plan' / 'B').mkdir()
            (root / 'docs' / '사람.md').write_text(DOC, encoding='utf-8')
            (root / 'plan' / 'A' / 'pieces.md').write_text(PIECES, encoding='utf-8')

            class L:
                pass
            L.root = root
            fast.tick = lambda L: None
            fast.apply(L, '=== 문서 | 사람 | 가 | 국적\n--- 고침\n<<<\n국적 | 포르투갈\n>>>\n국적 | 대한민국\n', 'B')
            self.assertIn('국적 | 대한민국', (root / 'docs' / '사람.md').read_text(encoding='utf-8'))
            fast.apply(L, '=== 문서 | 사람 | 가 | 지움\n--- 고침\n<<<\n그는 붉은 우산을 들고 다녔다.\n>>>\n그는 걸었다.\n', 'B')
            self.assertIn('붉은 우산', (root / 'docs' / '사람.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
