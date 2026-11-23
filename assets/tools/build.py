#!/usr/bin/env python3
"""docs/*.md -> site/*.html (위키 모양의 정적 사이트). 표준 라이브러리만 쓴다.

사용법: python tools/build.py [위키 폴더] [--text] [--single]
  위키 이름은 wiki.json에서 읽는다.
  --text    새 독자 시험용 글 파일(reader_start_<문서>.txt, reader_all.txt)도 만든다.
  --single  위키 전체를 HTML 파일 하나(dist/<위키이름>.html)로도 묶는다. 남에게 보내거나 올릴 때 쓴다.
"""
from functools import lru_cache
import time
import difflib
import sys, re, html, json, shutil, unicodedata, os
from pathlib import Path
from urllib.parse import quote, unquote

LINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]*))?\]\]')
# 진짜처럼 보이는 가짜 사건 문서가 검색 결과에 뜨면 실제 사건으로 오해받는다. 검색 엔진이 가져가지 않게 한다.
HEAD = '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
# 한 파일로 묶었을 때 쪽 사이를 오가는 코드. 쪽 내용은 #pages 에 들어 있고 주소의 # 뒤가 쪽 이름이다.
ROUTER = r"""
const P=JSON.parse(document.getElementById('pages').textContent),M=document.querySelector('main');
function show(){let h=decodeURIComponent(location.hash.slice(2)),a='';const i=h.indexOf('#');if(i>=0){a=h.slice(i+1);h=h.slice(0,i)}
  if(!P[h])h=START;M.innerHTML=P[h].h;document.title=P[h].t+' - '+WIKI;
  if(h==='_none.html'){if(a)M.querySelector('h1').textContent=a;scrollTo(0,0);return}
  if(h==='_search.html'){wsearch(a);scrollTo(0,0);return}
  const el=a?document.getElementById(a):null;el?el.scrollIntoView():scrollTo(0,0)}
function go(u){location.hash='#/'+u}
document.addEventListener('click',e=>{const A=e.target.closest('a');if(!A)return;const u=A.getAttribute('href');if(!u||/^[a-z]+:/i.test(u))return;e.preventDefault();
  if(u[0]==='#'){history.replaceState(null,'','#/'+location.hash.slice(2).split('#')[0]+u);const el=document.getElementById(u.slice(1));el&&el.scrollIntoView()}else go(u)});
addEventListener('hashchange',show);show();
"""
# 본문 검색. 찾을 글은 주소의 # 뒤에 온다. 쪽마다 따로 있는 화면에서도, 한 파일로 묶은 화면에서도 같은 함수를 쓴다
SEARCH = r"""function wgo(f,mode){var q=f.q.value.trim();if(!q||wgo.b)return false;wgo.b=1;setTimeout(function(){wgo.b=0},600);
var T=JSON.parse(f.dataset.t||'{}');if(mode!=='s'&&T[q])go(T[q]);else if(mode==='d')go('_none.html#'+encodeURIComponent(q));else go('_search.html#'+encodeURIComponent(q));return false}
function wsug(i,off){var f=i.form,u=f.querySelector('.sug');if(!u)return;if(off){setTimeout(function(){u.hidden=true},150);return}
var q=i.value.trim();if(!q){u.hidden=true;return}var T=JSON.parse(f.dataset.t||'{}');
var K=Object.keys(T).filter(function(t){return t.indexOf(q)>=0}).sort(function(a,b){return(b.indexOf(q)===0)-(a.indexOf(q)===0)||a.length-b.length}).slice(0,10);
u.innerHTML=K.map(function(t){return'<li data-h="'+T[t]+'">'+t.replace(/[&<>"]/g,function(k){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[k]})+'</li>'}).join('');u.hidden=!K.length}
function wkey(e){if((e.key==='Enter'||e.keyCode===13)&&!e.isComposing){e.preventDefault();var f=e.target.form;f.classList.contains('sform')?wsub(f):wgo(f)}}
function wsub(f){var q=f.q.value.trim();if(!q||wgo.b)return false;wgo.b=1;setTimeout(function(){wgo.b=0},600);go('_search.html#'+(f.w.value?'w='+f.w.value+'&q=':'')+encodeURIComponent(q));return false}
function wsearch(a){var o=document.getElementById('sres');if(!o)return;var I=JSON.parse(document.getElementById('sidx').textContent),T=JSON.parse(document.getElementById('stitles').textContent);
var w='',q=a||'',m=/^w=([tx])&q=/.exec(q);if(m){w=m[1];q=decodeURIComponent(q.slice(6))}q=q.trim();
var F=document.getElementById('sform');if(F){F.q.value=q;F.w.value=w}
var g=document.getElementById('sgo'),c=document.getElementById('scount');if(!q){o.innerHTML='';g.hidden=true;c.textContent='';return}
var E=function(s){return s.replace(/[&<>"]/g,function(k){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[k]})};
var lit=function(s){var r='',i=0,k;while((k=s.indexOf(q,i))>=0){r+=E(s.slice(i,k))+'<mark>'+E(q)+'</mark>';i=k+q.length}return r+E(s.slice(i))};
g.hidden=false;g.innerHTML='<span>찾는 문서가 없나요? 문서로 바로 갈 수 있습니다.</span><a href="'+(T[q]||'_none.html#'+encodeURIComponent(q))+'">\''+E(q)+'\' 문서로 가기</a>';
var R=[];I.forEach(function(d){var inT=w!=='x'&&d.t.indexOf(q)>=0,n=0,k=-1;if(w!=='t')for(k=d.x.indexOf(q);k>=0;k=d.x.indexOf(q,k+q.length))n++;
if(!inT&&!n)return;R.push({d:d,s:(d.t===q?1e6:0)+(inT?1e5:0)+n})});R.sort(function(a,b){return b.s-a.s});
c.textContent='전체 '+R.length+' 건';var h='';
R.forEach(function(r){var d=r.d,i=d.x.indexOf(q),a0=i<0?0:Math.max(0,i-60),s=d.x.slice(a0,a0+260);
h+='<div class="sr"><h3><a href="'+d.h+'"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6 2h8l6 6v14H6zm8 1.5V9h5.5"/></svg>'+E(d.t)+'</a></h3><div class="snip">'+(a0?'… ':'')+lit(s)+(a0+260<d.x.length?' …':'')+'</div></div>'});
o.innerHTML=R.length?h:'<p class="none">\''+E(q)+'\'에 대한 검색 결과가 없습니다.</p>'}"""
NOTICE = '<div class="fic">창작물입니다. 실제 사건·인물과 관련이 없습니다.</div>'   # wiki.json 의 notice_top 이 true 일 때만 문서 위에 붙는다
# 처음 열 때 한 번 뜨는 안내. 문서 위에 늘 붙어 있으면 위키가 아니라 세트장처럼 보여서, 확인하면 그 브라우저에서는 다시 뜨지 않는 창으로 뺐다
ACK = """<div id="ack" hidden style="position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center">
<div style="background:#1c1d1f;color:#e0e0e0;border:1px solid #444;border-radius:8px;padding:22px 26px;max-width:440px;font-size:16px;line-height:1.6">
<b style="font-size:18px">이 위키는 창작물입니다</b><p style="margin:10px 0 16px">여기 실린 사건과 인물은 모두 지어낸 것입니다. 실제 지명이 나오지만 실제로 있었던 일이 아닙니다.</p>
<div style="text-align:right"><button id="ackb" style="font:inherit;border:0;border-radius:5px;padding:7px 18px;background:#2e3033;color:#fff;cursor:pointer">확인</button></div></div></div>
<script>(function(){var a=document.getElementById('ack'),k='wiki-ack';try{if(localStorage.getItem(k))return}catch(e){}a.hidden=false;
document.getElementById('ackb').onclick=function(){a.hidden=true;try{localStorage.setItem(k,'1')}catch(e){}}})();</script>"""
# 각주 번호에 마우스를 올리면 내용이 그 자리에 뜬다. 누르면 아래 각주로 간다.
TIP = """<script>(function(){var t;function A(e){return e.target.closest&&e.target.closest('a.fn')}
document.addEventListener('mouseover',function(e){var a=A(e);if(!a)return;var n=document.getElementById(a.getAttribute('href').slice(1));if(!n)return;
if(!t){t=document.createElement('div');t.className='fntip';document.body.appendChild(t)}
t.innerHTML=n.innerHTML;t.style.display='block';var r=a.getBoundingClientRect();
t.style.left=Math.max(8,Math.min(r.left,innerWidth-t.offsetWidth-8))+'px';t.style.top=(r.bottom+6+t.offsetHeight>innerHeight?r.top-t.offsetHeight-6:r.bottom+6)+'px'});
document.addEventListener('mouseout',function(e){if(t&&A(e))t.style.display='none'})})();</script>"""
DISCLAIMER = '이 위키에 실린 사건·인물·지명·단체는 모두 창작이며 실제와 관련이 없습니다.'

NAV = """<script>
// 문단 제목을 누르면 그 문단이 접힌다. 다시 누르면 펴진다
document.addEventListener('click',function(e){var h=e.target.closest&&e.target.closest('main h2,main h3');if(!h||e.target.closest('a,button'))return;
var lv=+h.tagName[1],on=h.classList.toggle('fold');for(var n=h.nextElementSibling;n;n=n.nextElementSibling){if(/^H[1-6]$/.test(n.tagName)&&+n.tagName[1]<=lv)break;if(n.classList.contains('notes')||n.id==='lvin')break;n.style.display=on?'none':''}});
// 최근 변경의 시각을 지금으로부터 얼마 전인지로 바꿔 보여 준다
function wago(){var now=Date.now()/1000;document.querySelectorAll('[data-ts]').forEach(function(s){var d=Math.max(0,Math.floor(now-(+s.dataset.ts)));
s.textContent=d<60?d+'초 전':d<3600?Math.floor(d/60)+'분 전':d<86400?Math.floor(d/3600)+'시간 전':Math.floor(d/86400)+'일 전'})}
// 문단마다 [편집]. 이 위키에서 읽는 사람이 문서를 고치는 길은 토론에 요청하는 것이다. 그리로 보낸다
function wedit(){var on=document.querySelector('main .btns a.on'),talk=document.querySelector('main .btns a:nth-child(2)');if(!on||!talk||on!==document.querySelector('main .btns a:first-child'))return;
document.querySelectorAll('main h2,main h3').forEach(function(h){if(h.querySelector('.ed')||!h.id)return;var a=document.createElement('a');a.className='ed';a.href=talk.getAttribute('href');a.textContent='[편집]';a.title='토론에서 편집을 요청합니다';h.appendChild(a)})}
wago();wedit();setInterval(function(){wago();wedit()},3000);
</script><nav class="read-nav" aria-label="문서 이동">
<button type="button" id="readtoc" aria-label="목차 열기" title="목차" aria-expanded="false" aria-controls="readpanel">☷</button>
<button type="button" id="readtop" aria-label="맨 위로" title="맨 위로">↑</button>
<button type="button" id="readbottom" aria-label="맨 아래로" title="맨 아래로">↓</button></nav>
<nav class="read-panel card" id="readpanel" aria-label="문서 목차" hidden><div class="ch">목차</div><div class="contents"></div></nav>
<script>(function(){
const main=document.querySelector('main'),button=document.getElementById('readtoc'),panel=document.getElementById('readpanel');
if(!main)return;let signature='',headings=[],scheduled=false;
const close=()=>{panel.hidden=true;button.setAttribute('aria-expanded','false')};
button.onclick=()=>{panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden))};
document.getElementById('readtop').onclick=()=>window.scrollTo(0,0);
document.getElementById('readbottom').onclick=()=>window.scrollTo(0,document.documentElement.scrollHeight);
panel.addEventListener('click',e=>{if(e.target.closest('a'))close()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){close();button.focus()}});
document.addEventListener('click',e=>{if(!panel.contains(e.target)&&!button.contains(e.target))close()});
function active(){scheduled=false;let id=headings[0]?.id;for(const h of headings){if(h.getBoundingClientRect().top<=110)id=h.id}
  if(scrollY+innerHeight>=document.documentElement.scrollHeight-2)id=headings.at(-1)?.id;
  for(const a of document.querySelectorAll('.side-toc a,.read-panel a')){const on=a.getAttribute('href')==='#'+id;a.classList.toggle('active',on);if(on)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current')}}
function update(){headings=[...main.querySelectorAll('h2[id^="s"],h3[id^="s"]')];
  const next=JSON.stringify(headings.map(h=>[h.id,h.textContent,h.tagName]));if(next===signature)return;signature=next;
  const content=document.createElement('div');for(const h of headings){const a=document.createElement('a');a.href='#'+h.id;a.textContent=h.textContent;if(h.tagName==='H3')a.className='sub';content.appendChild(a)}
  panel.querySelector('.contents').replaceChildren(...[...content.childNodes].map(n=>n.cloneNode(true)));button.disabled=!headings.length;if(!headings.length)close();
  const aside=document.querySelector('aside');if(aside){let card=aside.querySelector('.side-toc');if(!card){card=document.createElement('nav');card.className='card side-toc';card.setAttribute('aria-label','목차');card.innerHTML='<div class="ch">목차</div><div class="contents"></div>';aside.prepend(card)}card.hidden=!headings.length;card.querySelector('.contents').replaceChildren(content)}active()}
new MutationObserver(update).observe(main,{childList:true,subtree:true});
const aside=document.querySelector('aside');if(aside)new MutationObserver(()=>{signature='';update()}).observe(aside,{childList:true});
addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(active)}},{passive:true});update();
})();</script>"""


