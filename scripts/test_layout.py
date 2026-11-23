"""공개 문서 렌더링 회귀 검사. 사건 설계나 실행 중인 위키는 읽지 않는다."""
import base64
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'assets' / 'tools'))
import build


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / 'img'
        self.images.mkdir()
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF1sAAAAASUVORK5CYII=')
        for name in ('a.png', 'b.png'):
            (self.images / name).write_bytes(png)

    def render(self, text, **kwargs):
        return build.render(text, {}, self.images, self.root / 'out', **kwargs)

    def test_a_chat_block_is_drawn_as_a_screen_and_escapes_its_text(self):
        result = self.render(':::대화 운영 대화방\n가 | 21:03 | 먼저 <b>갑니다</b>\n나 | 21:04 | 네\n:::\n뒤 문단')
        self.assertIn('<figure class="chat">', result)
        self.assertEqual(result.count('class="cm"'), 2)
        self.assertIn('운영 대화방', result); self.assertIn('21:04', result)
        self.assertNotIn('<b>갑니다</b>', result)

    def test_overview_precedes_contents_without_losing_links_or_notes(self):
        result = self.render('::: 정보\n날짜 | 2020년\n:::\n## 개요\n본문[^각주 내용]\n\n'
                             '![첫 사진](a.png)\n![둘째 사진](b.png)\n\n## 전개\n다음 문단')
        elements = Elements(result).elements
        ids = [a['id'] for _, a in elements if 'id' in a]
        self.assertEqual(ids, ['s1', 'r1', 'toc', 's2', 'fn1'])
        self.assertEqual(sum(a.get('class') == 'article-lead' for _, a in elements), 1)
        self.assertEqual(sum(a.get('class') == 'media gallery' for _, a in elements), 1)
        self.assertIn('다음 문단', result)
        self.assertIn('각주 내용', result)

    def test_photo_groups_follow_paragraph_boundaries(self):
        result = self.render('![첫 사진](a.png)\n\n![둘째 사진](b.png)\n\n설명 문단\n\n![따로](a.png)')
        groups = [a['class'] for tag, a in Elements(result).elements if tag == 'div' and a.get('class', '').startswith('media')]
        self.assertEqual(groups, ['media gallery', 'media'])
        self.assertEqual(len(list((self.root / 'out').glob('*.png'))), 2)

    def test_missing_images_leave_no_empty_group(self):
        self.assertEqual(self.render('![없는 사진](missing.png)'), '')
        ghost = self.render('![없는 사진](missing.png)', ghost=True)
        self.assertIn('사진 자리', ghost)

    def test_documents_without_an_infobox_and_unnumbered_views(self):
        text = '## 개요\n내용\n\n### 상세\n설명'
        self.assertNotIn('article-lead', self.render(text))
        plain = self.render(text, numbered=False)
        self.assertNotIn('class="toc"', plain)
        self.assertIn('상세', plain)

    def test_map_moves_labels_but_preserves_coordinates_and_escaping(self):
        rows = ['크기 | 100 80', '건물 | 시험 건물 | 20 20 10 10',
                '점 | 첫 지점 | 25 25', '점 | 둘째 지점 | 25 25', '점 | A&B <지점> | 25 25']
        svg = ET.fromstring(build.draw_map(rows))
        ns = {'s': 'http://www.w3.org/2000/svg'}
        points = svg.findall('s:circle', ns)
        self.assertEqual([(p.attrib['cx'], p.attrib['cy']) for p in points], [('160.0', '160.0')] * 3)
        building = svg.findall('s:rect', ns)[1]
        self.assertEqual([building.attrib[k] for k in ('x', 'y', 'width', 'height')], ['128.0', '128.0', '64.0', '64.0'])
        labels = svg.findall('s:text[@class="map-label"]', ns)
        self.assertEqual({l.text for l in labels}, {'시험 건물', '첫 지점', '둘째 지점', 'A&B <지점>'})
        self.assertEqual(len({(l.attrib['x'], l.attrib['y']) for l in labels}), len(labels))


if __name__ == '__main__':
    unittest.main()
