#!/usr/bin/env python3
"""plan/ 과 docs/ 가 서로 맞는지 검사한다. 표준 라이브러리만 쓴다.

사용법: python tools/check.py [위키 폴더] [--live]
  --live  사건을 쓰는 도중에 쓴다. 아직 안 채운 것은 넘어가고, 새는 것과 어긋난 것만 본다.
오류가 있으면 종료 코드 1. 경고는 하나씩 읽고 고치거나 plan/allow.md에 이유를 적는다.
"""
import sys, re, json, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from build import load, starts, start_doc, LINK

MAX_BODY, MAX_START = 2500, 9000     # 사건 문서는 대부분의 내용을 품으므로 길어도 된다
# 문서 종류: (순서대로 있어야 하는 문단, 정보 상자에 있어야 하는 항목). tools/templates/ 의 뼈대와 맞춘다.
TYPES = {
    '사건': (['개요', '사건 전개', '의문점', '이후'], ['발생일', '장소', '유형', '상태']),
    '인물': (['개요', '생애'], ['출생', '직업']),
    '장소': (['개요', '위치와 구조', '역사'], ['소재지', '종류']),
    '기관': (['개요', '역사'], ['소재지', '종류']),
    '지역': (['개요', '사건 사고'], ['종류']),       # 시, 군, 구, 동
    '매체': (['개요'], ['종류']),                     # 방송 프로그램, 신문, 책
    '기타': (['개요'], []),
}


