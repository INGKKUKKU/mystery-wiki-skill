"""가짜 사건 파일과 가짜 에이전트로 병렬 병합·접수 경합을 검사한다. 실제 위키는 읽지 않는다."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'assets/tools'))
import live
import fast

DOC = '---\ntype: 사건\nedit: 시험 | 시작\n---\n::: 시험\n상태 | 미제\n:::\n## 개요\n공개된 사실.\n\n## 수사\n기록 A.\n\n## 의문점\n기록 B.\n'


def fixture(root, sealed=True):
    case = root / 'plan' / '시험'
    case.mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / '.live').mkdir()
    (root / 'tools/guide').mkdir(parents=True)
    (root / 'wiki.json').write_text('{"name":"시험","quality":"빠르게","images":"off","stock":false}', encoding='utf-8')
    state = dict(turn=4 if sealed else 1, phase='파기' if sealed else '겉', sealed=sealed)
    (case / 'state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    (case / 'truth.md').write_text('검사용 고정 내용\n', encoding='utf-8')
    (root / 'plan/truth.md').write_text('# 검사 세계\n', encoding='utf-8')
    (root / 'docs/시험.md').write_text(DOC, encoding='utf-8')
    for guide in ('grading.md', 'verdict.md'):
        shutil.copy(SKILL / 'references' / guide, root / 'tools/guide' / guide)
    (root / 'tools/check.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
    return case, state


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture(self.root)
        self.live = live.Live(self.root, 'codex')
        self.live.busy = True

    def test_free_text_can_queue_while_writing_and_cannot_duplicate(self):
        text = '이런 일이 있었을 것 같습니다. 판단 근거도 함께 적습니다.'
        self.assertEqual(self.live.submit_verdict({'text': text})[1], 202)
        self.assertTrue(self.live.pending_verdict())
        request = json.loads((self.root / '.live/verdict_in.json').read_text(encoding='utf-8'))
        self.assertEqual(request['text'], text)
        self.assertEqual(self.live.submit_verdict({'text': '중복'})[1], 409)

    def test_two_simultaneous_submissions_accept_only_one(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.live.submit_verdict({'text': '의견'})[1], range(2)))
        self.assertEqual(sorted(results), [202, 409])

    def test_empty_and_unsealed_submissions_are_rejected(self):
        self.assertEqual(self.live.submit_verdict({'text': ' '})[1], 400)
        c = self.live.case(); st = json.loads((c / 'state.json').read_text(encoding='utf-8'))      # 봉인은 그 사건의 기록에서 읽는다
        st['sealed'] = False; (c / 'state.json').write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.live.submit_verdict({'text': '의견'})[1], 409)

    def test_verdict_goes_to_the_case_being_viewed(self):
        """다른 사건을 쓰는 중에도 보고 있는 사건 문서의 사건에 추리를 낸다."""
        old = self.live.case()
        other = self.root / 'plan' / '다른'; other.mkdir(); (other / 'state.json').write_text('{"sealed": false}', encoding='utf-8')
        (self.root / '.live' / 'current.txt').write_text('다른', encoding='utf-8'); self.live.current = '다른'
        with patch.object(self.live, 'case_of_page', return_value=old):
            self.assertEqual(self.live.submit_verdict({'text': '의견', 'page': '시험.html'})[1], 202)
            request = json.loads((self.root / '.live/verdict_in.json').read_text(encoding='utf-8'))
            self.assertEqual(request['case'], old.name)
            self.assertTrue(self.live.pending_any())
            self.assertEqual(self.live.view_state('시험.html')['case'], old.name)
            self.assertFalse(self.live.view_state('시험.html')['current'])

    def test_pending_verdict_runs_before_another_writing_turn(self):
        self.live.submit_verdict({'text': '의견'})
        with patch.object(fast, 'run', return_value=(True, '')), patch.object(self.live, 'fill_images'), patch.object(self.live, 'turn') as dispatch:
            self.live._run_turn('turn')
            dispatch.assert_called_once_with('verdict')

    def test_writer_exception_does_not_strand_an_accepted_verdict(self):
        self.live.submit_verdict({'text': '의견'})
        with patch.object(self.live, '_run_turn', side_effect=ValueError('test')), patch.object(self.live, 'turn') as dispatch:
            self.live._turn('turn')
            dispatch.assert_called_once_with('verdict')
        self.assertFalse(self.live.busy)


class NewCaseStateTest(unittest.TestCase):
    def test_new_order_resets_completion_but_continuation_keeps_it(self):
        for order in ('', None):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture(root)
                server = live.Live(root, 'codex')
                previous = dict(complete=True, checked=12, total=12, errors=0)
                server.completion = previous.copy()
                server.order = order

                observed = []

                def writer(current, request):
                    observed.append((request, current.completion.copy()))
                    return False, '시험용 중단'

                with patch.object(fast, 'run', side_effect=writer), patch.object(server, 'fill_images'), patch.object(server, 'prepare_grading'):
                    server._run_turn('turn')
                expected = live.F.completion(root, None) if order is not None else previous
                self.assertEqual(observed, [(order, expected)])


class OrderQueueTest(unittest.TestCase):
    """쓰는 중에 받은 새 사건은 줄에 서고, 앞 사건을 다 쓰면 맨 앞부터 하나씩 열린다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); fixture(self.root)
        self.live = live.Live(self.root, 'codex')

    def put(self, *texts):
        self.live.queue_save([dict(id=str(i), text=t) for i, t in enumerate(texts)])

    def test_busy_keeps_the_queue_and_idle_opens_the_head(self):
        self.put('첫째', '둘째')
        self.live.busy = True
        self.assertFalse(self.live.next_order())
        self.assertEqual(len(self.live.queue()), 2)
        self.live.busy = False
        with patch.object(self.live, 'turn', return_value=True) as dispatch:
            self.assertTrue(self.live.next_order())
            dispatch.assert_called_once_with()
        self.assertEqual(self.live.order, '첫째')
        self.assertEqual([o['text'] for o in self.live.queue()], ['둘째'])

    def test_finished_case_opens_next_but_failure_or_pause_does_not(self):
        for ok, stop, expect in ((True, False, True), (False, False, False), (True, True, False)):
            with self.subTest(ok=ok, stop=stop):
                self.put('다음'); self.live.order = None
                live.STOP.set() if stop else live.STOP.clear()
                with patch.object(fast, 'run', return_value=(ok, '')), patch.object(self.live, 'fill_images'), patch.object(self.live, 'prepare_grading'),                         patch.object(live.F, 'completion', return_value=dict(complete=True)), patch.object(self.live, 'next_order') as nxt:
                    self.live._run_turn('turn')
                self.assertEqual(nxt.called, expect)
        live.STOP.clear()

    def test_an_order_that_failed_to_open_goes_before_the_queue(self):
        self.put('줄에 선 것'); self.live.order = '실패해 남은 것'
        with patch.object(self.live, 'turn', return_value=True):
            self.live.next_order()
        self.assertEqual(self.live.order, '실패해 남은 것')
        self.assertEqual(len(self.live.queue()), 1)


