"""실제 사건을 읽지 않고 채점·재제출·해설 접근·완료 조건을 검사한다."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from test_live import fixture, live, DOC
import caseflow as F

RUBRIC = {'criteria': [
    {'id': 'K1', 'label': '행위자와 역할', 'required': True, 'expected': 'SECRET_ACTOR', 'evidence': [{'doc': '시험', 'where': '본문', 'quote': '기록 A.'}]},
    {'id': 'K2', 'label': '사건 경위', 'required': True, 'expected': 'SECRET_CAUSE', 'evidence': [{'doc': '시험', 'where': '본문', 'quote': '기록 B.'}]},
    {'id': 'K3', 'label': '동기', 'required': False, 'expected': 'SECRET_MOTIVE', 'evidence': []}]}
SOLUTION = '\n'.join('## ' + h + '\n검사용 사건의 경위를 재구성한 충분히 긴 설명 문장입니다. [[시험]] 문서에 기록되어 있습니다.\n' for h in ('사건의 전말', '시간 순서', '단서의 의미', '남아 있던 의문'))


def judgment(mark='일치', text='제출한 추리'):
    return {'checks': [{'id': 'K1', 'status': mark, 'claim': text}, {'id': 'K2', 'status': mark, 'claim': text},
                       {'id': 'K3', 'status': '미제시', 'claim': ''}], 'contradictions': []}


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case, self.state = fixture(self.root)
        self.request = dict(id='attempt-1', text='제출한 추리', case=self.case.name)

    def freeze(self):
        folder = F.cache(self.root, self.case)
        F.save(folder / 'rubric.json', RUBRIC)
        F.atomic_write(folder / 'solution.md', SOLUTION)
        F.save(folder / 'rubric-lock.json', dict(truth=F.digest(self.case/'truth.md'), rubric=F.digest(folder/'rubric.json'), solution=F.digest(folder/'solution.md')))

    def test_secret_optional_detail_is_not_required_or_exposed(self):
        result = F.normalize_judgment(judgment(), RUBRIC, self.request, self.root)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['checks']), 2)
        self.assertNotIn('SECRET_', json.dumps(result))

    def test_every_required_condition_must_match(self):
        for status in ('일부 일치', '불일치', '미제시'):
            raw = judgment(); raw['checks'][1].update(status=status, claim='' if status == '미제시' else self.request['text'])
            with self.subTest(status=status):
                self.assertFalse(F.normalize_judgment(raw, RUBRIC, self.request, self.root)['accepted'])

    def test_grade_comes_from_the_marks_by_a_fixed_table(self):
        def g(m1, m2, conflict=False):
            raw = judgment(); raw['checks'][0].update(status=m1, claim='' if m1 == '미제시' else '제출한 추리')
            raw['checks'][1].update(status=m2, claim='' if m2 == '미제시' else '제출한 추리')
            raw['contradictions'] = ['제출한 추리'] if conflict else []
            return F.normalize_judgment(raw, RUBRIC, self.request, self.root)['result']
        self.assertEqual(g('일치', '일치'), '완전 해결')
        self.assertEqual(g('일치', '일치', True), '거의 해결')
        self.assertEqual(g('일치', '일부 일치'), '거의 해결')
        self.assertEqual(g('일부 일치', '미제시'), '절반')
        self.assertEqual(g('불일치', '미제시'), '빗나감')

    def test_ending_with_a_grade_shows_the_guess_on_the_solution(self):
        self.freeze()
        F.save(F.cache(self.root, self.case)/'attempts.json', [dict(id='a', accepted=False, result='절반', text='내 추리 글',
                                                                    checks=[dict(label='사건 경위', status='일부 일치')])])
        st = F.read(self.case/'state.json', {}); st.update(revealed=True, ended='절반'); F.save(self.case/'state.json', st)
        page = F.solution_page(self.root, self.case)
        self.assertIn('내 추리 글', page); self.assertIn('△ 사건 경위', page); self.assertIn('절반', page)

    def test_record_page_collects_guesses_without_the_answer(self):
        self.freeze()
        F.save(F.cache(self.root, self.case)/'attempts.json', [
            dict(id='old', accepted=False, result='부분 정답', checks=[dict(label='사건 경위', status='일부 일치', claim='예전 주장')]),
            dict(id='new', accepted=False, result='거의 해결', text='두 번째 추리', checks=[dict(label='사건 경위', status='일치', claim='두 번째 추리')])])
        page = F.record_page(self.root)
        self.assertIn('추리 2번', page); self.assertIn('예전 주장', page); self.assertIn('2번째 · 거의 해결', page)
        self.assertIn('1번째 · 절반', page); self.assertNotIn('SECRET_', page); self.assertNotIn('전말 보기', page)

    def test_matching_keywords_with_a_core_contradiction_do_not_pass(self):
        raw = judgment(); raw['contradictions'] = ['제출한 추리']
        self.assertFalse(F.normalize_judgment(raw, RUBRIC, self.request, self.root)['accepted'])

    def test_missing_checks_and_invented_claims_are_rejected(self):
        missing = judgment(); missing['checks'].pop()
        invented = judgment(text='독자가 적지 않은 주장')
        for raw in (missing, invented):
            with self.assertRaises(ValueError):
                F.normalize_judgment(raw, RUBRIC, self.request, self.root)

    def test_a_required_condition_needs_public_evidence(self):
        F.validate_rubric(RUBRIC, self.root, self.case)
        bad = copy.deepcopy(RUBRIC); bad['criteria'][0]['evidence'][0]['quote'] = 'SECRET_ONLY'
        with self.assertRaises(ValueError):
            F.validate_rubric(bad, self.root, self.case)

    def test_solution_is_locked_until_acceptance_and_stays_locked_if_tampered(self):
        self.freeze()
        with self.assertRaises(PermissionError):
            F.solution_page(self.root, self.case)
        F.save(F.cache(self.root,self.case)/'attempts.json', [dict(id='wrong', accepted=False)])
        with self.assertRaises(PermissionError):
            F.solution_page(self.root, self.case)
        F.save(F.cache(self.root,self.case)/'attempts.json', [dict(id='right', accepted=True)])
        page = F.solution_page(self.root,self.case)
        self.assertIn('사건의 전말',page); self.assertIn('href="/',page)
        (self.case/'truth.md').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):
            F.solution_page(self.root,self.case)

    def test_rubric_is_prepared_without_the_submission_then_reused_on_retry(self):
        calls=[]
        result_mark='불일치'
        def runner(stage, agent, prompt, timeout, log, **kwargs):
            if '제출 의견을 보지 않은 독립 준비' in prompt:
                self.assertNotIn(self.request['text'], prompt)
                F.save(stage/'plan/시험/grading.json',RUBRIC)
                F.atomic_write(stage/'plan/시험/solution.md',SOLUTION)
                calls.append('prepare')
            else:
                F.save(stage/'.live/verdict_review.json',judgment(result_mark))
                calls.append('judge')
            return True,''
        args=(self.root,self.case,self.request,runner,'codex',10,threading.Event(),lambda x:None)
        self.assertTrue(F.review(*args)[0])
        self.assertFalse(F.read(self.case/'state.json')['closed'])
        fingerprint=F.digest(F.cache(self.root,self.case)/'rubric.json')
        result_mark='일치'; self.request['id']='attempt-2'
        self.assertTrue(F.review(*args)[0])
        self.assertEqual(calls,['prepare','judge','judge'])
        self.assertEqual(F.digest(F.cache(self.root,self.case)/'rubric.json'),fingerprint)
        self.assertTrue(F.read(self.case/'state.json')['closed'])
        self.assertEqual(len(F.attempts(self.root,self.case)),2)

    def test_a_judge_cannot_change_the_story(self):
        self.freeze()
        def runner(stage,*args,**kwargs):
            F.save(stage/'.live/verdict_review.json',judgment())
            (stage/'docs/시험.md').write_text('illegal edit',encoding='utf-8')
            return True,''
        result=F.review(self.root,self.case,self.request,runner,'codex',10,threading.Event(),lambda x:None)
        self.assertFalse(result[0]); self.assertFalse(F.solved(self.root,self.case))
        self.assertEqual((self.root/'docs/시험.md').read_text(encoding='utf-8'),DOC)

    def test_declaring_finished_without_checklist_is_not_completion(self):
        state=dict(self.state,finished=True); F.save(self.case/'state.json',state)
        with patch.object(F.C,'check') as check:
            result=F.completion(self.root,self.case)
            check.assert_not_called()
        self.assertFalse(result['complete']); self.assertFalse(F.read(self.case/'state.json')['finished'])

    def test_final_check_is_run_by_server_even_if_agent_forgot_finished(self):
        F.atomic_write(self.case/'next.md','\n'.join('- [x] '+s for s in F.CHECKS[:-1])+'\n- [ ] 마감 검사 오류 0개\n')
        with patch.object(F.C,'check',return_value=([],[])):
            result=F.completion(self.root,self.case)
        self.assertTrue(result['complete']); self.assertEqual(result['checked'],len(F.CHECKS))
        self.assertTrue(F.read(self.case/'state.json')['finished'])

    def test_errors_prevent_completion_and_are_not_published_as_spoilers(self):
        F.atomic_write(self.case/'next.md','\n'.join('- [x] '+s for s in F.CHECKS))
        with patch.object(F.C,'check',return_value=(['SECRET_VALIDATION_DETAIL'],[])):
            result=F.completion(self.root,self.case)
        self.assertFalse(result['complete']); self.assertEqual(result['errors'],1)
        self.assertNotIn('SECRET',json.dumps(result))

    def test_wrong_answer_can_be_submitted_again_and_does_not_close_wiki(self):
        L=live.Live(self.root,'codex'); L.busy=True
        F.save(F.cache(self.root,self.case)/'attempts.json',[dict(id='wrong',accepted=False)])
        self.assertEqual(L.submit_verdict({'text':'다시 제출한 추리'})[1],202)
        self.assertEqual(L.submit_verdict({'text':'중복'})[1],409)

    def test_review_failure_releases_pending_request_for_retry(self):
        L=live.Live(self.root,'codex'); L.busy=True
        L.submit_verdict({'text':'첫 의견'})
        with patch.object(F,'review',return_value=(False,'검토 실행 실패')):
            L._review_turn()
        self.assertFalse(L.pending_verdict()); self.assertFalse(L.busy)
        self.assertEqual(L.progress()['label'],'작업 중단')
        L.busy=True
        self.assertEqual(L.submit_verdict({'text':'재시도'})[1],202)

    def test_only_an_accepted_answer_blocks_further_submissions(self):
        L=live.Live(self.root,'codex'); L.busy=True
        F.save(F.cache(self.root,self.case)/'attempts.json',[dict(id='right',accepted=True)])
        self.assertEqual(L.submit_verdict({'text':'또 제출'})[1],409)

    def test_progress_distinguishes_pause_work_error_complete_and_solved(self):
        L=live.Live(self.root,'codex')
        self.assertEqual(L.progress()['label'],'일시 정지')
        L.busy=True; L.kind='turn'
        self.assertEqual(L.progress()['label'],'집필 중')
        L.busy=False; L.last_error='검사 실패'
        self.assertEqual(L.progress()['label'],'작업 중단')
        L.last_error=''; L.completion['complete']=True
        self.assertIn(L.progress()['label'],('마무리 중','추리할 수 있음'))      # 글이 끝나도 '완료'라 하지 않는다. 채점 기준이 있어야 추리할 수 있음
        self.assertEqual(L.progress()['label'],'추리할 수 있음' if L.graded() else '마무리 중')
        (self.case/'images.md').write_text('| a.png | 시험 | 모습 | 사진 | 사건 전개 | 캡션 | - | 구절 |\n',encoding='utf-8')
        self.assertIn('사진 1장 남음',L.progress()['detail'])      # 이 사건에서 아직 안 그려진 사진 수
        (self.case/'img').mkdir(exist_ok=True); (self.case/'img'/'a.png').write_bytes(b'x')
        self.assertNotIn('남음',L.progress()['detail'])
        F.save(F.cache(self.root,self.case)/'attempts.json',[dict(id='right',accepted=True)])
        self.assertEqual(L.progress()['label'],'정답 인정')


class OwnErrorsTest(unittest.TestCase):
    def test_errors_of_docs_left_by_earlier_cases_do_not_block_this_case(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); (root/'docs').mkdir(); (root/'history').mkdir()
            for n in ('old','new'): (root/'plan'/n).mkdir(parents=True); (root/'plan'/n/'truth.md').write_text('x',encoding='utf-8')
            for d in ('옛 인물','새 인물'): (root/'docs'/f'{d}.md').write_text('---\ntype: 인물\n---\n',encoding='utf-8')
            (root/'history'/'revs.json').write_text(json.dumps({'옛 인물':[{'rev':'r1','time':'2000-01-01 00:00:00'}],
                '새 인물':[{'rev':'r1','time':'2099-01-01 00:00:00'}]},ensure_ascii=False),encoding='utf-8')
            errs=['오류 | 옛 인물: 시작 문서에서 링크로 갈 수 없습니다.','오류 | 옛 인물 (옛 판): x','오류 | 새 인물: 시작 문서에서 링크로 갈 수 없습니다.',
                  '오류 | 조각 old/1: x','오류 | 조각 new/1: x']
            self.assertEqual(F.own_errors(errs,root,root/'plan'/'new'),['오류 | 새 인물: 시작 문서에서 링크로 갈 수 없습니다.','오류 | 조각 new/1: x'])


class SolutionLinkTest(unittest.TestCase):
    def test_links_to_documents_that_do_not_exist_show_as_plain_text(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); case, _ = fixture(root)
            folder = F.cache(root, case); F.save(folder / 'rubric.json', RUBRIC)
            F.atomic_write(folder / 'solution.md', SOLUTION.replace('[[시험]] 문서', '[[시험]] 문서와 [[없는업체|그 업체]], [[없는곳]]'))
            F.save(folder / 'rubric-lock.json', dict(truth=F.digest(case / 'truth.md'), rubric=F.digest(folder / 'rubric.json'), solution=F.digest(folder / 'solution.md')))
            F.update_state(case, sealed=True, revealed=True)
            page = F.solution_page(root, case)
            self.assertIn('그 업체', page); self.assertIn('없는곳', page)
            self.assertNotIn('없는업체.html', page); self.assertNotIn('class="new"', page)
            self.assertIn('href="/', page)                                   # 있는 문서([[시험]])는 링크로 남는다


class StateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.case, _ = fixture(self.root, sealed=False)

    def test_parallel_writers_do_not_lose_each_others_keys(self):
        ts = [threading.Thread(target=lambda k=k: [F.update_state(self.case, **{k: i}) for i in range(30)]) for k in ('wrote1', 'wrote2', 'turn')]
        [t.start() for t in ts]; [t.join() for t in ts]
        st = F.read(self.case / 'state.json')
        self.assertEqual((st['wrote1'], st['wrote2'], st['turn']), (29, 29, 29))

    def test_impossible_states_are_refused_and_logged(self):
        for bad in (dict(finished=True), dict(solved=True), dict(revealed=True)):
            with self.assertRaises(ValueError):
                F.update_state(self.case, **bad)
        self.assertFalse(F.read(self.case / 'state.json').get('finished'))
        F.update_state(self.case, sealed=True); F.update_state(self.case, finished=True)
        kinds = [e['kind'] for e in F.events(self.case)]
        self.assertEqual(kinds.count('rejected'), 3); self.assertIn('state', kinds)
        self.assertNotIn('검사용 고정 내용', json.dumps(F.events(self.case), ensure_ascii=False))      # 일지에 진상이 들어가지 않는다


if __name__=='__main__':
    unittest.main()
