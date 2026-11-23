"""엔진의 흐름 시험. 에이전트 대신 정해 둔 답을 돌려주고, 사건 하나가 끝까지 쓰이는지와 편집자에게 진상이 가지 않는지를 본다."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / 'assets' / 'tools'))
import live, fast

DOC = '불빛 사건'
ANSWERS = {
    'premise': f'''=== 사건 | 불빛
=== 문서 | {DOC} | 가 | 문서 생성
--- 새문서
---
type: 사건
category: 미제 사건
start: true
teaser: 불이 켜져 있었다.
---
::: {DOC}
발생일 | 1980년 3월 2일
장소 | 서울
유형 | 실종
상태 | 미해결
:::

## 개요
1980년 3월 2일 서울에서 구 모 씨(당시 30세)가 사라진 사건. 방에는 불이 켜져 있었다. 행방은 밝혀지지 않았다.
=== 설계 | truth.md
## 알맹이
- 무슨 일이 있었나: 비밀알맹이 한 줄.
## 답의 꼴
누구의 뜻.
## 크기
한 사람.
## 훅
불이 켜져 있었다.
## 사건 문서 이름
{DOC}
## 알려진 순간
- 3월 3일 집주인이 불 켜진 빈방을 보았다.
''',
    'side': '',
    'story1': '''=== 설계 | truth.md
## 알맹이
- 작가가 바꿔 쓴 알맹이.
## 중심 질문
왜 불이 켜져 있었나.
## 인물
- 구영수: 숨긴비밀.
## 무슨 일이 있었나
- 1980-03-02 21:00 진상의일.
## 뒤집히는 믿음
- 믿음 / 실제
=== 설계 | names.md
- 구영수 → 구 모 씨, 구 씨, 구 씨 : 세입자
=== 설계 | known.md
## 사람들
- 구영수는 세입자였다.
## 알려진 일
- 1980년 3월 2일 저녁 구 씨가 방에 들어갔다.
''',
    'spine1': f'=== 문서 | {DOC} | 다 | 경위\n--- 덧붙임 | 사건 전개\n### 그날 저녁\n1980년 3월 2일 저녁 구 씨가 방에 들어갔다.\n',
    'story2': '''=== 설계 | truth.md
## 수사는 왜 못 풀었나
| 수단 | 실제로 나온 것 | 왜 결정적이지 않았나 |
|---|---|---|
| 탐문 | 없음 | 없음 |
## 사다리
| 번호 | 놓을 곳 | 겉으로 보이는 것 | 진짜 까닭 | 종류 |
|---|---|---|---|---|
| 1 | 사건 전개 | 구 씨가 방에 들어갔다 | 숨은까닭 | 진실 |
| 2 | 수사 | 전등은 새것이었다 | 숨은까닭 | 진실 |
## 세간의 설
- 가출설
## 결론
- K1: 1·2
## 다른 문서에 놓을 것
| 문서 이름 | 종류 | 그 문서에 원래 있을 사실 | 문구 | 사건 문서의 무엇과 만나나 |
|---|---|---|---|---|
## 독자 생각의 흐름
- 흐름
## 끝까지 남길 것
- 남길것
=== 설계 | known.md
## 사람들
- 바꾸려는 줄.
## 수사
- 전등은 새것이었다.
## 세간의 설
- 가출설: 근거와 막히는 데.
## 그 뒤
- 방은 헐렸다. [[별빛방송]]이 이 일을 다뤘다.
''',
    'shots': '''| 파일 | 무엇을 담은 이미지인가 | 상태 | 캡션 | 놓을 곳 |
|---|---|---|---|---|
| door.png | 불 켜진 방문 | 보도 사진 | 불 켜진 방 | 구 씨가 방에 들어갔다 |
''',
    'critic': '판정: 고칠 것\n- 탐문이 왜 막혔는지가 없다.',
    'mend': '=== 설계 | truth.md\n<<<\n| 탐문 | 없음 | 없음 |\n>>>\n| 탐문 | 이웃은 못 봤다 | 고친까닭 |\n<<<\n- 무슨 일이 있었나: 비밀알맹이 한 줄.\n>>>\n- 바꾼 알맹이\n=== 설계 | known.md\n<<<\n- 전등은 새것이었다.\n>>>\n- 전등은 새것이었다.\n- 이웃은 소리를 듣지 못했다.\n<<<\n- 구 모 씨는 세입자였다.\n>>>\n- 잠긴 문단을 바꾸려는 줄.\n',
    'links': '', 'ledger': '=== 설계 | timeline.md\n| 시각 | 일 | 공개 |\n|---|---|---|\n| 1980-03-02 | 들어감 | 공개 |\n| 1980-03-03 | 발견 | 공개 |\n=== 설계 | facts.md\n- 없음\n',
    'spine2': f'=== 문서 | {DOC} | 다 | 수사\n--- 덧붙임 | 수사\n### 탐문\n경찰은 이웃을 탐문했다.\n',
    'spine3': f'=== 문서 | {DOC} | 다 | 마무리\n--- 덧붙임 | 의문점\n### 가출설\n가출설이 있다.\n=== 문서 | {DOC} | 다 | 마무리\n--- 덧붙임 | 이후\n### 헐린 방\n방은 헐렸다. [[별빛방송]]이 이 일을 다뤘다.\n',
    'talk': '',
    'pieces': '=== 設計 | 불빛/pieces.md\n| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 | 반박대상 | 안내 | 결론 |\n|---|---|---|---|---|---|---|---|---|---|\n'
              f'| 1 | 진실 | 끝 | 들어감 | {DOC} | 본문 | 구 씨가 방에 들어갔다 | | | K1 |\n| 9 | 비공개 | - | 남길것 | - | - | 남길것표현 | | | |\n',
    'add': f'=== 문서 | {DOC} | 라 | 보강\n--- 덧붙임 | 수사\n전등은 새것이었다.\n',
    'pieces-again': '=== 설계 | pieces.md\n| 번호 | 종류 | 단계 | 내용 | 문서 | 위치 | 문구 | 반박대상 | 안내 | 결론 |\n|---|---|---|---|---|---|---|---|---|---|\n'
                    f'| 1 | 진실 | 1 | 들어감 | {DOC} | 본문 | 구 씨가 방에 들어갔다 | | | K1 |\n| 2 | 진실 | 끝 | 전등 | {DOC} | 본문 | 전등은 새것이었다 | | | K1 |\n| 9 | 비공개 | - | 남길것 | - | - | 남길것표현 | | | |\n',
    'fix': '',
    'world': '''## 별빛방송
- 1961년에 문을 연 지역 방송이다.
''',          # 작가가 둘레 문서의 재료를 낸다(알려진 것만)
    'doc1': '''=== 문서 | 별빛방송 | 마 | 문서 생성
--- 새문서
---
type: 매체
category: 방송
---
::: 별빛방송
종류 | 방송
:::

## 개요
지역 방송이다.
''',
}
SECRET = ('비밀알맹이', '숨긴비밀', '진상의일', '숨은까닭', '구영수', '남길것')
BLIND = ('shots', 'side', 'spine1', 'spine2', 'spine3', 'talk', 'add', 'doc1')


class FlowTest(unittest.TestCase):
    def test_a_case_is_written_and_editors_never_see_the_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'w'
            subprocess.run([sys.executable, '-X', 'utf8', str(SKILL / 'scripts' / 'new_wiki.py'), str(root), '--name', '시험'], check=True, capture_output=True)
            conf = json.loads((root / 'wiki.json').read_text(encoding='utf-8')); conf['images'] = 'off'
            (root / 'wiki.json').write_text(json.dumps(conf, ensure_ascii=False), encoding='utf-8')
            L = live.Live(root, 'codex'); L.fill_images = lambda: None
            seen = {}

            def fake(L, prompt, deep=False, timeout=0, tag='', need='==='):
                seen[tag] = seen.get(tag, '') + prompt
                return ANSWERS.get(tag) or None
            real = fast.ask, fast.used_files, sys.modules['__main__']
            fast.ask, fast.used_files, sys.modules['__main__'] = fake, (lambda L: [root / 'plan' / 'used.md']), live
            try:
                ok, why = fast.run(L, '')
            finally:
                fast.ask, fast.used_files, sys.modules['__main__'] = real
            plan = root / 'plan' / '불빛'; truth = (plan / 'truth.md').read_text(encoding='utf-8'); known = (plan / 'known.md').read_text(encoding='utf-8')
            doc = (root / 'docs' / f'{DOC}.md').read_text(encoding='utf-8')
            self.assertIn('비밀알맹이', truth); self.assertNotIn('바꿔 쓴 알맹이', truth)            # 알맹이는 얼개에서 정한 그대로
            self.assertIn('구 모 씨는 세입자였다', known); self.assertNotIn('구영수', known)              # 실명은 알려진 것에서 가려진다
            self.assertNotIn('바꾸려는 줄', known); self.assertIn('전등은 새것이었다', known)          # 이미 쓰인 문단은 뒤에서 못 바꾼다
            for tag in BLIND:                                                                        # 편집자들이 받은 글에는 진상이 없다
                for word in SECRET:
                    self.assertNotIn(word, seen.get(tag, ''), f'{tag} 에 진상({word})이 갔다')
            self.assertIn('고친까닭', truth); self.assertNotIn('바꾼 알맹이', truth)                    # 고쳐 짓기는 줄 단위로 바꾸고, 알맹이는 못 바꾼다
            self.assertIn('이웃은 소리를 듣지 못했다', known); self.assertNotIn('잠긴 문단을 바꾸려는 줄', known)
            revs = json.loads((root / 'history' / 'revs.json').read_text(encoding='utf-8'))[DOC]
            self.assertGreaterEqual(len(revs), 5, [r['summary'] for r in revs])                    # 쉬지 않아도 편집마다 판이 하나씩 남는다
            self.assertIn('숨은까닭', seen['pieces']); self.assertIn('비밀알맹이', seen['critic'])     # 기록 담당과 따지는 쪽은 진상을 본다
            self.assertIn('전등은 새것이었다', doc)                                                  # 빠진 단서는 편집자가 채웠다
            for h in ('## 사건 전개', '## 수사', '## 의문점', '## 이후'):
                self.assertIn(h, doc)
            self.assertTrue((root / 'docs' / '별빛방송.md').is_file())                                # 링크가 걸린 둘레 문서는 본문 옆에서 같이 쓰인다
            shots = (plan / 'images.md').read_text(encoding='utf-8')                               # 사진 담당은 쓰인 문단을 읽고 고른다
            self.assertIn('door.png | ' + DOC, shots); self.assertIn('| 구 씨가 방에 들어갔다 |', shots)
            pic = doc.index('door.png)')
            self.assertLess(doc.index('구 씨가 방에 들어갔다'), pic); self.assertLess(pic, doc.index('## 수사'))     # 고른 구절 바로 아래에 놓인다
            st = json.loads((plan / 'state.json').read_text(encoding='utf-8'))
            self.assertTrue(st['sealed'] and st['finished'], (ok, why, st))


def write_case(tmp, answers):
    """가짜 답으로 사건 하나를 끝까지 돌린다. -> (성공, 이유, 사건 설계 폴더)"""
    root = Path(tmp) / 'w'
    subprocess.run([sys.executable, '-X', 'utf8', str(SKILL / 'scripts' / 'new_wiki.py'), str(root), '--name', '시험'], check=True, capture_output=True)
    conf = json.loads((root / 'wiki.json').read_text(encoding='utf-8')); conf['images'] = 'off'
    (root / 'wiki.json').write_text(json.dumps(conf, ensure_ascii=False), encoding='utf-8')
    L = live.Live(root, 'codex'); L.fill_images = lambda: None
    real = fast.ask, fast.used_files, sys.modules['__main__']
    fast.ask = lambda L, prompt, deep=False, timeout=0, tag='', need='===': answers.get(tag) or None
    fast.used_files, sys.modules['__main__'] = (lambda L: [root / 'plan' / 'used.md']), live
    try:
        ok, why = fast.run(L, '')
    finally:
        fast.ask, fast.used_files, sys.modules['__main__'] = real
    return ok, why, root / 'plan' / '불빛'


class FailureTest(unittest.TestCase):
    """실패한 일은 끝난 일로 적히지 않는다."""
    def test_critic_failure_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, why, plan = write_case(tmp, {k: v for k, v in ANSWERS.items() if k != 'critic'})
            st = json.loads((plan / 'state.json').read_text(encoding='utf-8'))
            self.assertFalse(ok); self.assertIn('따져 보지 못해', why)
            self.assertFalse(st.get('sealed')); self.assertFalse(st.get('finished'))

    def test_leftover_check_errors_do_not_finish_the_case(self):
        broken = dict(ANSWERS, spine3=ANSWERS['spine3'].replace(' [[별빛방송]]이 이 일을 다뤘다.', ''))      # 둘레 문서로 가는 길이 없다
        with tempfile.TemporaryDirectory() as tmp:
            ok, why, plan = write_case(tmp, broken)
            st = json.loads((plan / 'state.json').read_text(encoding='utf-8'))
            self.assertFalse(ok); self.assertIn('마감 검사 오류', why); self.assertFalse(st.get('finished'))
            self.assertIn('- [ ] 마감 검사', (plan / 'next.md').read_text(encoding='utf-8'))


class PremiseInTwoTest(unittest.TestCase):
    def test_candidates_come_first_without_the_ledger_then_get_picked_against_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'plan').mkdir()
            (L.root / 'plan' / 'used.md').write_text('* 옛 사건: 무엇. [빈 관이 나왔다] (1970년 어느 읍) | 알고 보니: 장부에만 있는 줄.\n', encoding='utf-8')
            seen = {}
            def fake(L, prompt, deep=False, timeout=0, tag='', need='==='):
                seen[tag] = prompt
                return '\n'.join(f'후보: 후보{i}' for i in range(5)) if tag == 'premise-cands' else '=== 사건 | 가'
            with patch.object(fast, 'ask', fake), patch.object(fast, 'used_files', lambda L: [L.root / 'plan' / 'used.md']):
                self.assertEqual(fast.premise_in_two(L, '김, 이'), '=== 사건 | 가')
            self.assertNotIn('장부에만 있는 줄', seen['premise-cands'])       # 후보는 장부 없이 떠올린다
            self.assertIn('1970년 어느 읍', seen['premise-cands'])         # 다만 이미 쓴 때와 곳은 본다
            self.assertNotIn('빈 관이 나왔다', seen['premise-cands']); self.assertIn('훅: 빈 관이 나왔다', seen['premise'])     # 훅은 고를 때만 본다
            self.assertIn('후보: 후보4', seen['premise']); self.assertIn('장부에만 있는 줄', seen['premise'])
            with patch.object(fast, 'ask', fake), patch.object(fast, 'used_files', lambda L: [L.root / 'plan' / 'used.md']):
                fast.premise_in_two(L, '김', '광주의 오래된 일')
            self.assertIn('광주의 오래된 일', seen['premise-cands']); self.assertIn('광주의 오래된 일', seen['premise'])     # 주문이 있어도 나누고, 두 호출 모두 주문을 본다
            with patch.object(fast, 'ask', lambda *a, **k: None):
                self.assertEqual(fast.premise_in_two(L, '김'), '')            # 후보를 못 받으면 부른 쪽이 한 번에 하는 길로 간다


class ScrubTest(unittest.TestCase):
    def test_a_real_name_in_a_later_clue_doc_and_its_piece_is_masked(self):
        with tempfile.TemporaryDirectory() as tmp:           # 단서를 둔 구술자료에 실명이 들어가 마감 검사에서 멈췄다
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'plan' / 'c' / 'names.md').write_text('- 김용찬 → 김 씨, 김 씨 : 아들\n', encoding='utf-8')
            (L.root / 'docs' / '구술자료.md').write_text('김용찬의 사망일은 5월 22일이다.', encoding='utf-8')
            (L.root / 'plan' / 'c' / 'pieces.md').write_text('| 1 | 진실 | 1 | 사망일 | 구술자료 | 본문 | 김용찬의 사망일은 5월 22일이다. | | | K1 |\n', encoding='utf-8')
            fast.scrub_docs(L, 'c')
            for p in (L.root / 'docs' / '구술자료.md', L.root / 'plan' / 'c' / 'pieces.md'):
                t = p.read_text(encoding='utf-8'); self.assertNotIn('김용찬', t); self.assertIn('김 씨의 사망일', t)


class NamesUsedTest(unittest.TestCase):
    def test_names_of_other_cases_are_listed_but_not_this_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp)
            for c, body in (('가', '- 남태수 → 남 씨 : 사장\n- 중앙여관 : 여관\n'), ('나', '- 백정임 : 이 사건 사람\n')):
                (L.root / 'plan' / c).mkdir(parents=True); (L.root / 'plan' / c / 'names.md').write_text(body, encoding='utf-8')
            got = fast.names_used(L, '나')
            self.assertIn('남태수', got); self.assertIn('중앙여관', got); self.assertNotIn('백정임', got)
            self.assertEqual(fast.names_used(L, '없는') .count('백정임'), 1)


class ShortLedgerTest(unittest.TestCase):
    def test_premise_sees_only_the_twist_and_the_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            class L: pass
            L.root = Path(tmp); (L.root / 'plan').mkdir()
            (L.root / 'plan' / 'used.md').write_text('* 시험 사건: 무엇을 모르나. [처음 본 장면] (1970년 3월, 어느 읍.) | 알고 보니: 이웃이 우체통을 옮긴 일.\n', encoding='utf-8')
            with patch.object(fast, 'used_files', lambda L: [L.root / 'plan' / 'used.md']):
                self.assertEqual(fast.used(L, short=True), '* 시험 사건: 이웃이 우체통을 옮긴 일. (1970년 3월, 어느 읍.)')
                self.assertIn('[처음 본 장면]', fast.used(L))


class RateLimitTest(unittest.TestCase):
    def test_a_429_is_waited_out_and_called_again(self):
        with tempfile.TemporaryDirectory() as tmp:          # 바로 다시 부르면 또 거절돼 조각 표가 통째로 빠졌다
            class L: agent = 'codex'
            L.root = Path(tmp); L.dir = Path(tmp) / '.live'; L.dir.mkdir()
            replies = [(1, b'', b'ERROR: exceeded retry limit, last status: 429 Too Many Requests', None), (0, b'=== ok', b'', None)]
            main = type('M', (), dict(chosen=staticmethod(lambda *a: ('', '', '')), step_of=staticmethod(lambda t: t)))
            with patch.dict(sys.modules, {'__main__': main}), patch.object(fast.A, 'find', lambda a: 'codex'), \
                 patch.object(fast.A, 'spawn', lambda *a: replies.pop(0)), patch.object(fast.time, 'sleep') as slept, \
                 patch.object(fast, 'stopped', lambda: False):
                self.assertEqual(fast.ask(L, '질문'), '=== ok')
            slept.assert_called_once_with(30)


class ScreenTest(unittest.TestCase):
    def test_design_sees_the_infobox_already_on_screen(self):
        with tempfile.TemporaryDirectory() as tmp:          # 첫 화면이 안 붙어 정보 상자의 숫자와 본문의 숫자가 한 문서에서 갈렸다
            class L: pass
            L.root = Path(tmp); (L.root / 'docs').mkdir(); (L.root / 'plan' / 'c').mkdir(parents=True)
            (L.root / 'plan' / 'c' / 'truth.md').write_text('## 사건 문서 이름\n가 사건\n', encoding='utf-8')
            (L.root / 'docs' / '가 사건.md').write_text('---\ntype: 사건\n---\n:::정보\n사망 | 1,234명\n:::\n\n## 개요\n그런 사건.\n\n## 사건 전개\n본문\n', encoding='utf-8')
            s = fast.screen(L, 'c')
            self.assertIn('1,234명', s); self.assertIn('그런 사건.', s); self.assertNotIn('본문', s)


if __name__ == '__main__':
    unittest.main()