def pull_notes(text):
    """[^각주 내용]을 본문에서 빼낸다. 각주 안에 [[링크]]가 있어도 되게 괄호 짝을 센다."""
    out, notes, i = [], [], 0
    while (j := text.find('[^', i)) >= 0:
        depth, k = 1, j + 2
        while k < len(text) and depth:
            depth += (text[k] == '[') - (text[k] == ']'); k += 1
        if depth:
            raise ValueError('닫히지 않은 각주: ' + text[j:j + 40].replace('\n', ' '))
        notes.append(text[j + 2:k - 1]); out.append(text[i:j] + f'\x00{len(notes)}\x00'); i = k
    return ''.join(out) + text[i:], notes


def parse(stem, text, where=''):
    """문서 글 하나를 읽는다."""
    text = text.replace('\r\n', '\n'); meta = {}
    if m := re.match(r'---\n(.*?)\n---\n', text, re.S):
        for line in m[1].splitlines():
            if ':' in line:
                k, v = line.split(':', 1); meta[k.strip()] = v.strip()
        text = text[m.end():]
    parts = re.split(r'^---(역사|토론)---[ \t]*$', text, flags=re.M)
    d = dict(name=stem, meta=meta, body=parts[0], 역사='', 토론='')
    d.update(zip(parts[1::2], parts[2::2]))
    try:
        d['body_text'], d['notes'] = pull_notes(d['body'])
    except ValueError as e:
        sys.exit(f'{where or stem}: {e}')
    d['history'] = [[c.strip() for c in l.split('|', 4)] for l in d['역사'].splitlines() if l.count('|') >= 4]
    d['base'], _, d['rev'] = stem.partition('@')
    return d


def load(project):
    """docs/*.md를 읽어 {파일이름(확장자 제외): 문서} 로 돌려준다.
    history/ 가 있으면(라이브 화면이 남긴 실제 편집 기록) 역사 탭과 최근 수정 시각, 이전 판을 거기서 가져온다."""
    docs = {p.stem: parse(p.stem, p.read_text(encoding='utf-8-sig'), p.name) for p in sorted(Path(project, 'docs').glob('*.md'))}
    hdir = Path(project, 'history')
    if (hdir / 'revs.json').is_file():
        for n, rows in json.loads((hdir / 'revs.json').read_text(encoding='utf-8-sig')).items():
            if n not in docs or not rows:
                continue
            d = docs[n]
            d['history'] = [[r['rev'], r['time'], r.get('editor') or '익명', f'{r.get("delta", 0):+d}', r.get('summary', '')] for r in reversed(rows)]
            d['역사'] = '\n'.join(' | '.join(r) for r in d['history'])
            d['meta']['modified'] = rows[-1]['time']
            for r in rows[:-1]:                     # 마지막 판은 지금 문서 그 자체다
                p = hdir / n.replace(' ', '_') / f'{r["rev"]}.md'
                if p.is_file():
                    stem = f'{n}@{r["rev"]}'; docs[stem] = parse(stem, p.read_text(encoding='utf-8-sig'))
    return docs


def wiki_name(project):
    f = Path(project, 'wiki.json')
    return json.loads(f.read_text(encoding='utf-8-sig')).get('name', '위키') if f.is_file() else '위키'


def starts(docs):
    """시작 문서들. 사건이 여러 개면 사건마다 하나씩 있다."""
    return [n for n, d in docs.items() if d['meta'].get('start') == 'true'] or [next(iter(docs))]


def start_doc(docs):
    """사이트 첫 화면. '대문' 문서가 있으면 그것, 없으면 첫 시작 문서."""
    return '대문' if '대문' in docs else starts(docs)[0]


def fname(name, tab=''):
    return name.replace(' ', '_') + (f'.{tab}' if tab else '') + '.html'


def talk_html(text, docs, inline_render):
    """토론을 나무위키의 토론 화면처럼 그린다. 맨 위에 주제 목록, 그 아래 주제마다 번호가 붙은 글 상자(#1 닉네임 … 시각).
    글은 `## 주제` 아래 `**닉네임** (시각): 내용` 꼴로 적혀 있다. 그 꼴이 아닌 줄은 앞 글에 이어 붙인다."""
    threads = []
    for line in text.split('\n'):
        line = line.rstrip()
        if m := re.match(r'##+ (.+)', line):
            threads.append((m[1], []))
        elif m := re.match(r'\*\*(.+?)\*\*\s*\((.+?)\)\s*[:：]\s*(.*)', line):
            if not threads:
                threads.append(('토론', []))
            threads[-1][1].append([m[1], m[2], m[3]])
        elif line.strip() and threads and threads[-1][1]:
            threads[-1][1][-1][2] += '\n' + line.strip()
    if not any(c for _, c in threads):
        return ''
    e = html.escape
    out = ['<h2>토론</h2><ul>' + ''.join(f'<li><a href="#t{k}">{k}. {e(t)}</a></li>' for k, (t, _) in enumerate(threads, 1)) + '</ul>']
    for k, (t, cs) in enumerate(threads, 1):
        out.append(f'<h2 id="t{k}" class="tt">{k}. {e(t)}</h2>')
        for i, (who, when, body) in enumerate(cs, 1):
            out.append(f'<div class="cm"><div class="cmh"><span>#{i} <b>{e(who)}</b></span><span>{e(when)}</span></div>'
                       f'<div class="cmb">{"<br>".join(inline_render(x) for x in body.split(chr(10)))}</div></div>')
    return ''.join(out)


INK, PAPER, RED = '#2b2b2b', '#f3efe4', '#b3261e'
SVG_HEAD = 'xmlns="http://www.w3.org/2000/svg" font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif"'


def draw_map(rows):
    """약도를 그린다. 문서에는 무엇이 어디에 있는지만 적혀 있고(미터 단위 좌표, 위가 북쪽), 선과 색과 글자는 여기서 정한다.
    글자가 겹치면 글자만 옮기고, 지점과 건물의 좌표는 그대로 둔다."""
    W, H, items = 80.0, 60.0, []
    for r in rows:
        c = [x.strip() for x in r.split('|')]
        try:
            if c[0] == '크기':
                W, H = (float(x) for x in c[1].split()[:2])
            elif len(c) >= 3:
                items.append((c[0], c[1], [float(x) for x in c[2].split()], float(c[3]) if len(c) > 3 and c[3] else 4.0))
        except ValueError:
            continue
    k = 640 / max(W, 1); e = html.escape
    labels, occupied = [], [(620, -24, 660, 40)]
    for t, _, n, _ in items:
        if t == '점' and len(n) >= 2:
            x, y = n[0] * k, n[1] * k
            occupied.append((x - 6.5, y - 6.5, x + 6.5, y + 6.5))
    pts = lambda n: ' '.join(f'{n[i] * k:.1f},{n[i + 1] * k:.1f}' for i in range(0, len(n) - 1, 2))
    o = [f'<svg viewBox="-24 -24 688 {H * k + 64:.0f}" {SVG_HEAD} font-size="14"><rect x="-24" y="-24" width="688" height="{H * k + 64:.0f}" fill="{PAPER}"/>',
         f'<defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="{RED}"/></marker></defs>']
    for kind in ('길', '터', '건물', '동선', '점'):
        for t, name, n, w in items:
            if t != kind or len(n) < 2:
                continue
            if t == '길' and len(n) >= 4:
                o.append(f'<polyline points="{pts(n)}" fill="none" stroke="#d3ccb8" stroke-width="{max(w * k, 6):.1f}" stroke-linecap="round" stroke-linejoin="round"/>')
                half = max(w * k, 6) / 2; mx, my = (n[0] + n[2]) / 2 * k, (n[1] + n[3]) / 2 * k      # 길 이름은 길 위가 아니라 옆에 적는다. 동선과 겹치지 않게
                if abs(n[2] - n[0]) >= abs(n[3] - n[1]):
                    labels.append((name, mx, my - half - 7, 'middle', '#6b6455', False, t))
                else:
                    labels.append((name, mx + half + 8, my + 5, 'start', '#6b6455', False, t))
            elif t in ('건물', '터') and len(n) >= 4:
                look = f'fill="#e2dccb" stroke="{INK}" stroke-width="1.6"' if t == '건물' else 'fill="none" stroke="#777" stroke-width="1.2" stroke-dasharray="5 4"'
                o.append(f'<rect x="{n[0] * k:.1f}" y="{n[1] * k:.1f}" width="{n[2] * k:.1f}" height="{n[3] * k:.1f}" {look}/>')
                y = n[1] * k + 22 if t == '터' else (n[1] + n[3] / 2) * k + 5
                labels.append((name, (n[0] + n[2] / 2) * k, y, 'middle', INK, False, t))
            elif t == '동선' and len(n) >= 4:
                o.append(f'<polyline points="{pts(n)}" fill="none" stroke="{RED}" stroke-width="2" stroke-dasharray="7 5" marker-end="url(#ah)"/>')
                labels.append((name, n[0] * k + 8, n[1] * k - 10, 'start', RED, False, t))
            elif t == '점':
                o.append(f'<circle cx="{n[0] * k:.1f}" cy="{n[1] * k:.1f}" r="5.5" fill="{RED}" stroke="#fff" stroke-width="1.5"/>')
                labels.append((name, n[0] * k + 12, n[1] * k + 5, 'start', RED, True, t))
    # SVG를 파일 하나로 내보내도 같은 배치가 되도록 글자 폭을 보수적으로 잡는다.
    labels.sort(key=lambda label: ('건물', '터', '점', '길', '동선').index(label[-1]))
    for name, x, y, anchor, color, bold, _ in labels:
        width = sum(16 if unicodedata.east_asian_width(c) in 'WF' else 10 for c in name)
        left = x - width / 2 if anchor == 'middle' else x
        choices = []
        for step in range(11):
            for dy in ((0,) if step == 0 else (-24 * step, 24 * step)):
                for dx in (0, -12, 12, -width - 24, width + 24):
                    lx = max(-16, min(left + dx, 656 - width))
                    ly = max(0, min(y + dy, H * k))
                    box = (lx - 1.5, ly - 17, lx + width + 1.5, ly + 5)
                    overlap = sum(max(0, min(box[2], b[2]) - max(box[0], b[0])) *
                                  max(0, min(box[3], b[3]) - max(box[1], b[1])) for b in occupied)
                    choices.append((overlap, abs(lx - left) + abs(ly - y), lx, ly, box))
        _, _, lx, ly, box = min(choices)
        occupied.append(box)
        if abs(lx - left) + abs(ly - y) > 18:
            ax = x - 12 if bold else x
            o.append(f'<path d="M{ax:.1f} {y - 5:.1f}L{max(lx, min(ax, lx + width)):.1f} {ly - 7:.1f}" fill="none" stroke="{color}" stroke-width=".8"/>')
        o.append(f'<text class="map-label" x="{lx:.1f}" y="{ly:.1f}" fill="{color}" font-size="16" font-weight="{700 if bold else 400}" '
                 f'stroke="{PAPER}" stroke-width="3" stroke-linejoin="round" paint-order="stroke">{e(name)}</text>')
    unit = min((5, 10, 20, 50, 100, 200, 500, 1000), key=lambda u: abs(u - W / 5)); y = H * k + 22
    o.append(f'<path d="M0 {y - 5}V{y}H{unit * k:.1f}V{y - 5}" fill="none" stroke="{INK}" stroke-width="1.4"/><text x="{unit * k + 8:.1f}" y="{y + 4}" fill="{INK}" font-size="12">{unit}m</text>')
    o.append(f'<path d="M640 14V-12M634 -4L640 -14L646 -4" fill="none" stroke="{INK}" stroke-width="1.6"/><text x="640" y="30" text-anchor="middle" fill="{INK}" font-size="12">북</text></svg>')
    return ''.join(o)


def draw_times(rows):
    """시간표를 그린다. 누가 언제 어디에 있었는지를 가로 막대로 보여 준다. 끝 시각이 ? 이면 그 뒤를 알 수 없다는 뜻으로 흐려진다.
    시각은 HH:MM 이고, 자정을 넘기면 25:30 처럼 이어 적는다."""
    def mins(t):
        h, _, m = t.partition(':'); return int(h) * 60 + int(m or 0)
    span, bars = None, []
    for r in rows:
        c = [x.strip() for x in r.split('|')]
        try:
            if c[0] == '범위':
                span = (mins(c[1]), mins(c[2]))
            elif len(c) >= 3:
                bars.append((c[0], mins(c[1]), None if c[2] in ('?', '') else mins(c[2]), c[3] if len(c) > 3 else ''))
        except (ValueError, IndexError):
            continue
    if not bars:
        return ''
    a, b = span or (min(x[1] for x in bars), max(x[2] or x[1] + 60 for x in bars))
    names = list(dict.fromkeys(x[0] for x in bars)); L, CW, RH = 120, 520, 38; e = html.escape
    X = lambda t: L + (min(max(t, a), b) - a) / max(b - a, 1) * CW
    step = 30 if b - a <= 240 else 60 if b - a <= 720 else 120
    Hh = len(names) * RH + 46; colors = ('#8aa0b8', '#b89a7a', '#93ad8c', '#b28fa8', '#a8a27c')
    o = [f'<svg viewBox="0 0 {L + CW + 30} {Hh}" {SVG_HEAD} font-size="13"><rect width="{L + CW + 30}" height="{Hh}" fill="{PAPER}"/>',
         '<defs><linearGradient id="fade"><stop offset="0" stop-color="#999"/><stop offset="1" stop-color="#999" stop-opacity="0"/></linearGradient></defs>']
    t = (a + step - 1) // step * step
    while t <= b:
        o.append(f'<path d="M{X(t):.1f} 26V{Hh - 10}" stroke="#d3ccb8"/><text x="{X(t):.1f}" y="18" text-anchor="middle" fill="#6b6455" font-size="12">{t // 60 % 24:02d}:{t % 60:02d}</text>'); t += step
    for i, n in enumerate(names):
        y = 34 + i * RH
        o.append(f'<text x="{L - 10}" y="{y + 17}" text-anchor="end" fill="{INK}" font-weight="700">{e(n)}</text>')
        for name, s, f, label in bars:
            if name != n:
                continue
            x1, x2 = X(s), X(b if f is None else f)
            fill = 'url(#fade)' if f is None else colors[i % len(colors)]
            o.append(f'<rect x="{x1:.1f}" y="{y}" width="{max(x2 - x1, 3):.1f}" height="24" rx="3" fill="{fill}"/>')
            o.append(f'<text x="{x1 + 6:.1f}" y="{y + 17}" fill="{INK}">{e(label)}{" ?" if f is None else ""}</text>')
    return ''.join(o) + '</svg>'


