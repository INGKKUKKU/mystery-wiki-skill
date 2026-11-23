"""얼굴 가림: 가릴지는 이름 목록이, 어느 얼굴인지는 그린 쪽이 적은 자리가 정한다."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'assets' / 'tools'))
import caseflow as F


class FacesTest(unittest.TestCase):
    def test_names_decide_who_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            (case / 'names.md').write_text('- 한재욱 : 골키퍼\n- 배도현 → 배 씨, 배 씨 : 대표\n', encoding='utf-8')
            row = lambda what, face='-', place='구절': ['a.png', '문서', what, '캡처', '사건 전개', '캡션', face, place]
            self.assertFalse(F.hidden(case, row('남자가 한재욱 앞에 앉아 있다', '가림')))      # 사진 담당의 얼굴 칸은 믿지 않는다
            self.assertTrue(F.hidden(case, row('배 씨가 회견장에 서 있다')))
            self.assertTrue(F.hidden(case, ['a.png', '문서', '남자', '사진', '사건 전개', '캡션', '가림']))      # 작가가 쓰던 옛 줄은 그 칸을 따른다

    def test_drawer_marks_the_face(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / 'a.png'
            self.assertIsNone(F.spots(raw))
            (Path(tmp) / 'a.png.faces').write_text('없음\n', encoding='utf-8'); self.assertEqual(F.spots(raw), [])
            (Path(tmp) / 'a.png.faces').write_text('0.1 0.2 0.3 0.4\n', encoding='utf-8'); self.assertEqual(F.spots(raw), [(0.1, 0.2, 0.3, 0.4)])

    def test_only_the_marked_spot_is_blurred(self):
        try:
            import cv2, numpy as np
        except ImportError:
            self.skipTest('OpenCV 없음')
        sys.modules.setdefault('__main__', sys.modules[__name__])
        import live
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 's.png', Path(tmp) / 'd.png'
            img = np.zeros((200, 200, 3), np.uint8); img[:, :100] = (0, 0, 255); img[::2, 100:] = 255      # 오른쪽 절반은 줄무늬
            cv2.imwrite(str(src), img)
            self.assertTrue(live.mosaic(src, dst, [(0.55, 0.1, 0.4, 0.8)]))
            out = cv2.imread(str(dst))
            self.assertTrue((out[:, :90] == img[:, :90]).all())                  # 짚지 않은 왼쪽은 그대로
            self.assertFalse((out[30:170, 120:180] == img[30:170, 120:180]).all())     # 짚은 자리는 가려졌다
            self.assertTrue(live.mosaic(src, dst, []))                            # 얼굴이 안 보인다고 했으면 그대로 낸다
            self.assertTrue((cv2.imread(str(dst)) == img).all())


if __name__ == '__main__':
    unittest.main()