class ArtOnceTest(unittest.TestCase):
    def test_art_being_drawn_is_not_drawn_again_by_the_photo_filler(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); case, _ = fixture(root)
            (case / 'solution-art.md').write_text('그림: 시험\n', encoding='utf-8')
            server = live.Live(root, 'codex')
            self.assertEqual(server.missing_images(), 1)
            server.drawing.add(case.name)
            self.assertEqual(server.missing_images(), 0)
            with patch.object(live, 'run_agent') as agent:
                server.draw_art(case.name)            # 이미 그리는 중이면 또 부르지 않는다
                agent.assert_not_called()

    def test_a_redrawn_photo_is_published_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); case, _ = fixture(root)
            (case / 'images.md').write_text('| 파일 | 문서 | 무엇 | 상태 |\n|---|---|---|---|\n| p.png | 시험 | 탁자 | 사진 |\n', encoding='utf-8')
            (case / 'img').mkdir(); raw = case / 'img' / 'p.png'
            server = live.Live(root, 'codex')
            with patch.object(live, 'shrink', lambda p: None), patch.object(live.F, 'hidden', lambda c, row: False):
                raw.write_bytes(b'first'); os.utime(raw, (1000, 1000))
                server.publish_images()
                self.assertEqual((root / 'docs' / 'img' / 'p.png').read_bytes(), b'first')
                self.assertEqual(server.publish_images(), 0)          # 바뀌지 않았으면 다시 내보내지 않는다
                raw.write_bytes(b'second')                           # 그린 쪽이 고쳐 그렸다
                server.publish_images()
                self.assertEqual((root / 'docs' / 'img' / 'p.png').read_bytes(), b'second')

    def test_refused_art_is_not_asked_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); case, _ = fixture(root)
            (case / 'solution-art.md').write_text('그림: 시험\n', encoding='utf-8')
            (root / 'wiki.json').write_text('{"name":"시험","images":"auto"}', encoding='utf-8')
            server = live.Live(root, 'codex')
            class Now:                                  # 스레드 대신 바로 돈다
                def __init__(self, target, daemon): self.target = target
                def start(self): self.target()
            with patch.object(live, 'run_agent') as agent, patch.object(live.threading, 'Thread', Now):
                server.draw_art(case.name); server.draw_art(case.name)      # 두 번 그려도 그림이 안 생겼다
                self.assertTrue((case / 'img' / 'solution.png.refused').is_file())
                server.draw_art(case.name)
                self.assertEqual(agent.call_count, 2)
            self.assertEqual(server.missing_images(), 0)