def pub_name(folder, f):
    """문서가 가리키는 사진 이름(x.png) -> 실제로 있는 공개 사진 이름. 줄여 둔 x.jpg 가 있으면 그것."""
    j = Path(f).with_suffix('.jpg').name
    return f if (Path(folder) / f).is_file() or not (Path(folder) / j).is_file() else j


def place(src, dst):
    """화면용 사이트에 사진을 둔다. 같은 디스크면 하드링크라 용량이 늘지 않는다. 안 되면 복사."""
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def render(text, docs, img_src, img_out, numbered=True, ghost=False):
    text, notes = pull_notes(text)

    def link(m):
        t = html.unescape(m[1]).strip(); label = m[2] or m[1]
        if t in docs:
            return f'<a href="{quote(fname(t))}">{label}</a>'
        return f'<a class="new" href="_none.html#{quote(t)}">{label}</a>'

    def inline(s):
        s = html.escape(s, quote=False)
        s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s); s = re.sub(r'~~(.+?)~~', r'<del>\1</del>', s)
        s = LINK.sub(link, s)
        return re.sub('\x00(\\d+)\x00', r'<a class="fn" id="r\1" href="#fn\1">[\1]</a>', s)

    H, toc, nums, para = [], [], [0, 0], []
    lines, i = text.split('\n'), 0

    def flush():
        if para:
            H.append('<p>' + inline(' '.join(para)) + '</p>'); para.clear()

    def take(prefix):
        nonlocal i
        got = [lines[i - 1][len(prefix):]]
        while i < len(lines) and lines[i].startswith(prefix):
            got.append(lines[i][len(prefix):]); i += 1
        return got

    while i < len(lines):
        l = lines[i].rstrip(); i += 1
        if m := re.match(r'(##+) (.+)', l):
            flush(); lv = min(len(m[1]), 3)
            if lv == 2:
                nums[0] += 1; nums[1] = 0; n = f'{nums[0]}.'
            else:
                nums[1] += 1; n = f'{nums[0]}.{nums[1]}.'
            toc.append((lv, n, m[2]))
            H.append(f'<h{lv} id="s{len(toc)}">' + (f'<a href="#toc">{n}</a> ' if numbered else '') + inline(m[2]) + f'</h{lv}>')
        elif l.startswith(':::'):
            flush(); rows = []; head = l[3:].strip()
            while i < len(lines) and not lines[i].startswith(':::'):
                rows.append(lines[i].strip()); i += 1
            i += 1
            if head.startswith('자료'):      # 녹취록, 문자, 메모, 기사처럼 원문을 그대로 옮긴 상자. 줄바꿈을 살린다
                title = head[2:].strip()
                H.append('<blockquote>' + '<br>'.join(inline(r) for r in rows)
                         + (f'<hr><div class="qs">{inline(title)}</div>' if title else '') + '</blockquote>')
                continue
            if head.startswith('대화'):      # 대화방, 채팅, 문자. 문서에는 누가 언제 뭐라고 했는지만 적고 화면 모양은 틀이 그린다
                title = head[2:].strip(); out = []
                for r in rows:
                    c = [x.strip() for x in r.split('|', 2)]
                    if len(c) == 3 and c[2]:
                        out.append(f'<div class="cm"><span class="cn">{inline(c[0])}</span><span class="cb">{inline(c[2])}</span><span class="ct">{inline(c[1])}</span></div>')
                H.append('<figure class="chat">' + (f'<div class="ch">{inline(title)}</div>' if title else '') + ''.join(out) + '</figure>')
                continue
            if head.startswith(('약도', '시간표')):      # 문서에는 내용만 적고 그림은 틀이 그린다
                svg = draw_map(rows) if head.startswith('약도') else draw_times(rows)
                title = head[2 if head.startswith('약도') else 3:].strip()
                if svg:
                    H.append(f'<figure class="map">{svg}' + (f'<figcaption>{inline(title)}</figcaption>' if title else '') + '</figure>')
                continue
            if head.startswith('도면'):      # 예전 방식. 안에 SVG를 그대로 쓴다. 새로 쓰는 문서는 약도와 시간표를 쓴다
                svg = re.sub(r'(?is)<script.*?</script>|\son\w+\s*=\s*("[^"]*"|\'[^\']*\')', '', '\n'.join(rows))
                title = head[2:].strip()
                H.append(f'<figure class="map">{svg}' + (f'<figcaption>{inline(title)}</figcaption>' if title else '') + '</figure>')
                continue
            cells = [r.split('|', 1) for r in rows if r]
            H.append('<table class="info">' + ''.join(
                f'<tr><th>{inline(c[0].strip())}</th><td>{inline(c[1].strip())}</td></tr>' if len(c) == 2
                else f'<tr><th colspan="2" class="cap">{inline(c[0])}</th></tr>' for c in cells) + '</table>')
        elif l.startswith('|'):
            flush(); i -= 1; rows = []
            while i < len(lines) and lines[i].startswith('|'):
                rows.append(lines[i].strip()); i += 1
            rows = [[c.strip() for c in r.strip('|').split('|')] for r in rows if not re.fullmatch(r'[|\-: ]+', r)]
            H.append('<div class="table-wrap"><table class="t">' + ''.join('<tr>' + ''.join(
                f'<th>{inline(c)}</th>' if k == 0 else f'<td>{inline(c)}</td>' for c in r) + '</tr>' for k, r in enumerate(rows)) + '</table></div>')
        elif l.startswith('- '):
            flush(); H.append('<ul>' + ''.join(f'<li>{inline(x)}</li>' for x in take('- ')) + '</ul>')
        elif l.startswith('> '):
            flush(); H.append('<blockquote>' + '<br>'.join(inline(x) for x in take('> ')) + '</blockquote>')
        elif m := re.fullmatch(r'!\[(.*?)\]\((.+?)\)', l):
            flush(); src = Path(img_src, pub_name(img_src, m[2]))
            if src.is_file():
                img_out.mkdir(exist_ok=True); dst = img_out / src.name
                if not dst.is_file() or (dst.stat().st_size, int(dst.stat().st_mtime)) != (src.stat().st_size, int(src.stat().st_mtime)):
                    place(src, dst)      # 바뀐 사진만 옮긴다. 라이브 화면은 편집마다 화면을 다시 만든다
                size = b''
                try:
                    with open(src, 'rb') as fh:
                        size = fh.read(24)
                except OSError:
                    pass
                dims = (f' width="{int.from_bytes(size[16:20], "big")}" height="{int.from_bytes(size[20:24], "big")}"' if size[:8] == b'\x89PNG\r\n\x1a\n' else '')
                pic = f'<a href="{quote(fname("파일." + Path(m[2]).name))}" title="파일:{html.escape(Path(m[2]).name)}"><img src="img/{quote(src.name)}" alt=""{dims}></a>'
            elif ghost:
                pic = '<div class="noimg">사진 자리 (아직 없음)</div>'
            else:
                continue                  # 사진이 채워지기 전에는 자리째로 보이지 않는다
            H.append(f'<figure class="photo">{pic}<figcaption>{inline(m[1])}</figcaption></figure>')
        elif not l:
            flush()
        else:
            para.append(l.strip())
    flush()
    grouped, photos = [], []
    for block in H + ['']:
        if block.startswith('<figure class="photo">'):
            photos.append(block)
            continue
        if photos:
            grouped.append('<div class="media' + (' gallery' if len(photos) > 1 else '') + '">' + ''.join(photos) + '</div>')
            photos.clear()
        if block:
            grouped.append(block)
    H = grouped
    if numbered and toc:
        first_h = next(j for j, block in enumerate(H) if re.match(r'<h[23]\b', block))
        clean = lambda t: html.escape(re.sub(r'[\[\]*~]', '', t))
        box = '<nav class="toc" id="toc" aria-label="목차"><b>목차</b><div class="toc-items">' + ''.join(
            f'<div class="l{lv}"><a href="#s{k + 1}">{n} {clean(t)}</a></div>' for k, (lv, n, t) in enumerate(toc)) + '</div></nav>'
        if first_h == 1 and H[0].startswith('<table class="info">'):
            end = next((j for j in range(first_h + 1, len(H)) if re.match(r'<h[23]\b', H[j])), len(H))
            H[:end] = ['<div class="article-lead"><div class="lead-copy">' + '\n'.join(H[first_h:end]) +
                       '</div><div class="lead-info">' + H[0] + '</div></div>', box]
        else:
            H.insert(first_h, box)
    if notes:
        H.append('<div class="notes">' + ''.join(
            f'<p id="fn{k}"><a href="#r{k}">[{k}]</a> {inline(n)}</p>' for k, n in enumerate(notes, 1)) + '</div>')
    return '\n'.join(H)


@lru_cache(maxsize=4096)      # 지난 판은 바뀌지 않는다. 라이브 화면이 편집마다 화면을 다시 만들 때 같은 비교를 되풀이하지 않게
def diff_html(a, b):
    """두 판의 원문을 줄 단위로 견주어 표로 그린다. 바뀐 줄 안에서는 바뀐 글자만 짙게 칠한다. 안 바뀐 곳은 바뀐 곳 바로 앞뒤 한 줄만 보인다."""
    e = html.escape; A, B = a.splitlines(), b.splitlines(); out = []
    row = lambda cls, sign, text: out.append(f'<tr class="{cls}"><th>{sign}</th><td>{text or "&nbsp;"}</td></tr>')

    def inline(x, y):
        l = r = ''
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
            if op == 'equal':
                l += e(x[i1:i2]); r += e(y[j1:j2])
            else:
                l += f'<del>{e(x[i1:i2])}</del>' if i2 > i1 else ''; r += f'<ins>{e(y[j1:j2])}</ins>' if j2 > j1 else ''
        return l, r
    ops = difflib.SequenceMatcher(None, A, B, autojunk=False).get_opcodes()
    for k, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == 'equal':
            same = [x for x in A[i1:i2] if x.strip()]
            head = same[:1] if k else []; tail = same[-1:] if k < len(ops) - 1 and len(same) > len(head) else []
            for x in head:
                row('dc', '', e(x))
            if len(same) > len(head) + len(tail):
                row('dc', '', '<span class="mute">⋯</span>')
            for x in tail:
                row('dc', '', e(x))
            continue
        n = min(i2 - i1, j2 - j1) if op == 'replace' else 0
        for d in range(n):
            l, r = inline(A[i1 + d], B[j1 + d]); row('dd', '−', l); row('da', '+', r)
        for x in A[i1 + n:i2]:
            row('dd', '−', e(x))
        for x in B[j1 + n:j2]:
            row('da', '+', e(x))
    return '<table class="diff">' + ''.join(out) + '</table>' if out else '<p>두 판의 내용이 같습니다.</p>'


def plain_inline(docs):
    """토론 글 한 줄을 그리는 함수를 돌려준다(링크, 굵게, 취소선만)."""
    def link(m):
        t = html.unescape(m[1]).strip(); label = m[2] or m[1]
        return f'<a href="{quote(fname(t))}">{label}</a>' if t in docs else f'<a class="new" href="_none.html#{quote(t)}">{label}</a>'

    def one(x):
        x = html.escape(x, quote=False)
        x = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', x); x = re.sub(r'~~(.+?)~~', r'<del>\1</del>', x)
        return LINK.sub(link, x)
    return one


def rules(year):
    """대문의 주요 운영 알림. 실제 위키의 운영 공지처럼 날짜와 규정 이름이 들어간 무미건조한 글로 쓴다.
    짧은 문장을 짝지은 구호 같은 말은 쓰지 않는다. wiki.json 의 rules 로 바꿀 수 있다."""
    return [f'{year}년 제1회 운영 회의의 합의에 따라 사건 문서의 인물 표기 기준이 정해졌습니다. 공인이 아닌 사건 관계자는 성과 직함, 또는 A씨와 같은 가명으로 적으며, 이미 실명으로 적힌 서술은 발견하는 대로 고쳐 주시기 바랍니다.',
            '사건 관계자나 유족의 요청으로 임시 조치된 서술은 해당 문서의 역사에서 조치 이전 판으로 확인할 수 있습니다. 임시 조치에 대한 이의는 그 문서의 토론에 남겨 주십시오.',
            '출처가 확인되지 않는 추정을 본문에 적는 일이 잦아, 수사 기관의 발표나 보도로 확인되지 않은 내용은 토론에서 먼저 다루도록 편집 지침에 명시하였습니다.',
            '이 위키의 문서는 검색 엔진에 수집되지 않도록 설정되어 있습니다.']


