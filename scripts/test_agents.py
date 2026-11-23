"""에이전트 CLI 찾기: Codex 앱 안의 CLI, PATH의 CLI, 데스크톱 앱에 든 CLI 차례. 실제 에이전트는 부르지 않는다."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'assets' / 'tools'))
import agents as A


class FindTest(unittest.TestCase):
    def setUp(self):
        A._found.clear(); self.addCleanup(A._found.clear)
        self.tmp = Path(tempfile.mkdtemp()); self.exe = 'claude.exe' if os.name == 'nt' else 'claude'

    def fake(self, *parts):
        p = self.tmp.joinpath(*parts); p.parent.mkdir(parents=True, exist_ok=True); p.write_text('x'); return str(p)

    def test_path_cli_comes_before_the_app_one(self):
        self.fake('Claude', 'claude-code', '1.0', 'h', self.exe)
        with patch.dict(os.environ, {'APPDATA': str(self.tmp)}), patch.object(A.shutil, 'which', return_value='/usr/bin/claude'):
            self.assertEqual(A.find('claude'), '/usr/bin/claude')

    def test_app_cli_is_found_when_nothing_is_on_path(self):
        old = self.fake('Claude', 'claude-code', '1.0', 'a', self.exe); new = self.fake('Claude', 'claude-code', '2.0', 'b', self.exe)
        os.utime(old, (1, 1))
        with patch.dict(os.environ, {'APPDATA': str(self.tmp)}), patch.object(A.shutil, 'which', return_value=None), patch.object(A.Path, 'home', return_value=self.tmp / 'home'):
            self.assertEqual(A.find('claude'), new)       # 판이 여럿이면 가장 새것

    def test_codex_app_session_cli_wins(self):
        app = self.fake('codex-app')
        with patch.dict(os.environ, {'CODEX_APP_RUNTIME_CLI_PATH': app}), patch.object(A.shutil, 'which', return_value='/usr/bin/codex'):
            self.assertEqual(A.find('codex'), app)

    def test_missing_cli_explains_how_to_get_it_and_is_not_remembered(self):
        with patch.object(A.shutil, 'which', return_value=None), patch.object(A, 'bundled', return_value=None):
            ok, said = A.diagnose('claude')
            self.assertFalse(ok); self.assertIn('Code 탭', said); self.assertNotIn('claude', A._found)

    def test_logged_out_cli_gets_the_login_command(self):
        with patch.object(A.shutil, 'which', return_value='/x/codex'), patch.object(A, 'logged_in', return_value=False):
            ok, said = A.diagnose('codex')
        self.assertFalse(ok); self.assertIn('/x/codex login', said)

    def test_child_env_drops_parent_session(self):
        with patch.dict(os.environ, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's', A.APP_SESSION_ENV[0]: 'pipe', 'KEEP': 'y'}):
            e = A.env()
        self.assertNotIn('CLAUDECODE', e); self.assertNotIn('CLAUDE_CODE_SESSION_ID', e); self.assertNotIn(A.APP_SESSION_ENV[0], e)
        self.assertEqual(e['KEEP'], 'y'); self.assertEqual(e['PYTHONUTF8'], '1')

    def test_new_wiki_follows_the_app_you_are_talking_in(self):
        with patch.object(A, 'find', side_effect=lambda a: '/x/' + a):
            with patch.dict(os.environ, {'CODEX_THREAD_ID': 't'}, clear=True):
                self.assertEqual(A.guess(), 'codex')
            with patch.dict(os.environ, {'CLAUDECODE': '1'}, clear=True):
                self.assertEqual(A.guess(), 'claude')


class SpawnTest(unittest.TestCase):
    def setUp(self):
        A.STOP.clear(); self.addCleanup(A.STOP.clear)

    def test_prompt_goes_in_and_output_comes_back(self):
        code, so, _, end = A.spawn([sys.executable, '-c', 'import sys; print(sys.stdin.read()[::-1])'], '가나다', None, 30)
        self.assertEqual((code, end), (0, '')); self.assertIn('다나가', so.decode('utf-8'))

    def test_timeout_ends_the_call(self):
        code, _, _, end = A.spawn([sys.executable, '-c', 'import time; time.sleep(60)'], '', None, 1)
        self.assertEqual(end, 'timeout'); self.assertFalse(A.PROC)

    def test_stop_ends_running_calls(self):
        import threading, time
        got = []
        t = threading.Thread(target=lambda: got.append(A.spawn([sys.executable, '-c', 'import time; time.sleep(60)'], '', None, 60)))
        t.start(); time.sleep(1); A.stop_all(); t.join(20)
        self.assertFalse(t.is_alive()); self.assertEqual(got[0][3], 'stopped')

    def test_a_call_that_finished_during_a_pause_keeps_its_answer(self):
        A.STOP.set()                      # 잠깐 멈춤은 돌던 호출을 기다린다. 제대로 끝난 답은 버리지 않는다
        code, so, _, end = A.spawn([sys.executable, '-c', 'print("답")'], '', None, 30, track=False)
        self.assertEqual((code, end), (0, ''))

    def test_failure_reason_names_the_login_command(self):
        with patch.object(A, 'find', return_value='/x/claude'):
            self.assertIn('/x/claude auth login', A.why('Error: not logged in', 'claude'))
        self.assertEqual(A.why('usage limit reached'), '에이전트 사용량 한도에 걸렸습니다')


if __name__ == '__main__':
    unittest.main()
