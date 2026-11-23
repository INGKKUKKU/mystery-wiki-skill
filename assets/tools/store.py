"""위키 파일 쓰기. 쓰다 끊겨도 반쪽 파일이 남지 않게 같은 폴더의 임시 파일에 다 쓴 뒤 한 번에 바꾼다.
문서, 설계, 상태, 기록을 쓰는 곳은 모두 이것을 거친다."""
import json
import os
import threading
import time
from pathlib import Path


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}-{threading.get_ident()}.tmp')
    # 글은 예전 write_text 와 같은 줄바꿈으로 쓴다(윈도우는 \r\n). 봉인 지문은 파일의 바이트로 뜨므로 줄바꿈이 바뀌면 진상이 바뀐 것으로 보인다
    data = content.replace('\n', os.linesep).encode('utf-8') if isinstance(content, str) else content
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # 윈도우에서는 다른 쪽이 그 파일을 읽는 동안 잠깐 바꿀 수 없다
            time.sleep(0.05)
    try:
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_json(path, obj, indent=None):
    write(path, json.dumps(obj, ensure_ascii=False, indent=indent))


SNAP_DIRS = ('docs', 'history', 'plan')       # 한 차례가 바꾸는 곳. 사진(img)은 크고 되돌릴 일이 없어 빼고, 되돌릴 때 지금 것을 그대로 둔다
KEEP = 3


def _skip_img(folder, names):
    return [n for n in names if n == 'img']


def snapshot(root, label):
    """한 차례를 시작하기 전의 문서·역사·설계를 .live/snapshots/ 에 남긴다. 운영 메뉴의 되돌리기가 이것을 쓴다."""
    root = Path(root); base = root / '.live' / 'snapshots'
    dst = base / time.strftime('%Y%m%d-%H%M%S')
    while dst.exists():
        dst = dst.with_name(dst.name + '_')
    tmp = dst.with_name(dst.name + '.tmp')
    for d in SNAP_DIRS:
        if (root / d).is_dir():
            import shutil
            shutil.copytree(root / d, tmp / d, ignore=_skip_img)
    write_json(tmp / 'meta.json', dict(label=label, time=time.strftime('%Y-%m-%d %H:%M:%S')))
    os.replace(tmp, dst)                       # 다 복사된 것만 스냅샷으로 보인다
    for old in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.endswith('.tmp') and not p.name.startswith('_'))[:-KEEP]:
        import shutil
        shutil.rmtree(old, ignore_errors=True)
    return dst


def snapshots(root):
    base = Path(root) / '.live' / 'snapshots'
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / 'meta.json').is_file() and not p.name.startswith('_')) if base.is_dir() else []


def latest_snapshot(root):
    snaps = snapshots(root)
    return snaps[-1] if snaps else None


def restore(root):
    """가장 최근 스냅샷으로 되돌린다. 지금 것은 .live/snapshots/_되돌리기 전-<시각>/ 에 남겨서 되돌리기도 되돌릴 수 있다(최근 3개).
    사진 폴더(docs/img, plan/<사건>/img)는 지금 것을 그대로 쓴다. 그 차례가 새로 연 사건의 사진은 따라오지 않는다.
    두 단계로 한다. 먼저 되돌린 폴더를 모두 옆에 만들고, 다 되면 바꿔 끼운다. 바꿔 끼우다 실패하면 바꾼 것을 원래대로 돌린다.
    -> 되돌린 스냅샷의 이름표, 없으면 None. 실패하면 OSError(위키는 되돌리기 전 그대로)."""
    import shutil
    root = Path(root); snap = latest_snapshot(root)
    if not snap:
        return None
    label = json.loads((snap / 'meta.json').read_text(encoding='utf-8')).get('label', '')
    base = root / '.live' / 'snapshots'
    keep = base / f'_되돌리기 전-{time.strftime("%Y%m%d-%H%M%S")}'
    while keep.exists():
        keep = keep.with_name(keep.name + '_')
    staged = {d: root / f'.{d}.restoring' for d in SNAP_DIRS}
    try:                                       # 1. 옆에 만든다. 여기서 실패하면 위키는 손대지 않은 그대로다
        for d, new in staged.items():
            shutil.rmtree(new, ignore_errors=True)
            shutil.copytree(snap / d, new) if (snap / d).is_dir() else new.mkdir()
            if (root / d).is_dir():            # 사진은 지금 것을 옮겨 온다. 되돌린 쪽에 없는 사건의 사진은 옮기지 않는다
                for img in [root / d / 'img'] + list((root / d).glob('*/img')):
                    target = new / img.relative_to(root / d)
                    if img.is_dir() and (target.parent == new or target.parent.is_dir()):
                        shutil.rmtree(target, ignore_errors=True); shutil.copytree(img, target)
    except OSError:
        for new in staged.values():
            shutil.rmtree(new, ignore_errors=True)
        raise
    done = []
    try:                                       # 2. 바꿔 끼운다
        keep.mkdir(parents=True)
        for d, new in staged.items():
            if (root / d).is_dir():
                os.replace(root / d, keep / d)
            done.append(d)
            os.replace(new, root / d)
    except OSError:
        for d in reversed(done):               # 바꾼 것을 원래대로
            if (keep / d).is_dir():
                if (root / d).is_dir():
                    shutil.rmtree(root / d, ignore_errors=True)
                os.replace(keep / d, root / d)
        for new in staged.values():
            shutil.rmtree(new, ignore_errors=True)
        shutil.rmtree(keep, ignore_errors=True)
        raise
    for img in [keep / d / 'img' for d in SNAP_DIRS] + list(keep.glob('*/*/img')):      # 사진은 되돌린 쪽으로 옮겨 갔다. 남긴 것에서는 뺀다
        shutil.rmtree(img, ignore_errors=True)
    shutil.rmtree(snap)                        # 같은 스냅샷으로 두 번 되돌리지 않는다. 다음 되돌리기는 그 앞의 것으로 간다
    for old in sorted(p for p in base.iterdir() if p.name.startswith('_되돌리기 전'))[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return label


def hold(path):
    """이 프로세스만 쥐는 잠금. 쥐면 파일 핸들(닫지 말고 들고 있는다), 다른 프로세스가 쥐고 있으면 None.
    프로세스가 죽으면 운영체제가 풀어 주므로 남은 잠금 파일 때문에 막히는 일이 없다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None
