# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['壳.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # 关联.py 与 小桥.py 都是在函数内部延迟 import 的（平时放视频用不到它们，
    # 免得它们出问题连累播放功能）。这种写法静态分析有漏掉的可能，
    # 所以显式声明一遍，保证它们一定被打进去。
    hiddenimports=['关联', '小桥'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='冰冰播放器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['图标.ico'],
)
