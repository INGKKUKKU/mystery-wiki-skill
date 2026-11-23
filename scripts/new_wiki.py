#!/usr/bin/env python3
"""새 위키 폴더를 만든다. 또는 이미 있는 위키의 틀(tools/)을 스킬의 최신 것으로 바꾼다.

사용법: python new_wiki.py <폴더> --name 위키이름 [--agent claude|codex]
                                                 새 위키 만들기 (폴더가 비어 있거나 없어야 한다).
                                                 --agent 를 안 주면 지금 대화하는 앱 쪽, 그다음 찾을 수 있는 쪽을 쓴다
        python new_wiki.py <폴더> --update-tools     틀만 다시 넣기 (문서와 설계는 건드리지 않는다)
"""
import sys, json, shutil, subprocess, datetime
from pathlib import Path

VERSION = '259'                                    # assets/ 를 고치면 올린다
ASSETS = Path(__file__).resolve().parent.parent / 'assets'
sys.dont_write_bytecode = True                   # 스킬 폴더에 __pycache__ 를 남기지 않는다
sys.path.insert(0, str(ASSETS / 'tools'))
from check import tools_hash                     # 지문 계산은 검사 스크립트와 같은 것을 쓴다

PHOTO_STYLE = ('그 사건이 있었던 연대에 흔하던 카메라로 찍은 기록 사진. 그 연대 사진의 화질과 색 그대로. '
               '주문에 없는 글자와 로고 없음. 영화 같은 조명이나 연출 없음.')
OLD_PHOTO_STYLES = ('그 사건이 있었던 연대에 흔하던 카메라로 보통 사람이 찍은 평범한 기록 사진. 그 연대 사진의 화질과 색 그대로, 밋밋한 자연광, 눈높이의 무심한 구도. 주문에 없는 글자와 로고 없음. 영화 같은 조명이나 연출 없음. 찍으려던 것은 화면 가운데에 또렷하게. 사람이 나오면 실제 누구도 닮지 않은 평범한 사람으로.',
                    '그 사건이 있었던 연대에 흔하던 카메라로 찍은 기록 사진. 그 연대 사진의 화질과 색 그대로. 주문에 없는 글자와 로고 없음. 영화 같은 조명이나 연출 없음. 찍으려던 것은 화면 가운데에 또렷하게. 사람이 나오면 실제 누구도 닮지 않게.',
                    '그 사건이 있었던 연대에 흔하던 카메라로 찍은 기록 사진. 그 연대 사진의 화질과 색 그대로. 주문에 없는 글자와 로고 없음. 영화 같은 조명이나 연출 없음. 사람이 나오면 실제 누구도 닮지 않게.')      # 예전 판의 기본 사진 문장
TRUTH = """# 세계

## 배경
(도시, 기관, 여러 사건이 함께 쓰는 장소와 인물을 적는다. 실존하는 이름은 쓰지 않는다.)

## 위키 관습
사건이 달라도 같아야 하는 것들이다. 첫 사건에서 정해 적고, 뒤 사건은 그대로 따른다.

- 날짜 표기: (예: 본문은 "2009년 11월 14일", "오후 11시 40분". 역사와 토론의 시각은 "2024-03-02 04:11")
- 편집자 닉네임: (넷에서 여섯 명. 이름과 성격 한 줄씩. 문서 머리말의 edit 와 토론에 이 이름들을 돌려 쓴다)
- 분류 이름: (지금까지 쓴 분류 목록)
- 삭제·임시 조치 사유 문구: (지금까지 쓴 문구)
- 토론 말투: (예: 짧은 존댓말)

## 사건 사이의 관계
| 사건 | 사건 | 관계 | 내용 |
|---|---|---|---|

## 이미 쓴 것
새 사건은 이 표의 사건들과 무슨 일, 어디서, 누구에게, 무엇이 어긋났나 가운데 둘 이상이 겹치지 않게 한다.

| 사건 | 무슨 일 | 어디서 | 누구에게 | 언제 | 무엇이 어긋났나 | 단서의 종류 | 진상의 종류 |
|---|---|---|---|---|---|---|---|
"""
README = """# {name}

mystery-wiki 스킬로 만든 가상 사건 위키다. 실린 사건·인물·지명·단체는 모두 창작이다.

- docs/   위키 문서
- plan/   설계. 진상이 들어 있다 (스포일러)
- tools/  화면 틀, 검사 스크립트, 문서 뼈대. 사건을 더할 때는 고치지 않는다
- 라이브 화면: `live.bat`을 두 번 누르거나 `python tools/live.py` (브라우저에서 버튼으로 사건을 연다)
- .live/  라이브 화면의 기록. agent.log 에 진상이 들어 있다 (스포일러)
- site/   공개용 화면. `python tools/build.py`
- dist/   한 파일로 묶은 공개용. `python tools/build.py --single`
- admin/  운영용 화면. `python tools/admin.py`

남에게 보여 줄 때는 site/ 폴더나 dist/ 의 파일 하나만 내보낸다. 이 폴더를 통째로 올리거나 공개 저장소에 올리면 진상이 공개된다.
"""


def git(root, *args):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True).returncode == 0
    except OSError:
        return False


