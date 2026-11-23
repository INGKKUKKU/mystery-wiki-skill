"""같은 곳을 다르게 부른 링크는 문서를 하나 더 열지 않고 있는 문서로 건다."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'assets' / 'tools'))
import fast


class PlacesTest(unittest.TestCase):
    def test_short_and_long_names_share_one_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'docs' / '충청남도 예산군 덕산면.md').write_text('면 문서', encoding='utf-8')
            (L.root / 'docs' / '사건.md').write_text('[[덕산면]]의 진입로와 [[덕산면|그 면]], 그리고 [[삽교읍]]', encoding='utf-8')
            self.assertEqual(fast.unwritten(L, 'c'), ['삽교읍'])                      # 덕산면은 새로 열지 않는다
            body = (L.root / 'docs' / '사건.md').read_text(encoding='utf-8')
            self.assertIn('[[충청남도 예산군 덕산면|덕산면]]의 진입로', body); self.assertIn('[[충청남도 예산군 덕산면|그 면]]', body)


class ParenNameTest(unittest.TestCase):
    def test_a_bare_name_links_to_the_doc_named_with_a_parenthesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'docs' / '중동(공주).md').write_text('동 문서', encoding='utf-8')
            (L.root / 'docs' / '사건.md').write_text('[[중동]]의 양복점', encoding='utf-8')
            self.assertEqual(fast.unwritten(L, 'c'), [])
            self.assertIn('[[중동(공주)|중동]]의 양복점', (L.root / 'docs' / '사건.md').read_text(encoding='utf-8'))


class AlignTest(unittest.TestCase):
    def test_a_table_fact_retold_as_a_sentence_is_anchored_to_real_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'docs' / '사건.md').write_text('## 수사\n사진에서 금액을 읽을 수 있는 두 표에는 같은 도장이 있었다.\n\n| 참가금 | 지급액 |\n|---|---|\n| 1만 원 | 187만 원 |\n', encoding='utf-8')
            head = '| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 | 반박대상 | 안내 | 결론 |\n|---|---|---|---|---|---|---|---|---|---|\n'
            (L.root / 'plan' / 'c' / 'pieces.md').write_text(head + '| 1 | 진실 | 1 | 금액 | 사건 | 본문 | 사진에서 읽을 수 있는 두 표의 참가금은 1만 원이었다. | | | K1 |\n', encoding='utf-8')
            self.assertEqual(fast.align_pieces(L, 'c'), 1)
            quote = (L.root / 'plan' / 'c' / 'pieces.md').read_text(encoding='utf-8').splitlines()[2].split('|')[7].strip()
            self.assertIn(quote, (L.root / 'docs' / '사건.md').read_text(encoding='utf-8')); self.assertGreaterEqual(len(quote), 6)

    def test_a_quote_unlike_the_document_is_anchored_by_the_row_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'docs' / '사건.md').write_text('## 수사\n그날 비가 왔다. 민 씨의 수입 수첩 여백에는 오후 논의 아래에 서울행과 여섯 명의 동행을 뜻하는 메모가 있었다. 공장은 닫혀 있었다.\n', encoding='utf-8')
            head = '| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 | 반박대상 | 안내 | 결론 |\n|---|---|---|---|---|---|---|---|---|---|\n'
            (L.root / 'plan' / 'c' / 'pieces.md').write_text(head + '| 1 | 진실 | 1 | 민 씨의 수첩에는 논의 아래 배웅 관련 메모가 있었다. | 사건 | 본문 | 기택 서울, 여섯 같이 | | | K1 |\n', encoding='utf-8')
            self.assertEqual(fast.align_pieces(L, 'c'), 1)
            quote = (L.root / 'plan' / 'c' / 'pieces.md').read_text(encoding='utf-8').splitlines()[2].split('|')[7].strip()
            self.assertTrue(quote.startswith('민 씨의 수입 수첩'), quote)


class NickTest(unittest.TestCase):
    def test_digit_only_variants_become_the_existing_regular(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'history').mkdir()
            (L.root / 'history' / 'revs.json').write_text('{"가": [{"rev": "r1", "editor": "june_84"}]}', encoding='utf-8')
            (L.root / 'docs' / '가.md').write_text('---토론---\n## 주제\n**모과차** (2026-11-22 01:00): 글\n', encoding='utf-8')
            self.assertEqual(fast.regular(L, 'june_82'), 'june_84')
            self.assertEqual(fast.regular(L, 'JUNE85'), 'june_84')
            self.assertEqual(fast.regular(L, '모과차77'), '모과차')
            self.assertEqual(fast.regular(L, 'pado808'), 'pado808')          # 새 사람은 그대로, 그리고 기억된다
            self.assertEqual(fast.regular(L, 'pado_83'), 'pado808')
            self.assertEqual(fast.regular(L, 'ab12'), 'ab12')                # 뿌리가 너무 짧으면 합치지 않는다

    def test_talk_lines_and_editor_field_are_merged_when_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan').mkdir(); (L.root / 'history').mkdir()
            (L.root / 'history' / 'revs.json').write_text('{"가": [{"rev": "r1", "editor": "hyeon_82"}]}', encoding='utf-8')
            (L.root / 'docs' / '가.md').write_text('---\ntype: 기타\n---\n## 개요\n내용\n', encoding='utf-8')
            fast.apply(L, '=== 문서 | 가 | hyeon_92 | 토론\n--- 토론\n## 주제\n**hyeon_83** (2026-11-22 02:00): 의견\n', None)
            t = (L.root / 'docs' / '가.md').read_text(encoding='utf-8')
            self.assertIn('**hyeon_82** (2026-11-22 02:00)', t); self.assertIn('edit: hyeon_82', t)


class MetaFixTest(unittest.TestCase):
    def test_a_fix_can_add_a_line_to_the_front_matter(self):
        with tempfile.TemporaryDirectory() as tmp:          # 검사가 search: true 를 요구했는데 고침이 본문만 봐서 사건이 멈췄다
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan').mkdir()
            (L.root / 'docs' / '가.md').write_text('---\ntype: 인물\ncategory: 희생자\n---\n## 개요\n내용\n', encoding='utf-8')
            fast.apply(L, '=== 문서 | 가 | ed | 검색 설정\n--- 고침\n<<<\ntype: 인물\n>>>\ntype: 인물\nsearch: true\n', None)
            meta = fast.split_doc((L.root / 'docs' / '가.md').read_text(encoding='utf-8'))[0]
            self.assertIn('search: true', meta); self.assertIn('category: 희생자', meta)


class SharedDocTest(unittest.TestCase):
    """여러 사건이 함께 쓰는 문서: 문단을 다시 쓸 수 있되 다른 사건으로 가는 길은 끊지 않고, 거의 같은 제목으로 문단을 또 열지 않는다."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        class L: pass
        L.root = Path(self.tmp.name); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
        (L.root / 'docs' / '가.md').write_text('---\ntype: 인물\n---\n## 개요\n남아공 출신 기업인.\n\n## 귀환 뒤 생활\n[[앞 사건]]에서 돌아왔다.\n', encoding='utf-8')
        self.L = L

    def doc(self):
        return (self.L.root / 'docs' / '가.md').read_text(encoding='utf-8')

    def test_an_overview_can_be_rewritten_in_a_shared_doc(self):
        fast.apply(self.L, '=== 문서 | 가 | ed | 개요\n--- 문단 | 개요\n기업인이자 다섯 전우 가운데 한 사람.\n', 'c', safe=True)
        self.assertIn('다섯 전우 가운데 한 사람', self.doc()); self.assertNotIn('남아공 출신 기업인.', self.doc())

    def test_a_rewrite_that_drops_another_cases_link_is_only_appended(self):
        fast.apply(self.L, '=== 문서 | 가 | ed | 정리\n--- 문단 | 귀환 뒤 생활\n안동에서 살았다.\n', 'c', safe=True)
        self.assertIn('[[앞 사건]]', self.doc()); self.assertIn('안동에서 살았다.', self.doc())

    def test_a_nearly_same_heading_goes_into_the_existing_section(self):
        fast.apply(self.L, '=== 문서 | 가 | ed | 덧붙임\n--- 덧붙임 | 귀환 이후의 생활\n[[새 사건]]에도 나왔다.\n', 'c', safe=True)
        self.assertNotIn('## 귀환 이후의 생활', self.doc()); self.assertEqual(self.doc().count('## 귀환 뒤 생활'), 1)
        self.assertIn('[[새 사건]]에도 나왔다.', self.doc())


if __name__ == '__main__':
    unittest.main()
