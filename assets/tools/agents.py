"""뒤에서 부를 에이전트 CLI(claude, codex)를 찾고, 부를 때 넘길 환경을 만든다. live.py와 fast.py가 같이 쓴다.

찾는 차례
1. Codex 앱 안에서 켰으면 앱이 알려 주는 CLI (CODEX_APP_RUNTIME_CLI_PATH)
2. PATH에 있는 독립형 CLI (예전과 같다)
3. 데스크톱 앱이 깔아 둔 CLI
   - Claude 데스크톱 앱: Code 탭을 쓰면 claude-code/<판>/ 아래에 claude를 받아 둔다
   - Codex 앱(ChatGPT 데스크톱의 Codex): 앱 안에 codex가 들어 있다
로그인은 CLI 자신의 것을 쓴다. 앱의 대화 세션이나 인증 통로를 빌려 쓰지 않는다.
"""
import glob
import json
import os
import shutil
import subprocess
import threading
import sys
from pathlib import Path

NAMES = ('claude', 'codex')
# 별도 CLI에 부모 앱의 실행 연결을 넘기면 도구 실행이 실패한다. 다른 에이전트 안에서 켰을 때 섞이지 않게도 뺀다
APP_SESSION_ENV = ('CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_WINDOWS_REGISTERED_CORE', 'CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY')
_found = {}


def _newest(paths):
    paths = [p for p in paths if os.path.isfile(p)]
    return max(paths, key=os.path.getmtime) if paths else None


def _codex_package():
    """윈도우 스토어로 깔린 Codex 앱의 폴더. WindowsApps는 목록을 볼 수 없어 패키지 정보로 묻는다."""
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-AppxPackage -Name OpenAI.Codex | Select-Object -Last 1).InstallLocation'],
                           capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def bundled(agent):
    """데스크톱 앱이 깔아 둔 CLI. 없으면 None."""
    home = Path.home()
    if agent == 'claude':
        bases = [os.environ.get('APPDATA', ''), str(home / 'Library' / 'Application Support'), str(home / '.config')]
        exe = 'claude.exe' if os.name == 'nt' else 'claude'
        return _newest([p for b in bases if b for pat in ('*', '*/*') for p in glob.glob(os.path.join(b, 'Claude', 'claude-code', pat, exe))])
    if os.name == 'nt':
        loc = _codex_package()
        return _newest([os.path.join(loc, 'app', 'resources', 'codex.exe')]) if loc else None
    # ponytail: 맥 Codex 앱 안의 경로는 이 컴퓨터에서 확인하지 못했다. 다르면 PATH의 codex를 쓴다
    return _newest(glob.glob('/Applications/*Codex*.app/Contents/Resources/codex') + glob.glob(str(home / 'Applications/*Codex*.app/Contents/Resources/codex')))


def find(agent):
    """부를 CLI의 경로. 못 찾으면 None. 찾은 것만 기억한다(나중에 설치하면 다시 찾는다)."""
    if agent == 'codex':
        app = os.environ.get('CODEX_APP_RUNTIME_CLI_PATH', '')
        if app and os.path.isfile(app):
            return app
    if agent not in _found:
        hit = shutil.which(agent) or bundled(agent)
        if not hit:
            return None
        _found[agent] = hit
    return _found[agent]


def env():
    """에이전트에게 넘길 환경. 부모 에이전트 세션의 변수와 앱 실행 연결은 뺀다."""
    out = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDECODE', 'CLAUDE_CODE_')) and k not in APP_SESSION_ENV}
    out['PYTHONUTF8'] = '1'
    return out


PROC = {}      # 지금 도는 에이전트 프로세스. 운영 메뉴의 멈추기가 전부 끝낼 수 있게 모아 둔다
PROC_LOCK = threading.Lock()
STOP = threading.Event()


def kill(p):
    """에이전트와 그 아래 프로세스까지 끝낸다."""
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
        else:
            p.kill()
    except OSError:
        pass


def stop_all():
    STOP.set()
    with PROC_LOCK:
        procs = list(PROC.values())
    for p in procs:
        kill(p)