class IsolationTest(unittest.TestCase):
    def test_user_config_is_unchanged_and_project_mcp_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / 'user-config'; home.mkdir()
            user = home / 'config.toml'
            contents = 'model="test-model"\n[mcp_servers.personal]\ncommand="unused"\n'
            user.write_text(contents, encoding='utf-8')
            project = root / 'project/.codex'; project.mkdir(parents=True)
            (project / 'config.toml').write_text('[mcp_servers.project]\ncommand="unused"\n', encoding='utf-8')
            with patch.dict(live.os.environ, {'CODEX_HOME': str(home)}):
                flags, model = live.codex_settings(project.parent)
            self.assertEqual(model, 'test-model')
            self.assertIn('--ignore-user-config', live.AGENTS['codex'])
            self.assertIn('mcp_servers."project".enabled=false', flags)
            self.assertIn('features.plugins=false', flags)
            self.assertEqual(user.read_text(encoding='utf-8'), contents)


    def test_child_cli_drops_app_transport_but_keeps_sandbox_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inherited = {key: 'parent-app' for key in live.APP_SESSION_ENV}
            inherited['CODEX_PERMISSION_PROFILE'] = 'preserved-permissions'
            with patch.dict(live.os.environ, inherited), patch.object(live.shutil, 'which', return_value=sys.executable), patch.object(live, 'codex_isolation_supported', return_value=True), patch.object(live, 'codex_settings', return_value=([], '')), patch.object(live.subprocess, 'Popen') as launch:
                launch.return_value.returncode = 0; launch.return_value.communicate.return_value = (b'', b'')
                ok, reason = live.run_agent(root, 'codex', '실행 확인', 10, root / 'probe.log', track=False, images=True)
            self.assertTrue(ok, reason)
            command = launch.call_args.args[0]
            env = launch.call_args.kwargs['env']
            self.assertFalse(set(live.APP_SESSION_ENV) & env.keys())
            self.assertEqual(env['CODEX_PERMISSION_PROFILE'], 'preserved-permissions')
            self.assertEqual(command[command.index('-s') + 1], 'workspace-write')


class ChosenModelTest(unittest.TestCase):
    def test_written_value_beats_preset(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'wiki.json').write_text(json.dumps({'quality': '빠르게', 'model': 'm1', 'effort_deep': 'high', 'speed_deep': 'fast'}), encoding='utf-8')
            with patch.object(live, 'model_choices', return_value={'base': {}}):     # 기준 모델이 목록에 없으면 사용자 설정의 모델
                self.assertEqual(live.chosen(d, 'codex', False, 'base'), ('m1', 'low', ''))
                self.assertEqual(live.chosen(d, 'codex', True, 'base'), ('base', 'high', 'fast'))

    def test_unset_codex_model_is_the_engine_model_not_the_users_global_one(self):
        with tempfile.TemporaryDirectory() as d:          # 새 위키는 wiki.json 에 모델이 없다. 전역 설정이 다른 모델이어도 기준 모델로 쓴다
            Path(d, 'wiki.json').write_text('{}', encoding='utf-8')
            with patch.object(live, 'model_choices', return_value={live.CODEX_MODEL: {}, 'gpt-6-astra': {}}):
                self.assertEqual(live.chosen(d, 'codex', False, 'gpt-6-astra')[0], live.CODEX_MODEL)
                self.assertEqual(live.chosen(d, 'codex', True, '')[0], live.CODEX_MODEL)


class FileReplyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case, self.state = fixture(self.root)

    def test_document_content_is_saved_without_running_commands(self):
        live.apply_file_reply(self.root, {'files': [{'path': 'docs/시험.md', 'content': DOC + '\n추가 문장.\n'}]})
        self.assertIn('추가 문장.', (self.root / 'docs/시험.md').read_text(encoding='utf-8'))

    def test_partial_edits_preserve_the_rest_and_reject_ambiguous_matches(self):
        live.apply_file_reply(self.root, {'files': [{'path': 'docs/시험.md', 'content': None, 'edits': [{'old': '기록 A.', 'new': '기록 A. 추가.'}]}]})
        expected = DOC.replace('기록 A.', '기록 A. 추가.')
        self.assertEqual((self.root / 'docs/시험.md').read_text(encoding='utf-8'), expected)
        for old in ('없는 문구', '## '):
            with self.subTest(old=old), self.assertRaises(ValueError):
                live.apply_file_reply(self.root, {'files': [{'path': 'docs/시험.md', 'content': None, 'edits': [{'old': old, 'new': '잘못된 수정'}]}]})
            self.assertEqual((self.root / 'docs/시험.md').read_text(encoding='utf-8'), expected)

    def test_entire_reply_is_checked_before_any_file_is_saved(self):
        for forbidden in ('../outside.md', 'tools/live.py', 'docs/file:stream.md', '.live/verdict_in.json'):
            with self.subTest(path=forbidden), self.assertRaises(ValueError):
                live.apply_file_reply(self.root, {'files': [{'path': 'docs/시험.md', 'content': '먼저 저장하면 안 됨'}, {'path': forbidden, 'content': '금지'}]})
            self.assertEqual((self.root / 'docs/시험.md').read_text(encoding='utf-8'), DOC)

    def test_a_reply_cannot_change_or_remove_a_seal(self):
        for path, content in [('plan/시험/truth.md', '변경'), ('plan/시험/state.json', '{"sealed":false}')]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                live.apply_file_reply(self.root, {'files': [{'path': path, 'content': content}]})
        self.assertEqual(json.loads((self.case / 'state.json').read_text(encoding='utf-8')), self.state)


class UndoTest(unittest.TestCase):
    def test_undo_is_refused_after_a_reader_reveals_the_solution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); case, _ = fixture(root)
            L = live.Live(root, 'codex'); L.busy = False
            live.S.snapshot(root, '이어 쓰기')
            self.assertFalse(L.readers_moved_since(live.S.latest_snapshot(root)))
            live.F.update_state(case, revealed=True)
            self.assertIn('되돌리지 않습니다', L.ops('undo'))
            self.assertTrue(live.F.read(case / 'state.json')['revealed'])


class AccessAndConfigTest(unittest.TestCase):
    def test_remote_devices_can_be_made_read_only_but_this_computer_never_is(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'wiki.json').write_text('{}', encoding='utf-8')
            self.assertTrue(live.can_play(root, '100.1.2.3'))                    # 기본은 지금까지처럼 누를 수 있다
            (root / 'wiki.json').write_text('{"remote": "read"}', encoding='utf-8')
            self.assertFalse(live.can_play(root, '100.1.2.3'))
            self.assertTrue(live.can_play(root, '127.0.0.1'))

    def test_bad_settings_are_reported(self):
        self.assertEqual(live.conf_problems({'agent': 'codex', 'quality': '기본', 'images': 'off', 'steps': {'premise': {'model': 'm', 'effort': 'low'}}}), [])
        bad = live.conf_problems({'agent': 'gpt', 'images': 'yes', 'remote': 'all', 'steps': {'없는단계': {}}})
        self.assertEqual(len(bad), 4, bad)

    def test_agent_cannot_create_hidden_or_reserved_documents(self):
        with tempfile.TemporaryDirectory() as d:
            class L: pass
            L.root = Path(d); (L.root / 'docs').mkdir(); (L.root / 'plan').mkdir()
            new = lambda n: f'=== 문서 | {n} | 가 | 새\n--- 새문서\n---\ntype: 기타\n---\n## 개요\n내용\n'
            fast.apply(L, new('.숨김') + new('CON') + new('보통 문서'), None)
            self.assertEqual(sorted(p.name for p in (L.root / 'docs').iterdir()), ['보통 문서.md'])


if __name__ == '__main__':
    unittest.main()
