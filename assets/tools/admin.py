#!/usr/bin/env python3
"""운영용 화면을 <프로젝트>/admin/ 에 만든다. 진상이 전부 들어 있으므로 공개 사이트와 함께 올리지 않는다.

사용법: python tools/admin.py [위키 폴더]
  admin/index.html  진실 페이지: 검사 결과, 사건별 진상·시간표·조각 표
  admin/*.html      조각 문장에 색이 칠해진 위키. 조각 표에서 누르면 그 문장으로 간다
"""
import sys, re, html, json
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).parent))
import build as B
from check import check, table, plain

KIND = {'진실': 'truth', '미끼': 'bait', '반박': 'rebut', '비공개': 'secret'}
STYLE = """
::highlight(truth){background:#1e5a2c}::highlight(bait){background:#6b4e00}::highlight(rebut){background:#17456e}
.pc{font-size:11px;line-height:1;border-radius:3px;padding:1px 5px;margin-left:3px;color:#fff!important;vertical-align:super;font-weight:700}
.truth{background:#2f9e44}.bait{background:#e67700}.rebut{background:#1971c2}.secret{background:#c92a2a}
.adm{position:sticky;top:0;z-index:9;background:#c92a2a;color:#fff;padding:6px 20px;font-size:14px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}
.adm a{color:#fff;text-decoration:underline}.adm .pc{vertical-align:baseline;margin:0}
tr.sec td{background:#2b1f1f}tr.bad td{background:#4a1f1f}.msg{margin:2px 0}.err{color:#c92a2a;font-weight:700}
"""
BANNER = ('<div class="adm"><b>운영용 화면</b><span>진상이 들어 있습니다. 공개하지 않습니다.</span><a href="index.html">진실 페이지</a>'
          '<span><span class="pc truth">진실</span> <span class="pc bait">미끼</span> <span class="pc rebut">반박</span></span></div>')
# 조각 문구를 화면에서 찾아 색칠하고 번호표를 붙인다. 문구가 링크나 굵은 글씨에 걸쳐 있어도 되게 글자 위치를 직접 센다.
JS = r"""
(function(){
const here=decodeURIComponent(location.pathname.split('/').pop()),mine=PIECES.filter(p=>p.file===here);
const main=document.querySelector('main');if(!mine.length||!main||!window.Highlight)return;
const w=document.createTreeWalker(main,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('.fn,.toc,.tabs,script,style')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
let s='',map=[],n,sp=true;
while(n=w.nextNode()){const t=n.nodeValue;for(let i=0;i<t.length;i++){const ws=/\s/.test(t[i]);if(ws&&sp)continue;s+=ws?' ':t[i];map.push([n,i]);sp=ws}}
const want=new URLSearchParams(location.hash.slice(1)).get('p'),found=[];
for(const p of mine){const q=p.phrase.replace(/\s+/g,' ').trim(),i=s.indexOf(q);if(i<0)continue;
  const r=new Range(),e=map[i+q.length-1];r.setStart(map[i][0],map[i][1]);r.setEnd(e[0],e[1]+1);found.push([p,r])}
for(const [p,r] of found){const h=CSS.highlights.get(p.kind)||new Highlight();h.add(r);CSS.highlights.set(p.kind,h)}
for(const [p,r] of found){const b=document.createElement('a');b.className='pc '+p.kind;b.textContent=p.id;b.title=p.what;b.href='index.html#'+encodeURIComponent(p.id);
  const c=r.cloneRange();c.collapse(false);c.insertNode(b);if(p.id===want)b.scrollIntoView({block:'center'})}
})();
"""