def tools_hash(folder):
    """틀 파일 전체의 지문. 위키를 만들 때 wiki.json 에 적어 두고, 누가 틀을 고쳤는지 알아보는 데 쓴다."""
    h = hashlib.sha256()
    for f in sorted(p for p in Path(folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts):
        h.update(f.relative_to(folder).as_posix().encode()); h.update(f.read_bytes().replace(b'\r\n', b'\n'))
    return h.hexdigest()[:16]
DATE = re.compile(r'(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일')
TIME = re.compile(r'(\d{1,2})시(?!간)(?:\s*(\d{1,2})분|\s*(반))?')
CLOCK = re.compile(r'(?<![\d:-])(\d{1,2}):(\d{2})(?![\d:])')


def table(path):
    """마크다운 표를 [{머리글: 값}] 으로 읽는다."""
    if not path.is_file():
        return []
    rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in path.read_text(encoding='utf-8-sig').splitlines()
            if l.strip().startswith('|') and not re.fullmatch(r'[|\-: ]+', l.strip())]
    return [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []


def plain(s):
    """꾸밈 기호를 떼고 공백을 하나로 줄인다. 문구 비교용."""
    s = LINK.sub(lambda m: m[2] or m[1], s)
    s = re.sub(r'\x00\d+\x00|\*\*|~~', '', s)
    return re.sub(r'\s+', ' ', s)


def moments(s, clock=True):
    """글에서 날짜와 시각 표현을 뽑는다. -> ({(년|None, 월, 일)}, {(시, 분|None)})"""
    # 연도 없는 날짜는 같은 문단에서 앞서 나온 연도를 이어받는다. "2019년 2월 12일 … 하루 앞선 2월 11일"의 11일을 아무 해로 보면
    # 다른 사건의 비공개 시간표(1997-02-11)와 맞아 새어 나감으로 잡혔다(2026-11-22, 실존 그룹 문서)
    dates = set()
    for para in s.split('\n'):
        year = None
        for m in DATE.finditer(para):
            year = int(m[1]) if m[1] else year
            dates.add((year, int(m[2]), int(m[3])))
    times = {(int(h), int(mi) if mi else 30 if half else None) for h, mi, half in TIME.findall(s)}
    if clock:
        times |= {(int(h), int(mi)) for h, mi in CLOCK.findall(s)}
    return dates, times


def unknown_day(row):
    return bool(re.search(r'(월일|일자|날짜)\s*(?:은|는)?\s*미상', ' '.join(str(v) for v in row.values())))


def date_ok(d, allowed):
    return any(d[1:] == a[1:] and (d[0] is None or d[0] == a[0]) for a in allowed)


def time_ok(t, allowed):
    # ponytail: 오전/오후를 구분하지 않는다. "11시 40분"은 11:40과 23:40 둘 다에 맞는 것으로 본다.
    return any(t[0] % 12 == a[0] % 12 and (t[1] is None or a[1] is None or t[1] == a[1]) for a in allowed)


def similar(a, b):
    """두 한글 글자가 오타로 보일 만큼 닮았나 (초성·중성·종성 셋 중 둘이 같음). '동'과 '둥'은 닮았고 '동'과 '안'은 아니다."""
    x, y = ord(a) - 0xAC00, ord(b) - 0xAC00
    if not (0 <= x < 11172 and 0 <= y < 11172):
        return False
    return (x // 588 == y // 588) + (x % 588 // 28 == y % 588 // 28) + (x % 28 == y % 28) >= 2


# --live 에서 남기는 것들. ponytail: 메시지 글귀로 고른다. 메시지를 고치면 여기도 고친다.
LIVE_KEEP = ('비공개인데', 'timeline.md에 없습니다', '비공개 시간표에만', '잘못된 표기일 수', '실명이 그대로', 'tools/ 의 틀', '끊어 쓴', '각주가', '틀의 말', '출처를 밝히는', '직접 그린', '단서를 다는')


def check(project, live=False):
    project = Path(project); plan = project / 'plan'; docs = load(project)
    err, warn = [], []
    P = {n: dict(본문=plain(d['body_text']), 각주=plain('\n'.join(d['notes'])), 역사=plain(d['역사']), 토론=plain(d['토론'])) for n, d in docs.items()}
    ALL = {n: ' '.join(p.values()) for n, p in P.items()}
    # plan/<사건>/ 마다 사건 설계가 있고, plan/ 바로 아래는 사건들을 잇는 세계 설계다
    cases = [d for d in sorted(plan.iterdir()) if d.is_dir()] if plan.is_dir() else []
    label = lambda d: '' if d == plan else d.name + '/'
    if not cases:
        warn.append('plan/ 아래에 사건 폴더가 없습니다.')
    for d in cases:
        for f in ('truth.md', 'timeline.md', 'pieces.md', 'names.md'):
            if not (d / f).is_file():
                err.append(f'plan/{label(d)}{f} 가 없습니다. 문서를 쓰기 전에 설계부터 합니다.')
    if not (plan / 'truth.md').is_file():
        err.append('plan/truth.md (세계 설계) 가 없습니다. 사건들이 어떻게 이어지고 안 이어지는지를 여기에 적습니다.')

    def merged(name):
        return [dict(r, _k=label(d)) for d in cases + [plan] for r in table(d / name)]
    allow = merged('allow.md')
    red_ok = {a['문구'] for a in allow if a.get('종류') == '빨간링크'}
    odd = [a for a in allow if a.get('종류') == '어긋남']
    for a in odd:
        if plain(a['문구']) not in ALL.get(a['문서'], ''):
            err.append(f'allow.md: 어긋남 문구 "{a["문구"]}" 가 문서 "{a["문서"]}" 에 없습니다.')

    # 1. 링크: 모든 링크는 문서로 이어지거나, 일부러 둔 빨간 링크여야 한다
    links = {n: {m[1].strip() for m in LINK.finditer(d['body'] + d['토론'])} for n, d in docs.items()}
    for n, ls in links.items():
        for t in sorted(ls - set(docs) - red_ok):
            err.append(f'{n}: [[{t}]] 문서가 없습니다. 문서를 만들거나 allow.md에 빨간링크로 적습니다.')
    for t in sorted(red_ok - set().union(*links.values())):
        warn.append(f'allow.md: 빨간링크 "{t}" 를 거는 문서가 없습니다.')

    # 2. 닿을 수 있는지: 시작 문서에서 링크만 타고 모든 문서에 갈 수 있어야 한다
    first = set(starts(docs)) | {start_doc(docs)}; seen, todo = set(first), list(first)
    while todo:
        n = todo.pop()
        nxt = (links[n] & set(docs)) | {f'{docs[n]["base"]}@{r[0]}' for r in docs[n]['history']} & set(docs)
        for t in nxt - seen:
            seen.add(t); todo.append(t)
    for n in sorted(set(docs) - seen):
        d = docs[n]
        if d['rev']:
            if d['base'] in docs and d['base'] not in seen:
                continue        # 판이 아니라 그 문서 자체가 안 이어진 것이다. 그 오류 하나만 낸다(고치는 쪽이 역사 줄만 거듭 덧붙였다)
            err.append(f'{n}: 이전 판인데 "{d["base"]}" 의 역사에 {d["rev"]} 줄이 없어서 갈 길이 없습니다.')
        elif d['meta'].get('search') == 'true':
            # 검색으로 닿는 문서. 제목이나, 설계가 정한 검색어(search_word) 가운데 하나가 이 문서와 이어진 문서 양쪽에 글자로 있으면 찾아진다
            words = [n] + [w.strip() for w in re.split(r'[,/]', d['meta'].get('search_word', '')) if w.strip()]
            if not any((w == n or w in ALL[n]) and any(w in ALL[o] for o in seen) for w in words):
                err.append(f'{n}: 검색 전용 문서인데 제목이나 검색어가 이어진 문서 어디에도 글자로 나오지 않습니다.')
        else:
            err.append(f'{n}: 시작 문서에서 링크로 갈 수 없습니다. (검색으로만 열리게 하려면 머리말에 search: true)')

    # 3. 조각: 설계한 자리에 실제로 들어갔는지, 숨긴 것이 새지 않았는지.
    # 단서가 몇 개인지, 어느 문서에 몇 번 링크를 타야 나오는지는 보지 않는다. 사건마다 추리의 모양이 다르다.
    # 발견할 수 있는지는 본다: 문구가 그 자리에 있고(아래), 그 문서가 시작 문서에서 링크나 검색으로 닿고(위 2),
    # 토론·역사·이전 판에 숨은 것은 본문이나 각주에 그쪽을 열어 보게 하는 문장이 있다(안내).
    pieces = merged('pieces.md')
    for p in pieces:
        no, kind, phrase = p['_k'] + p.get('번호', '?'), p.get('종류', ''), plain(p.get('문구', ''))
        if not phrase:
            err.append(f'조각 {no}: 문구가 비었습니다.'); continue
        if kind == '비공개':
            for n in docs:
                if phrase in ALL[n]:
                    err.append(f'조각 {no}: 비공개인데 문서 "{n}" 에 "{phrase}" 가 나옵니다.')
            continue
        doc, where = p.get('문서', ''), p.get('위치', '본문')
        if doc not in docs:
            err.append(f'조각 {no}: 문서 "{doc}" 가 없습니다.'); continue
        if where not in P[doc]:
            err.append(f'조각 {no}: 위치는 본문/각주/역사/토론 중 하나여야 합니다. (지금: {where})'); continue
        if phrase not in P[doc][where]:
            err.append(f'조각 {no}: 문서 "{doc}" 의 {where}에 "{phrase}" 가 없습니다.')
        if where in ('토론', '역사') or '@' in doc:
            guide = plain(p.get('안내', ''))
            if not guide:
                warn.append(f'조각 {no}: 숨은 자리({where}, 이전 판)에 있는데 안내 문구가 없습니다. 본문에 그쪽을 열어 보게 하는 문장을 두고 안내 칸에 적습니다.')
            elif not any(guide in P[n]['본문'] or guide in P[n]['각주'] for n in docs if '@' not in n):
                err.append(f'조각 {no}: 안내 문구 "{guide}" 가 어느 문서의 본문·각주에도 없습니다.')
        # 미끼에 따로 반박 조각이 있는지는 보지 않는다. 그릇된 설이 공개된 사실로 버려지는지는 따져 보기와 시험 독자가 본다
    for d in cases:   # 사건마다 따로 본다. 세계 설계(plan/ 바로 아래)는 조각이 없어도 된다
        kinds = {p.get('종류') for p in pieces if p['_k'] == label(d)}
        if '진실' not in kinds:
            err.append(f'{label(d)}pieces.md: 진실 조각이 없습니다. 진상에 닿는 단서가 문서 어디에도 기록되지 않았습니다.')
        if (d / 'truth.md').is_file():
            t = (d / 'truth.md').read_text(encoding='utf-8-sig')
            for h in ('훅', '수사는 왜 못 풀었나'):
                if not re.search(rf'^##+ {h}', t, re.M):
                    err.append(f'{label(d)}truth.md: "## {h}" 문단이 없습니다.')
            m = re.search(r'^##+ 수사는 왜 못 풀었나.*?(?=^##+ |\Z)', t, re.M | re.S)
            if m and sum(l.strip().startswith('|') for l in m[0].splitlines()) < 7:
                warn.append(f'{label(d)}truth.md: "수사는 왜 못 풀었나" 표가 5줄 미만입니다. 수사 수단마다 한 줄씩 채웁니다.')
    if (plan / 'truth.md').is_file() and cases:
        t = (plan / 'truth.md').read_text(encoding='utf-8-sig')
        m = re.search(r'^##+ 이미 쓴 것.*?(?=^##+ |\Z)', t, re.M | re.S)
        if not m or sum(l.strip().startswith('|') for l in m[0].splitlines()) - 2 < len(cases):
            warn.append('plan/truth.md: "이미 쓴 것" 표에 사건마다 한 줄씩 있어야 합니다.')

    # 4. 날짜와 시각: 문서에 나오는 것은 전부 timeline.md에 있어야 한다
    pub_d, pub_t, sec_d, sec_t = set(), set(), set(), set()
    sec_own = {}            # 비공개 날짜가 어느 사건의 것인지. 다른 사건 문서에 같은 날짜가 있는 것은 새는 것이 아니다(1993-06-09가 앞 사건 문서의 공개 날짜와 겹쳐 오류 18개)
    own_doc = {(re.search(r'^## 사건 문서 이름[ \t]*\n+(.+)$', (d / 'truth.md').read_text(encoding='utf-8-sig'), re.M) or ['', ''])[1].strip(): label(d)
               for d in cases if (d / 'truth.md').is_file()}
    for r in merged('timeline.md'):
        m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?', r.get('시각', ''))
        if not m:
            continue
        if unknown_day(r):          # 월일을 모르는 줄은 1월 1일 같은 자리표시를 적는다. 그 날짜는 사건의 날짜가 아니다(1968-01-01이 부평구의 실제 연혁과 겹쳐 새어 나감으로 잡혔다)
            continue
        secret = r.get('공개', '') == '비공개'
        (sec_d if secret else pub_d).add((int(m[1]), int(m[2]), int(m[3])))
        if secret:
            sec_own.setdefault((int(m[1]), int(m[2]), int(m[3])), set()).add(r['_k'])
        if m[4]:
            (sec_t if secret else pub_t).add((int(m[4]), int(m[5])))
    for a in odd:
        d, t = moments(plain(a['문구'])); pub_d |= d; pub_t |= t
    for n in docs:
        d1, t1 = moments(P[n]['본문'] + ' ' + P[n]['각주']); d2, t2 = moments(P[n]['토론'] + ' ' + P[n]['역사'], clock=False)
        region = docs.get(docs[n]['base'], docs[n])['meta'].get('type') == '지역'      # 시·군·구·동 문서는 그 고장의 실제 연혁 날짜를 싣는다. 사건 시간표에 없어도 된다(새는 것은 그대로 본다)
        mine = own_doc.get(docs[n]['base'])          # 이 문서가 어느 사건의 사건 문서인지(옛 판 포함)
        for d in sorted(d1 | d2, key=str):
            leak = date_ok(d, sec_d) and not (mine and not any(mine in k for a, k in sec_own.items() if date_ok(d, {a})))
            if not date_ok(d, pub_d) and not (region and not date_ok(d, sec_d)):
                (err if leak else warn).append(
                    f'{n}: 날짜 {d[0] or ""} {d[1]}월 {d[2]}일 이 ' + ('비공개 시간표에만 있습니다(새어 나감).' if leak else 'timeline.md에 없습니다.'))
        for t in sorted(t1 | t2, key=str):
            if not time_ok(t, pub_t):
                (err if time_ok(t, sec_t) else warn).append(
                    f'{n}: 시각 {t[0]}시 {"" if t[1] is None else str(t[1]) + "분"} 이 ' + ('비공개 시간표에만 있습니다(새어 나감).' if time_ok(t, sec_t) else 'timeline.md에 없습니다.'))

    # 5. 이름: 정해 둔 이름과 한 글자만 다른 표기를 찾는다 (김영숙/김영순 같은 실수)
    # ponytail: 첫 글자가 같고 한 글자만 다른 경우만 잡는다. 오탐은 allow.md 어긋남에 적어 넘긴다.
    # names.md 한 줄은 "- 이름 : 설명" 이거나 "- 실명 → 위키 표기 : 설명". 화살표가 있으면 실명은 문서에 나오면 안 된다
    names = set()
    for d in cases + [plan]:
        if not (d / 'names.md').is_file():
            continue
        for m in re.finditer(r'^- ([^:\n]+?)(?:\s*:|$)', (d / 'names.md').read_text(encoding='utf-8-sig'), re.M):
            real, arrow, shown = (x.strip() for x in m[1].partition('→'))
            if not arrow:
                names.add(real); continue
            for n in docs:
                if real in ALL[n]:
                    err.append(f'{n}: 실명이 그대로 나옵니다 ("{real}"). 문서에는 "{shown}" 로 적습니다.')
    odd_text = ' '.join(plain(a['문구']) for a in odd)
    for n in docs:
        text, hit = ALL[n], set()
        # 첫 글자가 같은 자리만 찾아 보고, 비싼 비교(다른 이름으로 시작하나, 허용 문구인가)는 한 글자만 다를 때만 한다.
        # 전에는 글자마다 모든 이름을 대 봐서, 사건 30건·문서 221개에서 한 번에 100초가 걸렸다(서버를 켤 때와 사건 끝마다 돈다)
        for name in (x for x in names if len(x) >= 3):
            L = len(name); i = text.find(name[0])
            while i != -1 and i <= len(text) - L:
                w = text[i:i + L]
                if w not in hit:
                    diff = [k for k in range(L) if w[k] != name[k]]
                    # 지명의 끝 글자(시·군·읍 …)만 다르면 오타가 아니라 조사나 긴 낱말이다("사북을", "목포지방", "경주신문")
                    place = name[-1] in '시군구읍면동리도' and diff == [L - 1]
                    if len(diff) == 1 and not place and similar(w[diff[0]], name[diff[0]]) and w not in odd_text and not any(text.startswith(x, i) for x in names):
                        hit.add(w); warn.append(f'{n}: "{w}" 는 "{name}" 의 잘못된 표기일 수 있습니다.')
                i = text.find(name[0], i + 1)

    # 6. 여러 사건에 나오는 사람의 나이: 사건마다 (사건 연도 - 당시 나이)가 같은 해에 태어난 사람이어야 한다.
    # 이름을 싣는 사람(names.md 에 화살표 없이 적힌 사람)만 본다. "손 모 씨"처럼 가린 표기는 사건마다 다른 사람이다.
    # 인물 문서에 "출생 | 1994년"이 있으면 그것이 기준이다. 생일 때문에 한 해는 어긋나도 된다
    born = {}
    for d in cases:
        t = (d / 'truth.md').read_text(encoding='utf-8-sig') if (d / 'truth.md').is_file() else ''
        title = (re.search(r'^## 사건 문서 이름[ \t]*\n+(.+)$', t, re.M) or ['', ''])[1].strip()
        year = re.search(r'^## 때와 곳[ \t]*\n+\D*?(\d{4})년', t, re.M)
        if not title or title not in ALL or not year or not (d / 'names.md').is_file():
            continue
        public = {m[1].strip() for m in re.finditer(r'^- ([^:\n→]+?)\s*:', (d / 'names.md').read_text(encoding='utf-8-sig'), re.M)}
        for name in (n for n in public if not any(m.startswith(n + '(') for m in public)):      # 박지훈과 박지훈(축구 선수)처럼 동명이인이 있으면 맨이름만으로는 누구 나이인지 모른다
            for age in set(re.findall(r'(?<![가-힣])' + re.escape(name) + r'\(당시 (\d+)세\)', ALL[title])):      # 이름 앞에 글자가 붙으면 다른 사람이다(지훈 ⊂ 박지훈. 박지훈의 나이가 다른 사람 지훈의 것으로 잡혔다)
                born.setdefault(name, []).append((int(year[1]) - int(age), title, int(year[1]), int(age)))
    for name, rows in born.items():
        doc = docs.get(name)
        b = re.search(r'출생[ \t]*\|[ \t]*(\d{4})', doc['body']) if doc and doc['meta'].get('type') == '인물' else None
        base = int(b[1]) if b else min(r[0] for r in rows)
        for y, title, yr, age in rows:
            if abs(y - base) > 1:
                src = f'인물 문서 {name}의 출생 {base}년' if b else f'다른 사건에서 {base}년생'
                err.append(f'{title}: {name}의 나이가 다른 문서와 어긋납니다({yr}년에 {age}세, {src}). 먼저 있던 문서에 맞춥니다.')

    # 글맛: 기계가 볼 수 있는 만큼만. 짧게 끊어 쓴 문단과, 각주 없이 본문에 다 밀어 넣은 긴 사건 문서
    # ponytail: 문장 길이와 각주 수만 본다. 문장이 이어지는지, 서술자가 있는지는 집필 지침(fast.py 의 VOICE)에 맡긴다.
    for n, d in docs.items():
        if d['rev'] or n == '대문' or d['meta'].get('deleted'):
            continue
        paras = [plain(p) for p in re.split(r'\n\s*\n', d['body_text']) if p.strip() and not re.match(r'\s*(#|\||:::|-|>|!\[)', p)]
        choppy = 0
        for p in paras:
            ss = [x for x in re.split(r'(?<=다\.)\s+', p) if len(x) > 5]
            choppy += len(ss) >= 3 and sum(map(len, ss)) / len(ss) < 40
        if choppy >= 2:
            warn.append(f'{n}: 문장을 짧게 끊어 쓴 문단이 {choppy}개입니다. 사실을 한 문장씩 나열하지 말고 앞뒤 관계를 문장 안에서 이어 씁니다.')
        size = len(P[n]['본문'])
        if d['meta'].get('type') == '사건' and size > 1500 and len(d['notes']) < size // 600:
            warn.append(f'{n}: 본문 {size}자에 각주가 {len(d["notes"])}개뿐입니다. 출처와 곁가지 사정은 각주로 내립니다.')

    # 각주가 전부 "~의 진술에 따른다" 꼴이면 각주가 아니라 출처 목록이다
    for n, d in docs.items():
        src = [x for x in d['notes'] if re.search(r'(따른다|따랐다|따른 것이다|기준으로 한다|기준으로 했다|옮겼다|옮긴 것이다|진술이다|의한다)\.?\s*$', plain(x).strip())]
        if len(src) >= 2 and len(src) * 2 > len(d['notes']):
            warn.append(f'{n}: 각주 {len(d["notes"])}개 중 {len(src)}개가 출처를 밝히는 말로 끝납니다("~에 따른다", "~에서 옮겼다"). 출처는 본문에 녹이고 각주에는 뒷이야기, 반론, 당시 사정을 씁니다.')
        if '<svg' in d['body']:
            warn.append(f'{n}: 직접 그린 그림(<svg>)이 있습니다. 약도와 시간표는 내용만 적으면 틀이 그립니다.')

    # 말하고 나서 곧바로 "정확하지 않을 수 있다"고 물러서는 말버릇
    HEDGE = ('다를 수 있다', '아닐 수 있다', '확정된 것은 아니', '확정은 아니', '단정할 수 없', '단정하기 어렵', '배제할 수 없', '유의해야', '유의할 필요',
             '주의가 필요', '해석에 주의', '참고용', '옮기면 다음과 같', '정리하면 다음과 같', '실측')
    for n in docs:
        hits = [w for w in HEDGE if w in ALL[n]]
        if len(hits) >= 2:
            warn.append(f'{n}: 단서를 다는 말이 여럿입니다({", ".join(hits[:4])}). 말하고 나서 "정확하지 않을 수 있다"고 물러서지 않습니다. 모르는 것은 모른다고 한 번만 씁니다.')

    # 문서가 자기 화면 구성을 말하면 위키가 아니라 만든 티가 난다
    for n in docs:
        for w in ('자료 상자', '정보 상자', '도면 상자', '위 상자', '아래 상자', '상자에 옮'):
            if w in ALL[n]:
                warn.append(f'{n}: 틀의 말("{w}")이 문서에 나옵니다. 문서는 자기 화면 구성을 가리키지 않습니다. 그 문장을 지우거나 "아래는 ~이다"처럼 씁니다.'); break

    # 6. 문서 구성: 종류마다 정해진 문단과 정보 상자가 있어야 사건이 달라도 같은 위키로 보인다
    for n, d in docs.items():
        if d['rev'] or n == '대문' or d['meta'].get('deleted'):
            continue
        kind = d['meta'].get('type', '')
        if kind not in TYPES:
            warn.append(f'{n}: 머리말의 type 이 없거나 모르는 종류입니다. ({", ".join(TYPES)} 중 하나. tools/templates/ 의 뼈대로 시작합니다)'); continue
        heads, keys = TYPES[kind]
        have = re.findall(r'^## (.+?)[ \t]*$', d['body'], re.M); it = iter(have)
        if not all(h in it for h in heads):
            warn.append(f'{n}: {kind} 문서는 문단이 "{" → ".join(heads)}" 순서로 있어야 합니다. (지금: {" → ".join(have) or "없음"})')
        m = re.search(r'^:::[^\n]*\n(.*?)^:::', d['body'], re.M | re.S)
        got = {l.split('|')[0].strip() for l in m[1].splitlines() if '|' in l} if m else set()
        lack = [k for k in keys if k not in got]
        if lack:
            warn.append(f'{n}: {kind} 문서의 정보 상자에 {", ".join(lack)} 항목이 없습니다.')
        if re.search(r'^\(.*\)[ \t]*$', d['body'], re.M):
            warn.append(f'{n}: 뼈대의 안내 글(괄호로 된 줄)이 남아 있습니다.')

    # 7. 틀: 사건을 더하는 동안 tools/ 가 바뀌면 안 된다
    conf = project / 'wiki.json'
    if conf.is_file():
        want = json.loads(conf.read_text(encoding='utf-8-sig')).get('tools_hash')
        if want and want != tools_hash(Path(__file__).resolve().parent):
            warn.append('tools/ 의 틀 파일이 위키를 만들 때와 다릅니다. 사건을 더하면서 틀을 고치지 않습니다. 일부러 올린 것이면 new_wiki.py --update-tools 로 다시 넣습니다.')

    # 8. 분량: 방송에서 소리 내 읽을 수 있는 길이
    main = [n for n, d in docs.items() if not d['rev']]
    per = len(main) / max(len(cases), 1)
    if cases and not 2 <= per <= 9:
        warn.append(f'문서가 사건 하나에 {per:.0f}개꼴입니다. 사건 문서에 합쳐 쓰고 따로 여는 문서는 서너 개가 보통입니다.')
    for n in main:
        size, cap = len(P[n]['본문']), MAX_START if n in first else MAX_BODY
        if size > cap:
            warn.append(f'{n}: 본문이 {size}자입니다. {cap}자 안으로 줄이거나 문서를 나눕니다.')
    if live:
        keep = lambda ms: [m for m in ms if any(k in m for k in LIVE_KEEP)]
        return keep(err), keep(warn)
    return err, warn


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):   # 콘솔 기본 인코딩(cp949)이면 에이전트가 읽을 때 깨진다
        o.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    err, warn = check(a[0] if a and not a[0].startswith('-') else Path(__file__).resolve().parent.parent, live='--live' in a)
    for e in err:
        print('오류 |', e)
    for w in warn:
        print('경고 |', w)
    print(f'\n오류 {len(err)}개, 경고 {len(warn)}개')
    sys.exit(1 if err else 0)