def ops_records(project, docs):
    """<위키 이름>:처리 내역. 서버에 이미 남은 기록(진상 봉인, 종결 의견 검토, 해설 공개, 임시 조치)으로 쓴다. 지어내는 것은 없다.
    나무위키의 처리 내역처럼 사건이 쌓일수록 자란다."""
    project = Path(project)

    def rd(p, d):
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return d

    def title(c):
        f = c / 'truth.md'
        m = re.search(r'^## 사건 문서 이름[ \t]*\n(.+)', f.read_text(encoding='utf-8') if f.is_file() else '', re.M)
        t = m.group(1).strip() if m else ''
        return f'[[{t}]]' if t in docs else (t or c.name)
    seal = rd(project / '.live' / 'seal.json', {})
    cases = sorted((c for c in (project / 'plan').glob('*') if c.is_dir()), key=lambda c: c.stat().st_ctime)
    lock, verdict = [], []
    for c in cases:
        day = time.strftime('%Y-%m-%d', time.localtime(c.stat().st_ctime))
        if c.name in seal:
            lock.append((f'{day} {seal[c.name].get("time", "")}', title(c), seal[c.name].get('hash', '')))
        for a in rd(project / '.live' / 'cases' / c.name / 'attempts.json', []):
            verdict.append((a.get('time', ''), title(c), '정답 인정' if a.get('accepted') else a.get('result') or '검토'))
        st = c / 'state.json'
        if rd(st, {}).get('revealed'):
            verdict.append((time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.stat().st_mtime)), title(c), '전말 공개'))
    gone = [(n, d['meta']['deleted']) for n, d in docs.items() if not d['rev'] and d['meta'].get('deleted')]

    def table(head, rows):
        return '| ' + ' | '.join(head) + ' |\n' + '\n'.join('| ' + ' | '.join(str(x).replace('|', '/') for x in r) + ' |' for r in rows)
    return ('이 문서는 이 위키의 운영 처리 내역입니다. 기록은 처리된 순서대로 자동으로 남습니다.\n\n'
            '## 기록 잠금\n사건의 기록이 모두 모여 진상이 확정되면 그 사건의 기록을 잠급니다. 지문은 잠근 시점의 진상 기록에서 계산한 값으로, 이후 진상이 바뀌지 않았음을 확인하는 데 씁니다.\n\n'
            + (table(('일시', '사건 문서', '처리', '지문'), [(t, n, '진상 확정 · 기록 잠금', h) for t, n, h in reversed(lock)]) if lock else '아직 잠긴 기록이 없습니다.')
            + '\n\n## 종결 의견\n추리 제출로 들어온 종결 의견의 검토 결과와 전말 공개 내역입니다.\n\n'
            + (table(('일시', '사건 문서', '결과'), sorted(verdict, reverse=True)) if verdict else '아직 처리된 종결 의견이 없습니다.')
            + '\n\n## 임시 조치\n사건 관계자나 유족의 요청으로 조치된 문서입니다.\n\n'
            + (table(('문서', '사유'), [(f'[[{n}]]', r) for n, r in gone]) if gone else '조치된 문서가 없습니다.'))


def staff(year, day, season=None):
    """<위키 이름>:운영진. 장식 문서다. 시즌을 열 때 에이전트가 정한 운영진과 회의 합의를 싣고, 없으면 기본 넷을 싣는다."""
    season = season or {}
    people = [p for p in season.get('staff') or [] if isinstance(p, dict) and p.get('nick')]
    meet = [m for m in season.get('meeting') or [] if isinstance(m, str) and m.strip()]
    one = lambda t: str(t).replace('\n', ' ').replace('|', '/')
    if people and meet:
        return ('이 문서는 이 위키의 운영진과 운영 회의 내역입니다.\n\n## 운영진\n운영진도 사건의 진상을 알지 못합니다.\n\n| 닉네임 | 권한 | 선임일 | 비고 |\n'
                + '\n'.join(f"| {one(p['nick'])} | {one(p.get('role', ''))} | {day} | {one(p.get('note', ''))} |" for p in people)
                + f'\n\n## 운영 회의\n### 제1회 운영 회의\n{year}년, 위키 개설과 함께 열렸습니다. 합의 사항은 다음과 같습니다.\n'
                + '\n'.join('- ' + one(m) for m in meet) + '\n\n처리된 일은 처리 내역 문서에서 볼 수 있습니다.')
    return ('이 문서는 이 위키의 운영진과 운영 회의 내역입니다.\n\n'
            '## 운영진\n운영진은 문서의 보호와 임시 조치, 토론 중재, 기록 잠금을 맡습니다. 운영진도 사건의 진상을 알지 못합니다.\n\n'
            f'| 닉네임 | 권한 | 선임일 | 비고 |\n| 서고지기 | 관리자 | {day} | 위키 개설 |\n| 회색수첩 | 기록 담당 | {day} | 기록 잠금, 처리 내역 관리 |\n'
            f'| 새벽편집 | 토론 중재 | {day} | 토론 규정 적용 |\n| 낡은필름 | 파일 담당 | {day} | 사진 출처와 얼굴 가림 확인 |\n\n'
            f'## 운영 회의\n### 제1회 운영 회의\n{year}년, 위키 개설과 함께 열렸습니다. 합의 사항은 다음과 같습니다.\n'
            '- 공인이 아닌 사건 관계자는 성과 직함, 또는 A씨와 같은 가명으로 적는다. 이미 실명으로 적힌 서술은 발견하는 대로 고친다.\n'
            '- 사건 관계자나 유족이 요청한 서술은 임시 조치하고, 이의는 그 문서의 토론에서 받는다.\n'
            '- 수사 기관의 발표나 보도로 확인되지 않은 추정은 본문보다 토론에서 먼저 다룬다.\n'
            '- 기록이 모두 모인 사건은 진상을 확정해 잠그고, 그 내역을 처리 내역에 남긴다.\n\n'
            '처리된 일은 처리 내역 문서에서 볼 수 있습니다.')

def tech(conf):
    """<위키 이름>:작동 방식. 이용 안내가 이용 방법이라면, 이 문서는 엔진이 어떻게 도는지를 적은 README 같은 문서다. 지금 설정은 wiki.json 에서 읽는다."""
    agent = conf.get('agent', 'claude')
    row = lambda k: f"{conf.get(k) or ('gpt-6.1-sol' if agent == 'codex' and k.startswith('model') else '기본값')}"      # Codex 모델을 비워 두면 엔진 기준 모델(live.CODEX_MODEL)을 쓴다
    mine = conf.get('steps') or {}
    return ('이 문서는 이 위키를 움직이는 엔진의 구조를 설명합니다. 이용 방법은 이용 안내 문서를 보십시오.\n\n'
            '## 개요\n'
            '이 위키의 사건은 사람이 아니라 뒤에서 도는 AI 에이전트가 짓고 씁니다. 사건 하나는 버튼을 누른 순간부터 지어지며, 미리 지어 둔 사건은 없습니다. 쓰는 중에 들어온 새 사건 주문은 예약 줄(최대 10건)에 서서 앞 사건을 다 쓴 뒤에 차례로 지어집니다. 낸 추리의 검토가 예약보다 먼저이고, 멈춤을 눌렀거나 쓰다 실패하면 줄은 그대로 기다립니다. '
            '보는 사람은 답을 모르는 채로 문서가 자라는 것을 읽고 추리합니다.\n'
            '- **라이브 서버**: 위키 화면을 내보내고, 버튼과 토론을 받아 에이전트를 부르고, 문서가 바뀔 때마다 화면을 다시 그립니다.\n'
            '- **엔진**: 사건을 짓고 문서를 쓰는 지침과 흐름입니다. 에이전트는 파일을 직접 고치지 않고 "어느 문서의 어느 문단에 이 글"이라는 편집 지시만 냅니다. 파일은 서버가 고칩니다.\n'
            '- **검사기**: 문서 사이의 모순, 링크, 가린 이름의 노출을 검사합니다.\n\n'
            '## 두 벌의 기록\n'
            '작가 에이전트는 사건을 두 벌로 짓습니다.\n'
            '- **진상**: 실제로 있었던 일과 단서의 뜻. 위키에는 쓰지 않고 봉인합니다.\n'
            '- **알려진 것**: 그 일이 정말 있었다면 세상이 보고 듣고 기록으로 알게 됐을 것. 문서를 쓰는 편집자 에이전트는 이것만 받습니다.\n\n'
            '편집자는 진상을 모릅니다. 답을 아는 채로 숨기며 쓰면 문장마다 티가 나기 때문입니다. 진상은 봉인할 때 지문(해시)을 떠 두고, 이후 진상 파일이 바뀌면 서버가 알아챕니다. 봉인 내역은 처리 내역 문서에 남습니다.\n\n'
            '## 사건 한 건의 흐름\n'
            '| 단계 | 하는 일 | 화면에 올라오는 것 |\n'
            '| 얼개 | 서로 다른 후보 다섯을 떠올려 하나를 고르고(두 번에 나눠, 먼저 후보 다섯을 꺼낸 뒤 이미 실린 사건과 견주어 고릅니다. 주문이 있으면 주문이 정한 것은 다섯 후보가 모두 지킵니다), 무슨 일이 있었나, 왜, 왜 드러나지 않았나를 정해 잠급니다. 이 위키에 이미 실린 사건들의 "알고 보니 어떤 일이었나"와 때, 그리고 고를 때는 세상이 처음 본 겉모습(훅)도 한 줄씩 보고, 속이 같은 종류인 후보는 버립니다. 소재와 때와 곳이 달라도 누가(한 사람인지 여럿인지) 어떤 마음으로 한 일인지가 같으면 같은 종류로 봅니다. 장부를 길게 주고 공통점을 찾게 하면 사건이 쌓일수록 얼개가 몇 분씩 길어져서, 얼개에는 이 짧은 꼴만 줍니다 | 사건 문서의 첫 화면 |\n'
            '| 설계 앞 절반 | 사람들과 일이 알려지기까지를 두 벌로 짓습니다. 이미 화면에 나간 첫 화면(정보 상자와 개요)을 함께 보고, 거기 실린 날짜와 숫자를 그대로 이어 씁니다. 사람과 가게 이름은 이 위키의 다른 사건에 이미 나온 이름과 겹치지 않게 짓습니다. 분량은 정해져 있지 않고, 그 세계에서 이 일이 얼마나 큰 일이었는지에 따라 작가가 정합니다. 한 동네의 일은 짧게, 여러 나라가 얽힌 일은 길게 남습니다 | 지역·기관 문서, 사건 전개 |\n'
            '| 설계 뒤 절반 | 수사, 세간의 설, 단서 사다리, 결론을 짓습니다. 단서가 몇 개인지, 어디에 놓이는지, 어떤 모양으로 이어지는지(모순 하나, 증언 대조, 시간표 다시 짜기, 다른 기록과 잇기 …)는 사건마다 다릅니다 | |\n'
            '| 시험 독자 | 진상을 모르는 독자가 공개 재료만으로 풀어 봅니다. 한 줄만 읽고 답이 나오거나, 결론을 그대로 말하는 줄로 답이 나오면 너무 쉬운 것으로 봅니다. 진상 쪽으로 짐작하되 확정하지 못하는 것이 바라는 자리입니다. 확정은 해설이 합니다. 공개 재료의 사실은 저마다 세상에 나온 길이 있어야 하고, 사적인 물건이나 기록은 가진 사람이 내놓을 까닭이 있을 때만 실립니다 | |\n'
            '| 따져 보기 | 다른 호출이 편집자와 독자의 눈으로 설계를 따지고, 지적된 곳만 고칩니다. 그럴듯한 오답 설이 공개된 사실의 논리로 버려지는지도 봅니다 | |\n'
            '| 봉인 | 진상을 잠그고 지문을 남깁니다. 해설과 해설 그림을 이때부터 따로 준비합니다 | 처리 내역 |\n'
            '| 쓰기 | 편집자들이 수사, 의문점, 토론을 쓰고 기록 담당이 지식·장소 문서와 단서가 숨은 문서를 씁니다 | 문서 본문, 토론, 사진 |\n'
            '| 마감 | 단서가 문서에 다 들어갔는지, 링크나 검색으로 닿는 곳에 있는지 확인하고, 검사에서 나온 오류만 문장 단위로 고칩니다 | |\n'
            '| 채점 준비 | 추리를 보기 전에 봉인된 진상에서 채점 기준을 만들어 둡니다 | 추리 제출 열림 |\n\n'
            '## 채점\n'
            '추리가 들어오면 미리 만든 기준마다 검토합니다. 필수 항목이 모두 맞는지와 등급(완전 해결, 거의 해결, 절반, 빗나감)은 서버가 판정을 정해진 표로 합쳐 계산합니다. 다 맞으면 정답으로 인정하고 전말을 엽니다. 기준은 추리를 보기 전에 만들어지므로 제출된 추리에 맞춰 바뀌지 않습니다.\n\n'
            '## 사진\n'
            '사진은 문단이 쓰이면 사진 담당이 그 글만 읽고 골라, 따로 도는 이미지 호출이 곧바로 만듭니다. 문서가 이름을 가리는 사람이 나오는 사진이면, 그 사진을 그린 쪽이 그 사람 얼굴의 자리를 적고 서버가 얼굴 검출 모델(YuNet)로 그 얼굴만 찾아 모자이크합니다. 함께 찍힌 다른 사람은 가리지 않습니다. 전말 문서 맨 위의 그림은 아무도 찍지 못한 진상의 순간입니다.\n\n'
            '## 시즌\n'
            '위키를 새로 열 때마다 새 시즌이 시작됩니다. 첫 실행 때 에이전트가 이 시즌의 로고(SVG), 상징색, 대문 인사말, 운영진, 운영 회의를 한 번 정하고 시즌 동안 고정합니다.\n\n'
            '## 생각 깊이\n'
            '에이전트가 사건을 쓰는 단계마다 모델과 생각 깊이를 따로 고를 수 있습니다. 깊게 생각할수록 결이 좋아지지만 오래 걸립니다. 깊이가 사건을 가장 크게 바꾸는 단계는 사건 구상(얼개)입니다. 얕게 생각하면 후보를 여럿 떠올려도 비슷한 결(사연, 조작된 퍼즐)에 머물고, 한 단계만 깊게 해도 어두운 가족 이야기부터 기묘한 사건까지 고루 나옵니다. 그보다 더 깊게 하면 시간만 늘고, 가장 깊게 하면 오히려 같은 사건으로 모입니다.\n\n'
            '| 사건 구상 깊이 | 첫 화면까지 | 사건 하나 | 결 |\n'
            '| low | 약 1분 반 | 7~8분 | 사연과 조작된 퍼즐에 쏠림 |\n'
            '| medium (권장) | 3~5분 | 8~10분 | 고루 나옴 |\n'
            '| high | 약 8~12분 | 약 15분 | 가장 기묘하지만 느림 |\n'
            '| ultra | 약 27분 | 약 37분 | 같은 사건으로 모이고 진상이 꼬임 |\n\n'
            '2026년 11월 gpt-6.1-sol로 재어 본 값입니다. Codex로 돌릴 때 모델을 따로 고르지 않으면 이 위키는 gpt-6.1-sol을 씁니다. 컴퓨터의 Codex 기본 모델이 무엇이든 따라가지 않습니다. 지침과 분량이 이 모델에 맞춰져 있어서, 다른 모델로 바뀌면 사건 문서가 눈에 띄게 짧아졌습니다. 기본 값은 사건 구상, 따져 보기, 해설과 채점이 medium이고 나머지 단계가 low입니다. 본문과 둘레 문서는 이미 정해진 재료를 글로 옮기는 일이라 깊이를 올려도 차이가 작습니다. 주문을 함께 줄 때는 무엇을 쓸지가 이미 정해져 있으므로 사건 구상도 low로 충분합니다.\n\n'
            '## 지금 설정\n'
            '| 항목 | 값 |\n'
            f'| 에이전트 | {agent} |\n'
            f'| 기본 모델 | {row("model")} · {row("model_deep")} |\n'
            f'| 기본 생각 깊이 | {row("effort")} · {row("effort_deep")} |\n'
            + ''.join(f'| {n} | {mine[k].get("model") or "기본"} · {mine[k].get("effort") or "기본"} |\n' for k, n, _, _ in STEPS if k in mine)
            + '\n기본 값은 앞쪽이 글을 쓰는 단계, 뒤쪽이 사건 구상, 따져 보기, 해설과 채점에 쓰입니다. 단계마다 따로 고른 값이 있으면 그 값이 먼저이고 위 표에 따로 나옵니다. 값은 편집 조작(✎)의 설정에서 바꿉니다.')