def spawn(cmd, prompt, cwd, timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, track=True):
    """에이전트 CLI를 한 번 돌린다. 프롬프트는 표준 입력으로 준다. 멈추기와 시간 초과는 가지째 끝낸다.
    -> (종료 코드, 표준 출력, 표준 오류, 까닭). 까닭은 ''(정상 종료), 'timeout', 'stopped' 가운데 하나. 실행 자체를 못 하면 OSError."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, cwd=cwd, env=env())
    key = object()
    if track:
        with PROC_LOCK:
            PROC[key] = p
        if STOP.is_set():
            kill(p)
    try:
        so, se = p.communicate(prompt.encode('utf-8'), timeout=timeout)
    except subprocess.TimeoutExpired:
        kill(p)                     # 윈도우에서는 자식의 자식이 파이프를 쥐고 있으면 끝없이 기다린다. 가지째 끝낸다
        try:
            so, se = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            so, se = b'', b''
        return p.returncode, so or b'', se or b'', 'timeout'
    finally:
        if track:
            with PROC_LOCK:
                PROC.pop(key, None)
    # 멈춤이 눌렸어도 제대로 끝난 호출의 답은 버리지 않는다(잠깐 멈춤은 돌던 호출을 끝까지 기다린다). 끊긴 것만 멈춘 것으로 친다
    return p.returncode, so or b'', se or b'', 'stopped' if track and STOP.is_set() and p.returncode != 0 else ''


def why(text, agent=''):
    """에이전트가 실패했을 때 화면에 보여 줄 이유. 기록 전체는 진상이 섞여 있을 수 있어 보여 주지 않고 종류만 가린다."""
    t = text.lower()
    if 'model' in t and ('not supported' in t or 'not_found' in t or 'not found' in t):
        return '설정한 모델을 이 에이전트에서 쓸 수 없습니다. 설정 창에서 그 단계의 모델을 처음 값으로 돌립니다'
    if any(k in t for k in ('login', 'log in', 'authenticat', 'unauthorized', 'api key', 'not logged')):
        exe = find(agent) if agent else None
        return '에이전트 로그인이 필요합니다. ' + (f'터미널에서 `{login_command(agent, exe)}` 로 로그인합니다' if exe else '터미널에서 에이전트를 한 번 실행해 로그인합니다')
    if any(k in t for k in ('usage limit', 'rate limit', 'quota', 'limit reached', 'credit')):
        return '에이전트 사용량 한도에 걸렸습니다'
    return '에이전트가 오류로 끝났습니다'


def logged_in(agent, exe):
    """CLI 자신의 로그인 상태. 알 수 없으면 None(그때는 실제 호출로 시험한다)."""
    try:
        if agent == 'claude':
            r = subprocess.run([exe, 'auth', 'status'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, env=env())
            return bool(json.loads(r.stdout).get('loggedIn'))
        r = subprocess.run([exe, 'login', 'status'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, env=env())
        return r.returncode == 0 and 'logged in' in (r.stdout + r.stderr).lower()
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


def guess():
    """새 위키에 쓸 에이전트. 지금 대화하는 앱 쪽을 먼저, 그다음 찾을 수 있는 쪽."""
    first = ['codex', 'claude'] if any(k.startswith('CODEX_') for k in os.environ) and not os.environ.get('CLAUDECODE') else ['claude', 'codex']
    return next((a for a in first if find(a)), first[0])


def login_command(agent, exe):
    q = f'"{exe}"' if ' ' in exe else exe
    return f'{q} auth login' if agent == 'claude' else f'{q} login'


def diagnose(agent):
    """(준비됨, 사람에게 보일 설명). 설치·로그인 안내는 여기 한 곳에서 한다. 로그인을 대신하지 않는다."""
    exe = find(agent)
    if not exe:
        if agent == 'claude':
            return False, ('claude 명령을 찾지 못했습니다. Claude 데스크톱 앱의 Code 탭을 한 번 열어 두면 앱이 claude를 받아 두고, 그러면 저절로 찾습니다. '
                           '앱이 없으면 https://claude.com/claude-code 에서 Claude Code를 설치합니다.')
        return False, ('codex 명령을 찾지 못했습니다. Codex 앱(ChatGPT 데스크톱의 Codex)을 설치하면 앱 안의 codex를 저절로 찾습니다. '
                       '앱 없이 쓰려면 `npm install -g @openai/codex`로 설치합니다.')
    where = '' if exe == shutil.which(agent) else '앱에 든 '
    state = logged_in(agent, exe)
    if state is False:
        return False, (f'{agent}는 찾았지만({exe}) 로그인되어 있지 않습니다. 터미널에서 `{login_command(agent, exe)}` 명령으로 브라우저에서 본인 계정에 로그인한 뒤 다시 시험합니다. '
                       + ('Codex 앱에 로그인했다면 같은 로그인(~/.codex)을 쓰므로 보통 이 단계가 필요 없습니다.' if agent == 'codex'
                          else 'Claude 데스크톱 앱의 로그인은 CLI에 넘어가지 않을 수 있어 한 번 따로 로그인합니다.'))
    return True, f'{agent}: {where}{exe}' + ('' if state else ' (로그인 상태는 실제 호출로 확인합니다)')


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):
        o.reconfigure(encoding='utf-8', errors='replace')
    for a in (sys.argv[1:] or NAMES):
        print(diagnose(a)[1])