def main(project):
    project = Path(project); wiki = B.wiki_name(project); plan = project / 'plan'; docs = B.load(project)
    cases = [d for d in sorted(plan.iterdir()) if d.is_dir()]
    P = {n: dict(본문=plain(d['body_text']), 각주=plain('\n'.join(d['notes'])), 역사=plain(d['역사']), 토론=plain(d['토론'])) for n, d in docs.items()}
    e = html.escape

    pieces, sections = [], []
    for d in [plan] + cases:
        label = '' if d == plan else d.name + '/'
        rows = ''
        for r in table(d / 'pieces.md'):
            pid, kind, doc, where, phrase = label + r.get('번호', '?'), r.get('종류', ''), r.get('문서', ''), r.get('위치', '본문'), plain(r.get('문구', ''))
            if kind == '비공개':
                leak = [n for n in docs if phrase and phrase in ' '.join(P[n].values())]
                ok, state, place = not leak, ('새지 않음' if not leak else '샘: ' + ', '.join(leak)), '(문서에 없음)'
            else:
                ok = doc in docs and phrase in P[doc].get(where, '')
                file = B.fname(doc, where if where in ('토론', '역사') else '')
                pieces.append(dict(id=pid, kind=KIND.get(kind, 'truth'), file=file, phrase=phrase, what=r.get('내용', '')))
                state, place = ('있음' if ok else '없음'), f'<a href="{quote(file)}#p={quote(pid)}">{e(doc)}</a> · {e(where)}'
            rows += (f'<tr id="{e(pid)}" class="{"" if ok else "bad"}"><td><span class="pc {KIND.get(kind, "truth")}">{e(pid)}</span></td><td>{e(kind)}</td>'
                     f'<td>{e(r.get("단계", ""))}</td><td>{e(r.get("내용", ""))}</td><td>{place}</td><td>{e(r.get("문구", ""))}</td><td>{e(r.get("반박대상", ""))}</td><td>{e(r.get("안내", ""))}</td><td>{state}</td></tr>')
        times = ''.join(f'<tr class="{"sec" if r.get("공개") == "비공개" else ""}"><td>{e(r.get("시각", ""))}</td><td>{e(r.get("일", ""))}</td><td>{e(r.get("공개", ""))}</td></tr>'
                        for r in table(d / 'timeline.md'))
        truth = (d / 'truth.md').read_text(encoding='utf-8-sig').replace('\r\n', '\n') if (d / 'truth.md').is_file() else ''
        truth = re.sub(r'^#+ ', '### ', truth, flags=re.M)           # 진상 안의 제목은 전부 작은 제목으로
        extra = ''
        for f, title in (('names.md', '이름'), ('allow.md', '일부러 둔 예외')):
            if (d / f).is_file():
                extra += f'<h3>{title}</h3>' + B.render((d / f).read_text(encoding='utf-8-sig').replace('\r\n', '\n'), docs, project / 'docs' / 'img', project / 'admin' / 'img', False)
        sections.append(
            f'<h2>{e("세계 설계 (사건 사이)" if d == plan else d.name)}</h2>'
            + (B.render(truth, docs, project / 'docs' / 'img', project / 'admin' / 'img', False) if truth else '<p class="err">truth.md 없음</p>')
            + ('<h3>조각</h3><table class="t"><tr><th>번호</th><th>종류</th><th>단계</th><th>내용</th><th>자리</th><th>문구</th><th>반박대상</th><th>안내</th><th>상태</th></tr>' + rows + '</table>' if rows else '')
            + ('<h3>시간표</h3><table class="t"><tr><th>시각</th><th>일</th><th>공개</th></tr>' + times + '</table>' if times else '') + extra)

    data = json.dumps(pieces, ensure_ascii=False).replace('</', '<\\/')
    inject = f'<style>{STYLE}</style><script>const PIECES={data};{JS}</script>'
    # 배너는 스크립트로 맨 위에 끼운다 (build의 틀을 바꾸지 않으려고)
    inject += '<script>document.body.insertAdjacentHTML("afterbegin",' + json.dumps(BANNER, ensure_ascii=False) + ')</script>'
    site, n = B.build(project, wiki + ' 운영용', out='admin', inject=inject, ghost=True)

    err, warn = check(project)
    msgs = ''.join(f'<div class="msg err">오류 | {e(m)}</div>' for m in err) + ''.join(f'<div class="msg">경고 | {e(m)}</div>' for m in warn)
    start = B.start_doc(docs)
    (site / 'index.html').write_text(f"""<!doctype html><html lang="ko">{B.HEAD}
<title>진실 페이지 - {e(wiki)} 운영용</title><style>{B.CSS}{STYLE}main{{max-width:1300px}}</style>
{BANNER}<main><h1>진실 페이지</h1>
<p>조각 표의 "자리"를 누르면 위키에서 그 문장으로 갑니다. 위키 첫 화면: <a href="{quote(B.fname(start))}">{e(start)}</a></p>
<h2>검사 결과</h2>{msgs or '<p>오류와 경고가 없습니다.</p>'}
{''.join(sections)}</main></html>""", encoding='utf-8')
    return site, len(err), len(warn)


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):   # 콘솔 기본 인코딩(cp949)이면 에이전트가 읽을 때 깨진다
        o.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    site, ne, nw = main(a[0] if a and not a[0].startswith('-') else Path(__file__).resolve().parent.parent)
    print(f'운영용 화면 -> {site / "index.html"} (오류 {ne}개, 경고 {nw}개) 공개 사이트와 함께 올리지 않습니다.')
