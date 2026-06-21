# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['speed_z_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('speed_z_models.py', '.'), ('speed_z_core.py', '.'), ('speed_z_config.py', '.'), ('speed_z_io.py', '.'), ('speed_z_logging.py', '.'), ('speed_z_errors.py', '.')],
    hiddenimports=[],
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
    name='SPEED-Z-Launcher',
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
    icon='NONE',
)
