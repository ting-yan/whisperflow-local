# -*- mode: python ; coding: utf-8 -*-
# Build: python -m PyInstaller --noconfirm --clean WhisperFlowLocal.spec
import os
import re
import shutil
import sys
from importlib.metadata import distribution, packages_distributions
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = [('config.example.json', '.'), ('icon.ico', '.')]
binaries = []
hiddenimports = ['pystray._win32']
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tokenizers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('opencc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['scripts/pyi_rth_no_av.py'],
    # PyAV (and the FFmpeg + x264/x265 codec DLLs it carries) is only used by
    # faster-whisper to decode audio files; the app passes numpy arrays. The
    # runtime hook above stands in for it. See scripts/pyi_rth_no_av.py.
    excludes=['av'],
    # LGPL-3.0: pystray must stay replaceable by the user, so ship it as
    # plain .py files in _internal/pystray/ rather than inside the archive.
    module_collection_mode={'pystray': 'py'},
    noarchive=False,
    optimize=0,
)

# DLLs that ride along in dependency wheels but this build never loads:
#   cudnn64_9.dll   - NVIDIA cuDNN (proprietary), bundled in the ctranslate2
#                     wheel; useless without cuBLAS, and the exe is CPU-only
#   *-asio.dll      - PortAudio built with Steinberg's ASIO SDK; sounddevice
#                     only loads it when SD_ENABLE_ASIO is set
_DROP = ('cudnn64_9.dll', 'libportaudio64bit-asio.dll')
_keep = lambda entry: os.path.basename(entry[0]).lower() not in _DROP
a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhisperFlowLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WhisperFlowLocal',
)


# --- Third-party licenses ----------------------------------------------------
# Ship every bundled package's own license files next to the exe, in
# licenses/<package>/, plus an index. Packages whose wheel carries no license
# file (CTranslate2) and native pieces with no package of their own (PortAudio,
# Intel OpenMP) come from licenses-extra/. Python's LICENSE.txt covers the
# interpreter and what it bundles (OpenSSL, libffi, Tcl/Tk, SQLite, zlib).
_out = Path(DISTPATH) / 'WhisperFlowLocal' / 'licenses'
shutil.rmtree(_out, ignore_errors=True)
_out.mkdir(parents=True)
_tops = {e[0].split('.')[0] for e in a.pure}
_tops |= {re.split(r'[\\/]', e[0])[0] for e in a.binaries + a.datas}
_pkg_map = packages_distributions()
_dists = sorted({d for t in _tops - set(sys.stdlib_module_names)
                 for d in _pkg_map.get(t, [])}, key=str.lower)
_LICENSE_RE = re.compile(r'^(LICEN[CS]E|COPYING|NOTICE|THIRD.?PARTY)', re.I)
_index = ['Third-party components bundled in WhisperFlow Local', '']
for _name in _dists:
    _dist = distribution(_name)
    _meta = _dist.metadata
    _lic = (_meta.get('License-Expression') or _meta.get('License') or '').strip()
    if not _lic or len(_lic) > 60:  # some put the whole text here
        _lic = '; '.join(c.split('::')[-1].strip() for c in
                         _meta.get_all('Classifier') or []
                         if c.startswith('License')) or 'see files'
    _files = [f for f in (_dist.files or []) if _LICENSE_RE.match(f.name)]
    for _f in _files:
        _dest = _out / _name / _f.name
        _dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_f.locate(), _dest)
    _index.append(f'{_name} {_dist.version}: {_lic}'
                  + ('' if _files else '  [no license file in package; see the matching *-LICENSE.txt here]'))
for _f in Path(SPECPATH, 'licenses-extra').glob('*'):
    shutil.copyfile(_f, _out / _f.name)
shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', _out / 'Python-LICENSE.txt')
shutil.copyfile(Path(SPECPATH) / 'LICENSE', _out / 'WhisperFlowLocal-LICENSE.txt')
(_out / 'INDEX.txt').write_text('\n'.join(_index) + '\n', encoding='utf-8')