# 닉네임을 짓는 원리. 토론 글쓴이와 편집자, 사건 속 인물, 시즌 운영진이 같이 쓴다. 지시가 없으면 모델은 감성 명사 하나짜리 닉네임만
# 짓고, 위키에 쌓인 그것을 보고 다시 따라 지어 위키 전체가 한 가지 결이 됐다(2026-11-22 실험: 그대로 두면 24개 중 20~24개가 그 꼴,
# 이 원리를 주면 12개. 사건 속 인물은 실존 이름 대신 지어낸 이름이 나왔다). 예시나 직업별 규칙은 넣지 않는다. 모델이 그대로 따라 쓴다
NICKNAME = ('닉네임은 그 사람이 어떤 사이트나 서비스에 계정을 만들던 날 자기 버릇대로 지은 이름이고, 사람마다 짓는 습관이 다르다. '
            '이름을 붙이기 전에 그 사람이 누구이고, 이 일을 어디서 접했고, 평소 어디서 무엇을 하는 사람인지 먼저 속으로 정한다. '
            '그런 사람이 만들었을 계정의 이름을 붙인다. 세상에 이름이 알려진 사람도, 세상이 아는 것이 그 사람이 직접 만든 활동 이름이면 그 이름을 붙인다. '
            '속으로 정한 것은 쓰지 않는다. 위키에 이미 보이는 이름들은 다른 사람들의 것이다.')
# 가게·회사·단체·매체처럼 지어내는 이름. 그대로 두면 온결·은결·곁·서림·이음 같은 예쁜 조어에 "~라는 뜻으로 지은 이름" 뜻풀이가 붙었다.
# 연 사람을 먼저 세우게 해도 그대로였고, 흔하고 평범한 것을 고르게 하자 사라졌다(2026-11-22, 실제 사건 셋으로 설계 단계 실험)
ORGNAME = ('가게·회사·단체·매체처럼 이 세계에 지어내는 이름은 후보를 여럿 떠올리고, 그 가운데 그때 그 거리와 그 업계에서 가장 흔하고 평범했을 것을 고른다. '
           '실제 상호와 단체 이름은 대개 평범하다. 후보는 쓰지 않는다.')


# 설정 창의 단계. (이름, 화면 이름, 하는 일, 처음 값이 깊은 차례인가). 호출마다 붙은 이름표(tag)가 단계를 정한다. 설정 창(live.py)과 작동 방식이 같이 쓴다
STEPS = [('premise', '사건 구상', '무슨 일이 있었고 무엇이 수수께끼로 남는지 정합니다. 깊이가 사건의 결을 가장 크게 바꿉니다.', True),
         ('design', '설계', '사람, 알려진 일, 수사, 단서를 짓고 지적받은 곳을 고칩니다.', False),
         ('reader', '시험 독자', '진상을 모르는 독자가 공개 재료만으로 풀어 봅니다.', False),
         ('critic', '따져 보기', '설계가 말이 되는지, 풀 수 있는지 따집니다.', True),
         ('body', '본문', '사건 문서의 사건 전개, 수사, 마무리를 쓰고 검사 오류를 고칩니다.', False),
         ('around', '둘레 문서', '지역, 기관, 지식 문서와 단서가 숨은 문서를 씁니다.', False),
         ('shots', '사진 고르기', '쓰인 문단을 읽고 실을 사진을 고릅니다.', False),
         ('images', '사진 그리기', '고른 사진과 해설 그림을 그립니다.', False),
         ('talk', '토론과 답글', '토론 글과 힌트를 쓰고 독자 글에 답합니다.', False),
         ('record', '기록', '조각 표와 장부를 정리합니다.', False),
         ('grade', '해설과 채점', '해설을 쓰고, 추리를 채점하고, 종결 의견을 검토합니다.', True)]


def cat_file(c):
    return fname('분류.' + c)


# 사건 문서 위에 붙는 틀. 위키가 사건 문서를 다루는 방식에 관한 안내다
NOTE_CASE = '<div class="tmpl"><b>주의. 사건·사고 관련 내용을 설명합니다.</b><br><span class="sm">사건 사고 관련 서술 규정을 유의하시기 바랍니다.</span></div>'

# 위키 자체를 설명하는 프로젝트 문서. 나무위키의 '나무위키:' 문서처럼 일반 문서와 따로 둔다. 서버가 만드는 고정 문서라 에이전트가 받는 문서 목록에 들어가지 않는다
GUIDE = """이 문서는 이 위키를 처음 찾은 사람을 위한 안내입니다. 규정으로서의 효력은 없습니다. 이 위키가 어떻게 움직이는지는 작동 방식 문서를 보십시오.

## 사건 기록
사건 문서는 편집자들이 공개된 보도, 수사 발표, 증언을 모아 정리합니다. 편집자들도 사건의 진상을 알지 못합니다.
- 문서는 기록이 모이는 대로 자랍니다. 사건 문서에서 이어지는 인물·장소·지식 문서에도 사건과 닿는 사실이 실립니다.
- 기록이 모두 모이면 그 사건의 진상이 확정되어 잠깁니다. 이후 문서가 보강되어도 진상은 바뀌지 않습니다.
- 사건은 한 번에 하나씩 쓰입니다. 쓰는 중에 편집 조작(✎)의 **새 사건 문서**를 누르면 다음 사건으로 예약되고, 앞 사건이 끝나면 예약한 순서대로 하나씩 열립니다. 예약은 조작부 아래에서 고치거나 지우거나 맨 앞으로 옮길 수 있습니다.

## 토론
모든 문서에는 토론이 있습니다. 진상이 확정된 사건은 문서 위쪽의 **토론** 탭에서 누구나 새 주제를 열 수 있습니다. 답이 달리기까지 몇 분이 걸립니다.
- **사실을 묻는 글**: 문서에 빠진 사실을 물으면 편집자들이 기록을 찾아 답하고, 필요하면 문서를 보강합니다.
- **가설을 내는 글**: 편집자들은 가설의 옳고 그름을 판정하지 않습니다. 그 가설과 맞는 기록과 맞지 않는 기록을 짚어 답합니다.
- **문서 요청**: 사건과 상관없이 이 위키에 있을 만한 문서라면 새로 작성됩니다.

진상을 묻거나 규정에 어긋나는 글은 토론에 옮겨지지 않습니다.

## 새 소식
사건마다 세 번까지, 뒤늦게 알려진 사실이 편집으로 올라옵니다. 편집 조작(✎)의 **힌트**로 부를 수 있습니다.
- 첫 번째: 토론에서 지나친 단서를 짚는 글
- 두 번째: 뒤늦게 알려진 사실
- 세 번째: 사건을 다시 다룬 방송

## 종결 의견
사건의 진상에 대한 자신의 추리는 편집 조작(✎)의 **추리 제출**로 냅니다.
- 제출된 의견은 확정된 진상과 대조해 검토하고, 기준마다 맞힘(✔), 일부(△), 놓침(✘)으로 알려 줍니다.
- 결과는 **완전 해결**, **거의 해결**, **절반**, **빗나감** 네 등급입니다. 완전 해결이면 정답으로 인정되어 사건의 전말이 열립니다.
- 완전 해결이 아니면 다시 추리하거나, **이 등급으로 마치기**를 눌러 그 등급으로 사건을 마치고 전말을 볼 수 있습니다. 전말 맨 위에 낸 추리와 판정이 함께 나옵니다.
- 편집 조작(✎) 맨 아래의 **추리 기록**에서 사건마다 낸 추리와 등급, 힌트 수를 모아 볼 수 있습니다.

## 사건의 전말
추리를 내지 않고도 편집 조작(✎)의 **해설 열기**로 사건의 전말을 볼 수 있습니다. 전말을 연 사건은 해설을 본 사건으로 남으며, 그 뒤로는 추리를 낼 수 없습니다.

## 인물 표기
공인이 아닌 사건 관계자는 성과 직함, 또는 가린 이름으로 적습니다. 자세한 기준은 대문의 주요 운영 알림을 참고하십시오."""

KINDS = ['사건', '인물', '장소', '기관', '지역', '매체', '기타']      # 대문과 종류별 목록에 나오는 차례


def front(docs, recent, project=None):
    """대문. 나무위키 대문의 짜임을 따른다: 가운데 인사말, 왼쪽 칸에 그림 글자가 있는 안내 표, 머리띠가 있는 분류 표, 운영 알림, 최근 토론.
    사건 목록은 두지 않는다. '열린 기록' 줄에 사건마다 번호와 훅 한 문장만 나오고, 누르면 그 사건으로 간다."""
    e = html.escape
    conf = json.loads(Path(project, 'wiki.json').read_text(encoding='utf-8-sig')) if project and Path(project, 'wiki.json').is_file() else {}
    name = e(conf.get('name', '위키')); season = conf.get('season') or {}
    main = {n: d for n, d in docs.items() if not d['rev'] and n != '대문'}
    cases = sorted((d for d in main.values() if d['meta'].get('teaser')), key=lambda d: d['meta'].get('modified', ''), reverse=True)
    rec = ''.join(f'<a class="rec" href="{quote(fname(d["name"]))}"><span class="no">기록 {len(cases) - k:03d}</span>{e(d["meta"]["teaser"])}</a>'
                  for k, d in enumerate(cases[:5])) or '<span class="mute">아직 열린 기록이 없습니다.</span>'
    wanted = sorted({m[1].strip() for d in main.values() for m in LINK.finditer(d['body'] + d['토론'])} - set(docs))[:10]
    want = ' · '.join(f'<a class="new" href="_none.html#{quote(t)}">{e(t)}</a>' for t in wanted) or '<span class="mute">요청된 문서가 없습니다.</span>'
    gone = [n for n, d in main.items() if d['meta'].get('deleted')]
    cut = '사건 관계자나 유족이 요청한 서술은 임시 조치하며, 요청은 해당 문서의 토론에서 받습니다.' + (
        '<br>임시 조치된 문서: ' + ' · '.join(f'<a href="{quote(fname(n))}">{e(n)}</a>' for n in gone) if gone else '')
    row = lambda icon, title, body: f'<tr><td class="ic">{icon}</td><td><div class="rt">{title}</div>{body}</td></tr>'
    guide = ('<table class="mp">'
             + row('?', f'{name}에 처음 오셨나요?', '먼저 <a href="_guide.html">이용 안내</a>와 <a href="_tech.html">작동 방식</a>, 아래의 운영 알림, 인물 표기 기준을 확인해 보세요. 문서마다 토론과 역사를 볼 수 있습니다. 운영은 <a href="_staff.html">운영진</a>, 처리된 일은 <a href="_records.html">처리 내역</a>에 남습니다.')
             + row('&#9998;', '열린 기록', rec)
             + row('&#43;', '작성이 요청된 문서', want)
             + row('&#9878;', '삭제와 임시 조치', cut) + '</table>')
    cats = {}
    for n, d in main.items():
        for c in d['meta'].get('category', '').split(','):
            if c.strip():
                cats.setdefault(c.strip(), []).append(n)
    kinds = {}
    for n, d in main.items():
        if not d['meta'].get('deleted'):
            kinds.setdefault(d['meta'].get('type') or '기타', []).append(n)
    index = ''
    if kinds:
        rows = ''
        for k in sorted(kinds, key=lambda k: KINDS.index(k) if k in KINDS else len(KINDS)):
            ns = sorted(kinds[k], key=lambda n: main[n]['meta'].get('modified', ''), reverse=True)
            rows += (f'<tr><td colspan="2"><a class="bdg" href="{quote(fname("종류." + k))}">{e(k)} {len(ns)}</a> '
                     + ' · '.join(f'<a href="{quote(fname(n))}">{e(n)}</a>' for n in ns[:8])
                     + (f' <a class="mute" href="{quote(fname("종류." + k))}">… 외 {len(ns) - 8}개</a>' if len(ns) > 8 else '') + '</td></tr>')
        index = ('<table class="mp"><tr><th class="mh" colspan="2">문서</th></tr>' + rows
                 + f'<tr><td colspan="2" style="text-align:right"><a href="_cats.html">분류 전체 보기 ({len(cats)}개)</a></td></tr></table>')
    notice = ('<div class="mcard"><div class="mct">주요 운영 알림</div><ul>'
              + ''.join(f'<li>{e(r)}</li>' for r in conf.get('rules') or season.get('rules') or rules(str(conf.get('created', ''))[:4] or '올해')) + '</ul></div>')
    talks = [c for c in recent if '토론' in c['kind']][:5]
    talk = ('<div class="mcard"><div class="mct">최근 토론</div><ul>' + ''.join(
        f'<li><a href="{c["href"]}">{e(c["doc"])}</a> <span class="mute">{e(c["t"][-8:-3])}</span></li>' for c in talks) + '</ul></div>') if talks else ''
    hello = ((f'<div class="hello"><div class="big">{e(season["hello"])}</div>' if season.get('hello') else '<div class="hello"><div class="big">여러분이 함께 정리하는 <b>미제 사건 기록</b></div>')
             + (f'<div>{e(season["tagline"])}</div>' if season.get('tagline') else f'<div><b>{name}</b>에 오신 것을 환영합니다!</div>') +
             f'<div class="sm">{name}는 누구나 기여할 수 있는 위키입니다.<br>검증되지 않았거나 편향된 내용이 있을 수 있습니다.</div></div>')
    return hello + guide + index + notice + talk