def copy_tools(root):
    """틀을 넣고 그 지문을 돌려준다."""
    tools = root / 'tools'
    for d in ('templates', 'guide'):
        shutil.rmtree(tools / d, ignore_errors=True)
    tools.mkdir(exist_ok=True)
    for f in (ASSETS / 'tools').glob('*.py'):
        shutil.copy(f, tools / f.name)
    shutil.copytree(ASSETS / 'templates', tools / 'templates')
    (tools / 'guide').mkdir()
    for f in ('grading.md', 'verdict.md', 'images.md'):
        shutil.copy(ASSETS.parent / 'references' / f, tools / 'guide' / f)
    shutil.rmtree(tools / '__pycache__', ignore_errors=True)
    return tools_hash(tools)


def write_conf(conf, c):
    conf.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):   # 콘솔 기본 인코딩(cp949)이면 에이전트가 읽을 때 깨진다
        o.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if not a or a[0].startswith('-') or ('--name' in a) == ('--update-tools' in a):
        sys.exit(__doc__)
    root, conf = Path(a[0]), Path(a[0], 'wiki.json')
    if '--update-tools' in a:
        if not conf.is_file():
            sys.exit(f'{root} 에 wiki.json 이 없습니다. 위키 폴더가 아닙니다.')
        sys.path.insert(0, str(ASSETS / 'tools')); import store
        guard = store.hold(root / '.live' / 'server.lock')      # 켜진 서버는 옛 틀을 메모리에 들고 있다. 틀만 바뀌면 옛 코드와 새 파일이 섞인다
        if not guard:
            sys.exit(f'{root} 의 라이브 서버가 켜져 있습니다. 서버를 끈 뒤에 틀을 바꿉니다.')
        c = json.loads(conf.read_text(encoding='utf-8-sig')); old = c.get('tools_version')
        if (root / 'tools').is_dir():                           # 새 판이 이상하면 되돌릴 수 있게 옛 틀을 남긴다
            keep = root / '.live' / 'tools-backup' / f'{old or "옛판"}-{datetime.datetime.now():%Y%m%d-%H%M%S}'
            shutil.copytree(root / 'tools', keep, ignore=shutil.ignore_patterns('__pycache__'))
            for stale in sorted((root / '.live' / 'tools-backup').iterdir())[:-3]:
                shutil.rmtree(stale, ignore_errors=True)
        c.update(tools_version=VERSION, tools_hash=copy_tools(root)); c['photo_style'] = PHOTO_STYLE if c.get('photo_style') in (None, *OLD_PHOTO_STYLES) else c['photo_style']; c.setdefault('agent', 'claude')
        write_conf(conf, c)
        print(f'틀을 {old} -> {VERSION} 판으로 바꿨습니다. tools/build.py 와 tools/check.py 를 다시 돌려 확인합니다.')
        sys.exit()
    if conf.is_file():
        sys.exit(f'{root} 는 이미 위키입니다. 새로 만들지 않고 여기에 사건을 더합니다.')
    if root.exists() and any(root.iterdir()):
        sys.exit(f'{root} 가 비어 있지 않습니다. 빈 폴더나 새 폴더 이름을 줍니다.')
    name = a[a.index('--name') + 1]
    sys.path.insert(0, str(ASSETS / 'tools')); import agents
    agent = a[a.index('--agent') + 1] if '--agent' in a else agents.guess()
    if agent not in agents.NAMES:
        sys.exit(f'모르는 에이전트: {agent} (claude, codex 중 하나)')
    for d in ('plan', 'docs/img'):
        (root / d).mkdir(parents=True, exist_ok=True)
    write_conf(conf, dict(name=name, tools_version=VERSION, tools_hash=copy_tools(root), created=str(datetime.date.today()), agent=agent, quality='기본', photo_style=PHOTO_STYLE))
    (root / 'plan' / 'truth.md').write_text(TRUTH, encoding='utf-8')
    (root / 'docs' / '대문.md').write_text(f'---\nstart: true\n---\n{name}. 풀리지 않은 일들을 기록합니다.\n', encoding='utf-8')
    (root / 'README.md').write_text(README.format(name=name), encoding='utf-8')
    # 두 번 누르면 라이브 화면이 켜지는 파일. 그 뒤로는 에이전트와 대화하지 않고 브라우저에서 한다
    (root / 'live.bat').write_text('@echo off\r\ncd /d "%~dp0"\r\npython tools\\live.py\r\npause\r\n', encoding='ascii', newline='')
    (root / '.gitignore').write_text('site/\ndist/\nadmin/\n.live/\nreader_*.txt\n__pycache__/\ndocs/img/\nplan/*/img/\n', encoding='utf-8')
    saved = git(root, 'init', '-q') and git(root, 'add', '-A') and git(root, 'commit', '-q', '-m', f'{name} 만들기 (틀 {VERSION}판)')
    print(f'{name} -> {root.resolve()}')
    print(agents.diagnose(agent)[1])      # 어느 에이전트를 어디서 찾았는지, 로그인이 필요한지
    print('git 저장 지점을 만들었습니다.' if saved else 'git 저장은 하지 못했습니다 (git이 없거나 사용자 설정이 없음). 나머지는 정상입니다.')
