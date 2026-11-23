"""단서 검사: 꼴(끝 조각, 링크 거리, 미끼마다 반박, 문서당 개수)은 강제하지 않고,
새는 것, 문구가 실제로 있는지, 시작 문서에서 닿는지는 계속 본다."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'assets' / 'tools'))
import check as C

HEAD = '| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 | 반박대상 | 안내 | 결론 |\n|---|---|---|---|---|---|---|---|---|---|\n'


def wiki(root, rows, extra_docs=()):
    case = root / 'plan' / 'c'; case.mkdir(parents=True); (root / 'docs').mkdir()
    (root / 'plan' / 'truth.md').write_text('# 세계\n', encoding='utf-8')
    (case / 'truth.md').write_text('## 훅\n등불\n## 수사는 왜 못 풀었나\n| 수단 | 나온 것 | 왜 |\n|---|---|---|\n', encoding='utf-8')
    for f in ('timeline.md', 'names.md'):
        (case / f).write_text('', encoding='utf-8')
    (case / 'pieces.md').write_text(HEAD + ''.join(rows), encoding='utf-8')
    (root / 'docs' / '대문.md').write_text('---\nstart: true\n---\n[[사건]]\n', encoding='utf-8')
    (root / 'docs' / '사건.md').write_text('## 개요\n관리사 앞에서 물품을 넘겼다. 일지에는 이상 없음이 적혔다.\n', encoding='utf-8')
    for name, body in extra_docs:
        (root / 'docs' / f'{name}.md').write_text(body, encoding='utf-8')
    return C.check(root)


def about(msgs, *words):
    return [m for m in msgs if any(w in m for w in words)]


class ClueTest(unittest.TestCase):
    def run_wiki(self, rows, extra=()):
        with tempfile.TemporaryDirectory() as d:
            return wiki(Path(d), rows, extra)

    def test_no_fixed_puzzle_shape_is_required(self):
        # 진실 조각 하나가 사건 문서 첫 화면에 있고, 반박 없는 미끼, 끝 조각 없음, 비공개 없음
        err, warn = self.run_wiki(['| 1 | 진실 | 1 | 물품 | 사건 | 본문 | 관리사 앞에서 물품을 넘겼다 | | | K1 |\n',
                                   '| 2 | 미끼 | 2 | 일지 | 사건 | 본문 | 일지에는 이상 없음이 적혔다 | | | |\n'])
        shape = about(err + warn, '반박하는 조각', '"끝"인 조각', '링크', '비공개 조각이 없습니다', '진실 조각이', '독자 생각의 흐름', '끝까지 남길 것')
        self.assertEqual([m for m in shape if '조각' in m or 'truth.md' in m], [])

    def test_leaks_missing_phrases_and_unreachable_clues_still_fail(self):
        err, _ = self.run_wiki(['| 1 | 진실 | 1 | 물품 | 사건 | 본문 | 관리사 앞에서 물품을 넘겼다 | | | K1 |\n',
                                '| 2 | 진실 | 2 | 없는 말 | 사건 | 본문 | 문서에 없는 문구입니다 | | | K1 |\n',
                                '| 3 | 비공개 | - | 숨길 것 | - | - | 이상 없음 | | | |\n',
                                '| 4 | 진실 | 3 | 외딴 곳 | 외딴 | 본문 | 아무도 못 오는 곳 | | | K1 |\n'],
                               [('외딴', '## 개요\n아무도 못 오는 곳\n')])
        self.assertTrue(about(err, '조각 c/2', '없습니다'))                 # 문구가 실제로 있어야 한다
        self.assertTrue(about(err, '조각 c/3: 비공개인데'))                   # 봉인한 것이 새면 안 된다
        self.assertTrue(about(err, '외딴: 시작 문서에서 링크로 갈 수 없습니다'))  # 단서는 탐색으로 닿아야 한다

    def test_a_case_without_any_true_clue_fails(self):
        err, _ = self.run_wiki(['| 1 | 미끼 | 1 | 일지 | 사건 | 본문 | 일지에는 이상 없음이 적혔다 | | | |\n'])
        self.assertTrue(about(err, '진실 조각이 없습니다'))


class SameNameAgeTest(unittest.TestCase):
    def test_a_short_name_inside_a_longer_name_is_not_that_person(self):
        with tempfile.TemporaryDirectory() as tmp:          # 지훈 ⊂ 박지훈: 박지훈의 나이가 다른 사람 지훈의 것으로 잡혀 사건이 마감에서 멈췄다
            root = Path(tmp)
            wiki(root, [], extra_docs=[('지훈', '---\ntype: 인물\n---\n| 출생 | 1994년 |\n')])
            case = root / 'plan' / 'c'
            (case / 'truth.md').write_text('## 사건 문서 이름\n사건\n## 때와 곳\n2030년 서울\n', encoding='utf-8')
            (case / 'names.md').write_text('- 박지훈 : 정치인\n- 지훈 : 가수\n', encoding='utf-8')
            (root / 'docs' / '사건.md').write_text('## 개요\n대통령 박지훈(당시 69세)과 [[지훈]](당시 36세)이 만났다.\n', encoding='utf-8')
            self.assertEqual(about(C.check(root)[0], '나이가 다른 문서와'), [])
            (case / 'names.md').write_text('- 박지훈 : 정치인\n- 박지훈(축구 선수) : 공격수\n', encoding='utf-8')      # 동명이인: 맨이름 나이는 누구 것인지 모른다
            (root / 'docs' / '박지훈.md').write_text('---\ntype: 인물\n---\n| 출생 | 1961년 |\n', encoding='utf-8')
            (root / 'docs' / '사건.md').write_text('## 개요\n대통령 박지훈(당시 69세)과 공격수 박지훈(당시 31세)이 만났다.\n', encoding='utf-8')
            self.assertEqual(about(C.check(root)[0], '나이가 다른 문서와'), [])


class DateTest(unittest.TestCase):
    def test_a_yearless_date_takes_the_year_said_earlier_in_the_paragraph(self):
        dates = C.moments('2019년 2월 12일 발매했다. 하루 앞선 2월 11일 공개됐다.\n3월 5일에는 따로 열렸다.')[0]
        self.assertIn((2019, 2, 11), dates)
        self.assertIn((None, 3, 5), dates)          # 다른 문단은 이어받지 않는다
        self.assertFalse(C.date_ok((2019, 2, 11), {(1997, 2, 11)}))

    def test_a_placeholder_day_for_an_unknown_date_is_not_a_date(self):
        self.assertTrue(C.unknown_day({'시각': '1968-01-01', '일': '1968년, 딸이 태어났다. 월일 미상'}))
        self.assertFalse(C.unknown_day({'시각': '1968-01-01', '일': '시가 출범했다.'}))


if __name__ == '__main__':
    unittest.main()