# 나무위키의 어두운 테마를 따랐다. 값은 실제 화면에서 가져왔다: 바탕 #000, 문서 칸 #1c1d1f 테두리 #444, 글자 #e0e0e0, 링크 #ec9f19, 윗띠 #2e3033, 표 칸 #2d2f34 테두리 #383b40.
CSS = """
/* 스크롤바: 브라우저 기본 모양 대신 어두운 화면에 맞는 가는 막대 */
html{color-scheme:dark}*{scrollbar-width:thin;scrollbar-color:#4a4d53 transparent}
::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#4a4d53;border-radius:4px}::-webkit-scrollbar-thumb:hover{background:#6a6e75}::-webkit-scrollbar-corner{background:transparent}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#000;color:#e0e0e0;font:16px/1.6 "Pretendard JP",Pretendard,-apple-system,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif}
a{color:#ec9f19;text-decoration:none}a:hover{color:#bd7f14;text-decoration:underline}a.new{color:#d64a58}
.bar{background:#2e3033;height:56px;padding:8px 16px;display:flex;align-items:center;gap:4px;position:sticky;top:0;z-index:10}
.bar a{color:#fff;font-size:16.8px;font-weight:500;padding:0 12px;line-height:40px;border-radius:4px}.bar a:hover{background:rgba(255,255,255,.08);color:#fff;text-decoration:none}
.bar a.brand{font-size:21px;font-weight:700;padding-left:0;margin-right:12px;display:inline-flex;align-items:center;gap:8px}.bar img.logo{width:28px;height:28px}.bar form{margin-left:auto}
.bar input{width:320px;max-width:42vw;height:40px;padding:0 12px;border:1px solid #444;border-radius:6px;font:inherit;font-size:15px;background:#000;color:#e0e0e0}
.wrap{max-width:1300px;margin:0 auto;padding:16px;display:flex;gap:16px;align-items:flex-start}
main{flex:1;min-width:0;background:#1c1d1f;border:1px solid #444;border-radius:6px;padding:24px}main::after{content:"";display:block;clear:both}
aside{width:300px;flex:none;position:sticky;top:72px}.card{background:#1c1d1f;border:1px solid #444;border-radius:6px;margin-bottom:16px;overflow:hidden}
.side-toc .contents,.read-panel .contents{max-height:44vh;overflow:auto;padding:8px 10px}.side-toc a,.read-panel a{display:block;padding:5px 8px;border-left:2px solid transparent;color:#c6c8cb;font-size:14px}.side-toc a.sub,.read-panel a.sub{padding-left:22px}.side-toc a.active,.read-panel a.active{border-color:#ec9f19;color:#ec9f19;background:#25272b}
.read-nav{position:fixed;right:18px;bottom:86px;z-index:15;display:flex;flex-direction:column;gap:4px}.read-nav button{width:40px;height:40px;border:1px solid #4a4d53;border-radius:4px;background:#27292d;color:#e0e0e0;font:24px/1 sans-serif;cursor:pointer}.read-nav button:hover{background:#34363b}.read-nav button:focus-visible{outline:2px solid #ec9f19;outline-offset:2px}.read-nav button:disabled{opacity:.4;cursor:default}.read-panel{position:fixed;right:70px;bottom:86px;width:300px;max-width:calc(100vw - 86px);z-index:19;box-shadow:0 4px 20px #0008}.read-panel .ch{padding:10px 16px;border-bottom:1px solid #444}
.card .ch{padding:10px 16px;font-size:16.8px;font-weight:500;border-bottom:1px solid #444}.card .ci{display:flex;justify-content:space-between;gap:10px;padding:5px 16px;font-size:14.4px}
.card .ci a{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.card .ci span{color:rgba(224,224,224,.5);flex:none}.card .cn{padding:10px 16px;font-size:14.4px;color:rgba(224,224,224,.5)}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:24px}h1{font-size:36px;font-weight:700;line-height:1.15;margin:0;color:#e0e0e0}h1 small{font-size:.5em;font-weight:400;color:rgba(224,224,224,.6)}
.mod{color:rgba(224,224,224,.75);font-size:14.4px;margin-top:8px}
.btns{display:flex;flex:none}.btns a{background:#1c1d1f;border:1px solid #3e3e3e;margin-left:-1px;padding:4px 12px;color:rgba(224,224,224,.75);font-size:15px}.btns a:first-child{border-radius:4.8px 0 0 4.8px}.btns a:last-child{border-radius:0 4.8px 4.8px 0}
.btns a.on{background:#2e3033;color:#fff}.btns a:hover{text-decoration:none;background:#262626}
.cat{border:1px solid #383b40;border-radius:4px;padding:3.2px 8px;font-size:14.4px;margin:0 0 14.4px}
h2{font-size:1.8em;font-weight:700;border-bottom:1px solid #555;margin:1.2em 0 .7em;padding-bottom:5px}h3{font-size:1.45em;font-weight:700;border-bottom:1px solid #444;margin:1.1em 0 .6em;padding-bottom:4px}
h2,h3,.toc,.src,blockquote,table.t{overflow:hidden}
h2,h3,[id^="fn"],#toc{scroll-margin-top:76px}
.article-lead{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start;margin:20px 0}
.lead-copy{min-width:0}.lead-copy>h2:first-child,.lead-copy>h3:first-child{margin:0 0 12px}.lead-copy>p:last-child{margin-bottom:0}
.lead-info table.info{float:none;width:100%;margin:0}
.toc{display:flex;gap:18px;border:1px solid #444;padding:10px 14px;margin:20px 0;font-size:15px;clear:both}.toc b{flex:none}.toc-items{display:flex;flex-wrap:wrap;gap:4px 20px}.toc .l3{padding-left:12px}.toc a{color:inherit}.toc a:hover{color:#ec9f19}
table{border-collapse:collapse}th,td{border:1px solid #383b40;padding:5px 10px;text-align:left;vertical-align:top}th{background:#2d2f34}
table.t{width:100%;max-width:660px;margin:20px auto}.table-wrap{max-width:660px;margin:20px auto;overflow-x:auto}.table-wrap table.t{margin:0}table.info{float:right;margin:0 0 6px 24px;width:340px;max-width:100%;font-size:15px}table.info th{white-space:nowrap}th.cap{text-align:center;font-size:16px}
blockquote{display:table;margin:12px 0;padding:12px 16px;border:2px dashed #555;border-left:5px solid #71bc6d;background:#2d2f34}blockquote hr{border:0;border-top:1px solid #555;margin:8px 0}blockquote .qs{font-size:14.4px;color:rgba(224,224,224,.75);text-align:right}
h2.tt{font-size:22.5px;border:0;margin:26px 0 12px}.cm{max-width:72%;margin:0 0 24px 25px;background:#2d2f34;border:1px solid #383b40;border-radius:4px;overflow:hidden}
.cmh{display:flex;justify-content:space-between;padding:7px 10px}.cmh span:last-child{color:rgba(224,224,224,.75);font-size:14.4px}.cmb{background:#27292d;padding:13px}
ul.hist{padding-left:20px;font-size:15px}ul.hist li{padding:2px 0}@media(max-width:700px){.cm{max-width:100%;margin-left:0}}
.media{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;max-width:660px;margin:20px auto;clear:both}.media.gallery{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}
figure{margin:0;border:1px solid #444;padding:6px;min-width:0}figure img{width:100%;max-width:100%;height:auto;display:block}.gallery img{aspect-ratio:4/3;object-fit:contain;background:#131415}figcaption{font-size:14.4px;color:rgba(224,224,224,.75);padding-top:6px;text-align:center;text-wrap:balance}
.noimg{width:300px;max-width:100%;height:190px;background:#2d2f34;color:rgba(224,224,224,.5);display:flex;align-items:center;justify-content:center}
figure.map{display:block;max-width:660px;margin:20px auto;background:#f3efe4;padding:0;border-color:#555;overflow-x:auto}figure.map svg{width:100%;height:auto;display:block}figure.map figcaption{background:#1c1d1f;padding:6px 8px}
.fn{font-size:.8em;vertical-align:super;line-height:0}.notes{border-top:1px solid #555;margin-top:36px;padding-top:10px;font-size:15px;clear:both}.notes p{margin:4px 0}
.fntip{position:fixed;display:none;z-index:30;max-width:440px;background:#2d2f34;border:1px solid #555;border-radius:6px;padding:8px 14px;font-size:15px;line-height:1.6;box-shadow:0 3px 14px rgba(0,0,0,.6)}
.chat{max-width:420px;margin:14px 0;padding:0 0 10px;border:1px solid #3a3d43;border-radius:10px;background:#1b1c1f;overflow:hidden;clear:both}
.chat .ch{padding:8px 14px;background:#26282c;border-bottom:1px solid #3a3d43;font-size:13px;color:rgba(224,224,224,.6);margin-bottom:8px}
.chat .cm{padding:3px 14px;line-height:1.5}.chat .cn{display:block;font-size:12px;color:rgba(224,224,224,.55)}
.chat .cb{display:inline-block;max-width:80%;padding:6px 10px;border-radius:10px;background:#2f3237;font-size:14px}.chat .ct{margin-left:6px;font-size:11px;color:rgba(224,224,224,.4)}
.box{border:1px solid #5a2f33;border-left:5px solid #d64a58;background:#2a1c1e;padding:12px 16px;margin:16px 0}
.src{border:1px solid #444;background:#131415;padding:14px 20px;margin:14px 0;font-family:"Batang","AppleMyungjo",serif;line-height:1.9;clear:both}
.srct{font-family:"Malgun Gothic",sans-serif;font-size:14px;color:rgba(224,224,224,.5);border-bottom:1px solid #383b40;margin-bottom:8px;padding-bottom:4px}
.fic{max-width:1300px;margin:0 auto;padding:6px 16px 0;font-size:13px;color:rgba(224,224,224,.35);text-align:right}
.hello{text-align:center;margin:8px 0 22px}.hello .big{font-size:1.25em;margin-bottom:2px}.hello .sm{font-size:14.4px;color:rgba(224,224,224,.75);margin-top:14px}
table.mp{width:100%;border:2px solid #2d2f34;margin:0 0 16px}table.mp td{border-color:#383b40;padding:8px 12px}table.mp td.ic{width:84px;background:#2d2f34;text-align:center;vertical-align:middle;font-size:34px;line-height:1;color:#e0e0e0}
table.mp .rt{font-size:1.15em;font-weight:700;margin-bottom:2px}table.mp th.mh{background:#2d2f34;text-align:center;font-size:1.1em;padding:7px}
a.bdg{color:#e0e0e0}.bdg{display:inline-block;background:#2d2f34;border-radius:3px;padding:2px 6px;font-size:13.5px;font-weight:700;margin-right:4px}
a.rec{display:block;color:#e0e0e0;padding:6px 0}a.rec:hover{color:#fff;text-decoration:none}a.rec .no{display:inline-block;background:#2d2f34;border-radius:3px;padding:1px 6px;font-size:13px;font-weight:700;margin-right:8px;color:#ec9f19}
.mcard{border:1px solid #444;border-top:3px solid #2d2f34;border-radius:4px;padding:10px 16px 6px;margin:0 0 16px}.mcard .mct{font-size:1.2em;font-weight:700;border-bottom:1px solid #383b40;padding-bottom:6px;margin-bottom:4px}
.mcard ul{margin:6px 0;padding-left:20px}.mcard li{padding:5px 0;border-bottom:1px solid #2d2f34}.mcard li:last-child{border-bottom:0}
table.diff{width:100%;border-collapse:collapse;font-size:14.5px;line-height:1.6;table-layout:fixed}table.diff th{width:22px;font-weight:400;color:rgba(224,224,224,.5);vertical-align:top}
table.diff td{padding:2px 8px;white-space:pre-wrap;word-break:break-all}tr.dd td{background:#3a1f22}tr.da td{background:#1c3323}tr.dd del{background:#7a2a31;text-decoration:none}tr.da ins{background:#2b6b3d;text-decoration:none}
.sr{padding:16px 0 14px;border-top:1px solid #383838}.sr h3{margin:0 0 6px;font-size:21px;font-weight:700}.sr h3 a{display:inline-flex;align-items:center;gap:6px}.sr h3 svg{width:22px;height:22px;flex:none;opacity:.85}.snip{font-size:15px;line-height:1.7;word-break:break-all;color:rgba(224,224,224,.85)}mark{background:#5a5a5a;color:#fff;border-radius:3px;padding:0 2px}.sform{display:flex;gap:6px;margin:14px 0 10px}.sform select,.sform input{height:38px;background:#000;color:#e0e0e0;border:1px solid #444;border-radius:4px;padding:0 8px;font:inherit;font-size:15px}.sform input{flex:1;min-width:0}.sform button{height:38px;padding:0 18px;background:#0275d8;color:#fff;border:0;border-radius:4px;font:inherit;font-size:15px;cursor:pointer}.sgo{display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid #444;border-radius:6px;padding:10px 14px;margin:10px 0;font-size:14.4px}.sgo a{border:1px solid #555;border-radius:4px;padding:5px 12px;white-space:nowrap;color:#e0e0e0}.scount{font-size:14.4px;color:rgba(224,224,224,.7);margin:16px 0 4px}.none{margin:20px 0}.bar a.brand{white-space:nowrap;flex:none}.bar form.sf{position:relative}.bar a.mi{display:none}.sug{position:absolute;left:0;right:0;top:100%;margin:2px 0 0;padding:4px 0;list-style:none;background:#2e3033;border:1px solid #444;border-radius:6px;z-index:30;max-height:60vh;overflow:auto}.sug li{padding:9px 14px;cursor:pointer;color:#e0e0e0}.sug li:hover{background:rgba(255,255,255,.08)}.bar form.sf{display:flex;align-items:center;gap:2px}.bar .ib{width:38px;height:40px;background:none;border:0;color:#fff;cursor:pointer;border-radius:4px;padding:8px}.bar .ib:hover{background:rgba(255,255,255,.08)}.bar .ib:disabled{opacity:.35;cursor:default}.bar .ib svg{width:22px;height:22px}@media(max-width:700px){.bar{height:auto;padding:0;flex-wrap:wrap;gap:0}.bar a.brand{margin:0;padding:10px 14px;font-size:20px;flex:1}.bar a.mi{display:inline-flex;align-items:center;padding:0 12px}.bar a.mi svg{width:24px;height:24px}.bar .ib{width:42px;padding:9px}.bar input{max-width:none;width:0;flex:1;min-width:0;height:46px;border:0;border-radius:0;background:transparent;font-size:16px}.bar form.sf{flex:1 0 100%;order:2;min-width:0;margin:0;padding:0 4px;background:#232528;border-top:1px solid #3a3d43;border-bottom:1px solid #3a3d43}.sug{margin:0;border-radius:0;border-width:0 0 1px}.sform select{max-width:88px}.sgo{flex-direction:column;align-items:flex-start}}
.tmpl{border:1px solid #6b5a14;border-left:5px solid #ec9f19;background:#2a2617;padding:8px 14px;margin:0 0 14px;font-size:15px;text-align:center}.tmpl .sm{font-size:13.5px;color:rgba(224,224,224,.75)}a.ed{float:right;font-size:14px;font-weight:400;color:rgba(224,224,224,.55);margin-left:10px}a.ed:hover{color:#ec9f19}
main h2,main h3{cursor:pointer}h2.fold,h3.fold{color:rgba(224,224,224,.55)}h2.fold::after,h3.fold::after{content:" ⋯";font-weight:400}
figure.photo img{height:auto}figure.photo a{display:block}figure.file{max-width:900px;margin:0 auto 16px}
.mute{color:rgba(224,224,224,.5);font-size:14.4px}.plus{color:#6bcf7f}.minus{color:#ff7b7b}
footer{max-width:1300px;margin:0 auto 30px;padding:0 16px;color:rgba(224,224,224,.35);font-size:13.5px}
@media(max-width:1100px){.article-lead{grid-template-columns:minmax(0,1fr)}.lead-info{max-width:660px;width:100%;margin:auto}}
@media(max-width:1000px){aside{display:none}}@media(max-width:700px){.wrap{padding:0}main{padding:14px 14px 20px;border:0;border-radius:0}table.info{float:none;margin:12px 0;width:100%}h1{font-size:28px}.head{flex-direction:column;gap:12px}.bar a:not(.brand):not(.mi){display:none}.media.gallery{grid-template-columns:minmax(0,1fr)}.gallery img{aspect-ratio:auto}figure.map svg{min-width:560px}}
"""


