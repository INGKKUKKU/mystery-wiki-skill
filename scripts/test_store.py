"""파일 쓰기와 서버 잠금."""
import sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'assets' / 'tools'))
import store as S


class StoreTest(unittest.TestCase):
    def test_write_replaces_whole_file_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a' / '문서.md'
            S.write(p, '첫 판'); S.write(p, '둘째 판')
            self.assertEqual(p.read_text(encoding='utf-8'), '둘째 판')
            self.assertEqual([x.name for x in p.parent.iterdir()], ['문서.md'])

    def test_concurrent_writers_never_leave_a_mixed_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'state.json'
            texts = [str(i) * 5000 for i in range(8)]
            ts = [threading.Thread(target=lambda t=t: [S.write(p, t) for _ in range(20)]) for t in texts]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertIn(p.read_text(encoding='utf-8'), texts)

    def test_only_one_holder_of_the_server_lock(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / '.live' / 'server.lock'
            first = S.hold(lock)
            self.assertIsNotNone(first)
            self.assertIsNone(S.hold(lock))
            first.close()
            again = S.hold(lock); self.assertIsNotNone(again); again.close()


class SnapshotTest(unittest.TestCase):
    def test_restore_goes_back_one_turn_keeps_photos_and_can_be_undone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            S.write(root / 'docs' / '사건.md', '앞 판'); S.write(root / 'plan' / 'c' / 'truth.md', '진상')
            S.snapshot(root, '이어 쓰기')
            S.write(root / 'docs' / '사건.md', '뒤 판'); S.write(root / 'docs' / '새 문서.md', '새것')
            S.write(root / 'docs' / 'img' / 'a.png', b'png'); S.write(root / 'plan' / 'c' / 'img' / 'b.png', b'png')
            self.assertEqual(S.restore(root), '이어 쓰기')
            self.assertEqual((root / 'docs' / '사건.md').read_text(encoding='utf-8'), '앞 판')
            self.assertFalse((root / 'docs' / '새 문서.md').exists())
            self.assertTrue((root / 'docs' / 'img' / 'a.png').is_file()); self.assertTrue((root / 'plan' / 'c' / 'img' / 'b.png').is_file())
            before = [p for p in (root / '.live' / 'snapshots').iterdir() if p.name.startswith('_')]
            self.assertEqual((before[0] / 'docs' / '사건.md').read_text(encoding='utf-8'), '뒤 판')      # 되돌리기 전 것도 남는다
            self.assertIsNone(S.restore(root))                                                           # 같은 지점으로 두 번 가지 않는다

    def test_undoing_a_new_case_leaves_no_empty_case_folder_and_two_undos_in_a_row_work(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); S.write(root / 'docs' / 'a.md', '1'); S.write(root / 'plan' / 'old' / 'truth.md', 't')
            S.snapshot(root, '첫'); S.write(root / 'docs' / 'a.md', '2')
            S.snapshot(root, '새 사건'); S.write(root / 'plan' / 'new' / 'truth.md', 'n'); S.write(root / 'plan' / 'new' / 'img' / 'x.png', b'p')
            self.assertEqual(S.restore(root), '새 사건'); self.assertEqual(S.restore(root), '첫')      # 같은 초에 두 번
            self.assertFalse((root / 'plan' / 'new').exists())
            self.assertEqual((root / 'docs' / 'a.md').read_text(encoding='utf-8'), '1')
            self.assertFalse(list(root.glob('.*.restoring')))

    def test_a_failed_swap_puts_everything_back(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); S.write(root / 'docs' / 'a.md', '앞'); S.write(root / 'plan' / 'c' / 'truth.md', '앞')
            S.snapshot(root, '이어 쓰기'); S.write(root / 'docs' / 'a.md', '뒤'); S.write(root / 'plan' / 'c' / 'truth.md', '뒤')
            real, calls = S.os.replace, []
            def flaky(a, b):
                calls.append(a)
                if str(a).endswith('.plan.restoring'):
                    raise PermissionError('잡혀 있음')
                return real(a, b)
            with patch.object(S.os, 'replace', flaky), self.assertRaises(OSError):
                S.restore(root)
            self.assertEqual((root / 'docs' / 'a.md').read_text(encoding='utf-8'), '뒤')
            self.assertEqual((root / 'plan' / 'c' / 'truth.md').read_text(encoding='utf-8'), '뒤')
            self.assertEqual(len(S.snapshots(root)), 1)                                     # 실패하면 스냅샷도 그대로

    def test_only_recent_snapshots_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); S.write(root / 'docs' / 'a.md', 'x')
            for i in range(S.KEEP + 2):
                S.snapshot(root, str(i))
            self.assertEqual(len(S.snapshots(root)), S.KEEP)


if __name__ == '__main__':
    unittest.main()