def build(project, wiki=None, text=False, out='site', inject='', single=False, store=None, write=True, recent=None, ghost=False):
    """out과 inject는 운영용 화면(admin.py)이 쓴다. store(dict)를 주면 쪽 HTML을 거기에 담고, write=False면 파일로 쓰지 않는다(live.py).
    recent 는 라이브 화면이 주는 실제 변경 기록이고, 없으면 문서들의 역사에서 모은다."""
    project = Path(project); docs = load(project); wiki = wiki or wiki_name(project)
    f = project / 'wiki.json'; top = NOTICE if f.is_file() and json.loads(f.read_text(encoding='utf-8-sig')).get('notice_top') else ''
    if not docs:
        sys.exit('docs/ 폴더에 .md 문서가 없습니다.')
    site = project / out
    if write:
        shutil.rmtree(site, ignore_errors=True)
    site.mkdir(exist_ok=True)
    start = start_doc(docs)
    titles = json.dumps({n: quote(fname(n)) for n, d in docs.items() if not d['rev']}, ensure_ascii=False)
    pool = json.dumps([quote(fname(n)) for n, d in docs.items() if not d['rev'] and n != '대문' and not d['meta'].get('deleted')])     # 임의 문서는 대문과 지워진 문서를 빼고 고른다. 지금 보는 문서도 뺀다
    pool = '' if pool == '[]' else pool
    R = lambda t, numbered=True: render(t, docs, project / 'docs' / 'img', site / 'img', numbered, ghost)
    e = html.escape
    if recent is None:
        rows = sorted(((r[1], n, r[4]) for n, d in docs.items() if not d['rev'] and n != '대문' for r in d['history']), reverse=True)[:100]
        recent = [dict(t=t, doc=n, href=quote(fname(n)), kind=k or '편집') for t, n, k in rows]

    season = (json.loads((project / 'wiki.json').read_text(encoding='utf-8-sig')) if (project / 'wiki.json').is_file() else {}).get('season') or {}
    logo = season.get('logo', '') if '<svg' in season.get('logo', '') else ''      # 시즌을 열 때 에이전트가 그린 문양. 그림 파일로만 실어 스크립트가 돌지 않는다
    c = season.get('color', '') if re.fullmatch(r'#[0-9a-fA-F]{6}', season.get('color', '')) else ''
    # 문서를 읽는 화면(링크, 문단 번호, 목차의 지금 자리)은 시즌마다 바꾸지 않는다. 시즌 색이 문단 번호까지 칠하자 새 시즌마다
    # 같은 위키가 낯설게 읽혔다(2026-11-22). 시즌 색은 대문의 기록 번호 같은 장식에만 쓴다
    wm = season.get('wordmark') if isinstance(season.get('wordmark'), dict) else {}
    wmc = wm.get('color', '') if re.fullmatch(r'#[0-9a-fA-F]{6}', str(wm.get('color', ''))) else ''
    ci = f'<div class="lockup"><img src="_logo.svg" alt=""><div class="wm">{e(wiki)}</div></div>' if logo else ''      # 세로 조합형. 운영 문서 맨 위에 대표 그림으로 싣는다. 이름을 ci 로 했더니 최근 변경 한 줄(.card .ci)에 여백이 붙었다
    css = CSS + '.lockup{text-align:center;margin:6px 0 22px}.lockup img{width:88px;height:88px;display:block;margin:0 auto}.lockup .wm{font-size:26px;margin-top:10px}' + (
        f'.wm{{font-weight:{int(wm.get("weight", 700))};letter-spacing:{float(wm.get("spacing", 0))}em' + (f';color:{wmc}' if wmc else '') + '}' if wm else '') + (f'a.rec .no{{color:{c}}}' if c else '')
    icon = '<link rel="icon" href="_logo.svg">' if logo else ''
    if logo and write:
        site.mkdir(parents=True, exist_ok=True); (site / '_logo.svg').write_text(logo, encoding='utf-8')
    bar = (f'<div class="bar"><a class="brand" href="{quote(fname(start))}">' + ('<img class="logo" src="_logo.svg" alt="">' if logo else '') + f'<span class="wm">{e(wiki)}</span></a><a href="_changes.html">최근 변경</a><a href="_talks.html">최근 토론</a>'
           '<a class="mi" href="_changes.html" title="최근 변경"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm1 3v4.6l3.4 2-1 1.7L11 12.7V7z"/></svg></a><a class="mi" href="_talks.html" title="최근 토론"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M3 4h13v9H7l-4 4zm5 11h9l4 4V8h-3v7H8z"/></svg></a>'
           f'<form class="sf" data-t="{e(titles)}" onsubmit="return wgo(this)">'
           f'<button type="button" class="ib" title="임의 문서"' + (' disabled' if not pool else '') + f' onclick="var h=decodeURIComponent(location.pathname.split(&quot;/&quot;).pop()),v={e(pool or "[]")}.filter(function(u){{return decodeURIComponent(u)!==h}});if(v.length)go(v[Math.floor(Math.random()*v.length)])"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M14 4h6v6l-2.3-2.3-3.2 3.2-1.4-1.4 3.2-3.2zM4 18.6 16.3 6.3l1.4 1.4L5.4 20zM13.1 14.5l1.4-1.4 3.2 3.2L20 14v6h-6l2.3-2.3zM4 5.4 5.4 4l5 5-1.4 1.4z"/></svg></button>'
           '<input name="q" type="search" enterkeyhint="search" placeholder="여기에서 검색" autocomplete="off" onkeydown="wkey(event)" onkeyup="wkey(event)" oninput="wsug(this)" onfocus="wsug(this)" onblur="wsug(this,1)">'
           '<button type="button" class="ib" title="검색" onclick="wgo(this.form,\'s\')"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M10 3a7 7 0 0 1 5.6 11.2l5.1 5.1-1.4 1.4-5.1-5.1A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"/></svg></button>'
           '<button type="button" class="ib" title="문서로 바로 가기" onclick="wgo(this.form,\'d\')"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M4 11h12.2l-5.6-5.6L12 4l8 8-8 8-1.4-1.4 5.6-5.6H4z"/></svg></button>'
           '<ul class="sug" hidden onmousedown="var l=event.target.closest(\'li\');if(l)go(l.dataset.h)"></ul></form></div>')
    # 오른쪽 칸의 최근 변경. 나무위키처럼 모든 쪽에 붙는다
    seen, items = set(), ''
    for c in recent:
        if c['doc'] in seen or c['doc'] == '대문':
            continue
        seen.add(c['doc']); ts = (' data-ts="%d"' % int(c['ts'])) if c.get('ts') else ''; items += f'<div class="ci"><a href="{c["href"]}">{e(c["doc"])}</a><span{ts}>{e(c["t"][-8:-3])}</span></div>'
        if len(seen) == 10:
            break
    side = f'<aside><div class="card"><div class="ch">최근 변경</div>{items or chr(60) + "div class=cn>아직 없습니다." + chr(60) + "/div>"}</div></aside>'
    pages = {}; edits = {}; back = {}

    def page(file, title, content, base=None, tab='', sub='', mod=''):
        btns = ''
        if base:
            btns = '<div class="btns">' + ''.join(
                f'<a class="{"on" if tab == t else ""}" href="{quote(fname(base, t))}">{label}</a>'
                for t, label in (('', '문서'), ('토론', '토론'), ('역사', '역사'), ('역링크', '역링크'))) + '</div>'
        inner = (f'<div class="head"><div><h1>{e(title)}{sub}</h1>' + (f'<div class="mod">최근 수정 시각: {e(mod)}</div>' if mod else '')
                 + f'</div>{btns}</div>{content}')
        pages[file] = (title, inner)
        doc = f"""<!doctype html><html lang="ko">{HEAD}
<title>{e(title)} - {e(wiki)}</title>{icon}<style>{css}</style>
{bar}{top}
<div class="wrap"><main>{inner}</main>{side}</div>
<footer>{DISCLAIMER}</footer><script>function go(u){{location.href=u}}{SEARCH}</script>{NAV}{TIP}{ACK}{inject}</html>"""
        if store is not None:
            store[file] = doc
        if write:
            (site / file).write_text(doc, encoding='utf-8')

    for n, d in docs.items():
        meta, base = d['meta'], d['base']
        cat = ('<div class="cat">분류: ' + ' | '.join(f'<a href="{quote(cat_file(c.strip()))}">{e(c.strip())}</a>' for c in meta['category'].split(',') if c.strip()) + '</div>') if meta.get('category') else ''
        if d['rev']:
            page(fname(n), base, f'<div class="box">이 문서의 {e(d["rev"])} 판입니다. 최신 판과 내용이 다를 수 있습니다.</div>' + R(d['body']),
                 base, sub=f' <small>({e(d["rev"])} 판)</small>')
            continue
        if n == '대문':
            body = '<div class="cat">분류: ' + e(wiki) + '</div>' + front(docs, recent, project)
        elif meta.get('deleted'):
            body = f'<div class="box"><b>이 문서는 삭제되었습니다.</b><br>{e(meta["deleted"])}</div>'
        else:
            body = cat + (NOTE_CASE if meta.get('type') == '사건' else '') + R(d['body'])
        page(fname(n), f'{wiki}:대문' if n == '대문' else n, body, n, mod=meta.get('modified', ''))
        page(fname(n, '토론'), n, (talk_html(d['토론'], docs, plain_inline(docs)) or R(d['토론'], False)) if d['토론'].strip() else '<h2>토론</h2><p>진행 중인 토론이 없습니다.</p>',
             n, '토론', ' <small>(토론)</small>')
        H = d['history']                                   # 새 판이 먼저다. [판, 시각, 편집자, 변화, 요약]
        text_of = lambda k: d['body'] if k == 0 else docs[f'{n}@{H[k][0]}']['body'] if f'{n}@{H[k][0]}' in docs else None
        rows = ''
        for k, r in enumerate(H):
            now, old = text_of(k), text_of(k + 1) if k + 1 < len(H) else None
            links = [f'<a href="{quote(fname(f"{n}@{r[0]}"))}">보기</a>' if f'{n}@{r[0]}' in docs else '보기']
            if now is not None and old is not None:
                page(fname(f'{n}@{r[0]}', '비교'), n, diff_html(old, now), n, '역사', f' <small>({e(H[k + 1][0])} → {e(r[0])} 비교)</small>')
                links.append(f'<a href="{quote(fname(f"{n}@{r[0]}", "비교"))}">비교</a>')
            who = re.sub(r'[\\/:*?"<>|]', '', r[2]).strip()
            if who:
                edits.setdefault(who, []).append((r[1], n, r[0], r[3], r[4]))
            rows += (f'<li>{e(r[1])} <span class="mute">({" | ".join(links)})</span> <b>{e(r[0])}</b> <span class="{"minus" if r[3].startswith("-") else "plus"}">({e(r[3])})</span> '
                     + (f'<a href="{quote(fname("기여." + who))}">{e(r[2])}</a>' if who else e(r[2])) + (f' <span class="mute">({e(r[4])})</span>' if r[4] else '') + '</li>')
        page(fname(n, '역사'), n, f'<ul class="hist">{rows}</ul>' if rows else '<p>기록이 없습니다.</p>', n, '역사', ' <small>(문서 역사)</small>')
        for target in set(re.findall(r'\[\[([^\]|#]+)', d['body'])):
            if target.strip() != n:
                back.setdefault(target.strip(), set()).add(n)

    for n, d in docs.items():                              # 역링크: 이 문서로 오는 링크가 있는 문서들
        if not d['rev']:
            ns = sorted(back.get(n, ()))
            page(fname(n, '역링크'), n, (f'<p>이 문서를 가리키는 문서 {len(ns)}개</p><ul>' + ''.join(f'<li><a href="{quote(fname(x))}">{e(x)}</a></li>' for x in ns) + '</ul>')
                 if ns else '<p>이 문서를 가리키는 문서가 없습니다.</p>', n, '역링크', ' <small>(역링크)</small>')
    for who, items in edits.items():                       # 편집자의 기여 목록
        page(fname('기여.' + who), f'{who}의 기여 목록', '<table class="t"><tr><th>시각</th><th>문서</th><th>판</th><th>변화</th><th>요약</th></tr>' + ''.join(
            f'<tr><td>{e(a)}</td><td><a href="{quote(fname(doc))}">{e(doc)}</a></td><td>{e(rev)}</td><td class="{"minus" if dl.startswith("-") else "plus"}">({e(dl)})</td><td>{e(sm)}</td></tr>'
            for a, doc, rev, dl, sm in sorted(items, reverse=True)) + '</table>')
    strip = lambda s: re.sub(r'\s+', ' ', re.sub(r'[#*|`>]|^:::.*$|!\[[^\]]*\]\([^)]*\)', ' ', re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', s), flags=re.M))
    index = json.dumps([dict(t=n, h=quote(fname(n)), x=strip(d['body'] + ' ' + d['토론'])) for n, d in docs.items() if not d['rev'] and n != '대문' and not d['meta'].get('deleted')],
                       ensure_ascii=False).replace('</', '<\\/')
    page('_search.html', '검색', '<form class="sform" id="sform" onsubmit="return wsub(this)">'
         '<select name="w"><option value="">제목/내용</option><option value="t">제목</option><option value="x">내용</option></select>'
         '<input name="q" type="search" enterkeyhint="search" autocomplete="off" onkeydown="wkey(event)" onkeyup="wkey(event)"><button>검색</button></form>'
         '<div class="sgo" id="sgo" hidden></div><p class="scount" id="scount"></p>'
         f'<div id="sres"></div><script type="application/json" id="sidx">{index}</script><script type="application/json" id="stitles">{titles.replace("</", "<\\/")}</script>'
         '<script>addEventListener("DOMContentLoaded",function(){var f=function(){wsearch(decodeURIComponent(location.hash.slice(1)))};f();addEventListener("hashchange",f)})</script>')

    cats = {}
    for n, d in docs.items():
        if not d['rev']:
            for c in d['meta'].get('category', '').split(','):
                if c.strip():
                    cats.setdefault(c.strip(), []).append(n)
    for c, ns in cats.items():        # 분류를 누르면 그 분류에 속한 문서가 나온다
        page(cat_file(c), f'분류:{c}', f'<h2>"{e(c)}" 분류에 속하는 문서</h2><p>전체 {len(ns)}개 문서</p><ul>'
             + ''.join(f'<li><a href="{quote(fname(n))}">{e(n)}</a></li>' for n in sorted(ns)) + '</ul>')
    page('_cats.html', '분류 전체', f'<p>전체 {len(cats)}개 분류</p><ul>' + ''.join(
        f'<li><a href="{quote(cat_file(c))}">{e(c)}</a> <span class="mute">({len(ns)})</span></li>' for c, ns in sorted(cats.items(), key=lambda x: (-len(x[1]), x[0]))) + '</ul>')
    kinds = {}
    for n, d in docs.items():
        if not d['rev'] and n != '대문' and not d['meta'].get('deleted'):
            kinds.setdefault(d['meta'].get('type') or '기타', []).append(n)
    for k, ns in kinds.items():
        page(fname('종류.' + k), f'종류:{k}', f'<p>전체 {len(ns)}개 문서</p><ul>' + ''.join(f'<li><a href="{quote(fname(n))}">{e(n)}</a></li>' for n in sorted(ns)) + '</ul>')
    shots = {}                                              # 사진마다 문서 하나. 본문의 사진을 누르면 여기로 온다
    for n, d in docs.items():
        if not d['rev']:
            for cap, f in re.findall(r'^!\[(.*?)\]\((.+?)\)[ \t]*$', d['body'], re.M):
                if (project / 'docs' / 'img' / pub_name(project / 'docs' / 'img', f)).is_file():
                    shots.setdefault(f, []).append((n, cap))
    for f, uses in shots.items():
        g = pub_name(project / 'docs' / 'img', f); p = project / 'docs' / 'img' / g; head = p.read_bytes()[:24]
        size = (f'{int.from_bytes(head[16:20], "big")} × {int.from_bytes(head[20:24], "big")} 픽셀, ' if head[:8] == b'\x89PNG\r\n\x1a\n' else '') + f'{p.stat().st_size // 1024:,} KB'
        (site / 'img').mkdir(exist_ok=True)
        if not (site / 'img' / g).is_file():
            place(p, site / 'img' / g)
        page(fname('파일.' + f), f'파일:{f}',
             f'<figure class="file"><img src="img/{quote(g)}" alt=""></figure>'
             f'<table class="t"><tr><th>설명</th><td>{"<br>".join(dict.fromkeys(e(c) for _, c in uses if c))}</td></tr>'
             f'<tr><th>크기</th><td>{size}</td></tr><tr><th>올린 시각</th><td>{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))}</td></tr></table>'
             '<h2>이 파일을 사용하는 문서</h2><ul>' + ''.join(f'<li><a href="{quote(fname(n))}">{e(n)}</a></li>' for n in dict.fromkeys(n for n, _ in uses)) + '</ul>')
    page('_none.html', '문서 없음', '<p>해당 문서를 찾을 수 없습니다.</p>'
         '<script>var q=decodeURIComponent(location.hash.slice(1));if(q){document.querySelector("h1").textContent=q;document.title=q}</script>')
    rows = ''.join(f'<tr><td>{e(c["t"])}</td><td><a href="{c["href"]}">{e(c["doc"])}</a></td><td>{e(c["kind"])}</td>'
                   + (f'<td class="{"minus" if c["delta"] < 0 else "plus"}">({c["delta"]:+d})</td>' if 'delta' in c else '<td></td>') + '</tr>' for c in recent[:100])
    page('_changes.html', '최근 변경', f'<table class="t"><tr><th>시각</th><th>문서</th><th>종류</th><th>변화</th></tr>{rows}</table>' if rows else '<p>아직 변경이 없습니다.</p>')
    talks = ''.join(f'<tr><td><a href="{quote(fname(n, "토론"))}">{e(n)}</a></td><td>{d["토론"].count("**") // 2}개의 글</td></tr>'
                    for n, d in docs.items() if not d['rev'] and d['토론'].strip())
    page('_guide.html', f'{wiki}:이용 안내', f'<div class="cat">분류: {e(wiki)}의 도움말</div>' + ci + R(GUIDE))
    day = str((json.loads((project / 'wiki.json').read_text(encoding='utf-8')) if (project / 'wiki.json').is_file() else {}).get('created', '')) or time.strftime('%Y-%m-%d')
    page('_tech.html', f'{wiki}:작동 방식', f'<div class="cat">분류: {e(wiki)}의 도움말</div>' + ci + R(tech(json.loads((project / 'wiki.json').read_text(encoding='utf-8-sig')) if (project / 'wiki.json').is_file() else {})))
    page('_records.html', f'{wiki}:처리 내역', f'<div class="cat">분류: {e(wiki)}의 운영</div>' + R(ops_records(project, docs)))
    page('_staff.html', f'{wiki}:운영진', f'<div class="cat">분류: {e(wiki)}의 운영</div>' + ci + R(staff(day[:4], day, season)))
    page('_talks.html', '최근 토론', f'<table class="t"><tr><th>문서</th><th>토론</th></tr>{talks}</table>' if talks else '<p>아직 토론이 없습니다.</p>')
    if write:
        (site / 'index.html').write_text(f'<!doctype html>{HEAD}<meta http-equiv="refresh" content="0;url={quote(fname(start))}">', encoding='utf-8')

    if single:
        import base64, mimetypes

        def embed(m):                                    # 사진을 파일 안에 넣는다
            f = site / 'img' / unquote(m[1])
            return f'src="data:{mimetypes.guess_type(f.name)[0] or "image/png"};base64,{base64.b64encode(f.read_bytes()).decode()}"'
        data = json.dumps({f: dict(t=t, h=re.sub(r'src="img/([^"]+)"', embed, h)) for f, (t, h) in pages.items()}, ensure_ascii=False).replace('</', '<\\/')
        consts = f'const START={json.dumps(fname(start), ensure_ascii=False)},WIKI={json.dumps(wiki, ensure_ascii=False)};'
        (project / 'dist').mkdir(exist_ok=True)
        (project / 'dist' / f'{wiki}.html').write_text(f"""<!doctype html><html lang="ko">{HEAD}
<title>{e(wiki)}</title>{icon}<style>{css}</style>
{bar}{top}
<div class="wrap"><main></main>{side}</div>
<footer>{DISCLAIMER}</footer>
<script type="application/json" id="pages">{data}</script>
<script>{consts}{SEARCH}{ROUTER}</script>{NAV}{TIP}{ACK}</html>""", encoding='utf-8')

    if text:
        def dump(d):
            s = f'===== 문서: {d["name"]} =====\n{d["body"].strip()}\n'
            for k in ('토론', '역사'):
                if d[k].strip():
                    s += f'\n--- {k} ---\n{d[k].strip()}\n'
            return s
        for old in project.glob('reader_start*.txt'):
            old.unlink()
        ss = [s for s in starts(docs) if s != '대문']
        for s in ss:
            (project / f'reader_start_{s.replace(" ", "_")}.txt').write_text(dump(docs[s]), encoding='utf-8')
        (project / 'reader_all.txt').write_text('\n\n'.join(dump(docs[n]) for n in [start] + [x for x in docs if x != start]), encoding='utf-8')
    return site, len(docs)


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):   # 콘솔 기본 인코딩(cp949)이면 에이전트가 읽을 때 깨진다
        o.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    root = a[0] if a and not a[0].startswith('-') else Path(__file__).resolve().parent.parent   # 폴더를 안 주면 이 스크립트가 든 위키
    site, n = build(root, text='--text' in a, single='--single' in a)
    print(f'문서 {n}개 -> {site / "index.html"}')
    if '--single' in a:
        print(f'한 파일 -> {Path(root, "dist", wiki_name(root) + ".html")}')
