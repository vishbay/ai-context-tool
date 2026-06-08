# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for cram-ai.app (macOS menu bar application).
#
# Build:
#   python scripts/generate_icns.py   # one-time: creates assets/cram-ai.icns
#   pyinstaller cram-menu.spec --clean --noconfirm
#
# Output: dist/cram-ai.app
#
# The bundled app contains only the tray UI + popup server.
# Heavy CLI work (cram task, cram sync, …) is delegated via subprocess to the
# system `cram` binary that users install separately with pip.

from pathlib import Path
import cram  # must be importable from the build environment

VERSION = cram.__version__

block_cipher = None

a = Analysis(
    ['cram_menu_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle the popup HTML/CSS/JS assets
        ('cram/tray_ui', 'cram/tray_ui'),
    ],
    hiddenimports=[
        # Tray-specific cram modules (dynamic/lazy imports)
        'cram.tray_server',
        'cram.status',
        'cram.utils',
        'cram.targets',
        'cram.session',
        'cram.suggest',
        'cram.symbols',
        # pystray platform backends
        'pystray._darwin',
        'pystray._base',
        # pywebview platform backends
        'webview.platforms.cocoa',
        # Flask/Werkzeug internals that are dynamically loaded
        'flask',
        'werkzeug.serving',
        'werkzeug.routing',
        'jinja2',
        # PIL
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # CLI-only modules — not needed in the .app; cram CLI runs via subprocess
        'cram.cli',
        'cram.init',
        'cram.find_context',
        'cram.sync_context',
        'cram.hooks',
        'cram.benchmark',
        'cram.decide',
        'cram.add_context',
        'cram.doctor',
        'cram.vscode',
        'cram.mcp_server',
        # Dev / test deps
        'pytest',
        'litellm',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cram-ai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can break macOS code signing — leave off
    console=False,      # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,   # None = native arch; set 'universal2' for fat binary
    codesign_identity=None,
    entitlements_file='assets/entitlements.plist',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='cram-ai',
)

app = BUNDLE(
    coll,
    name='cram-ai.app',
    icon='assets/cram-ai.icns',
    bundle_identifier='ai.cram.menu',
    info_plist={
        # Background-only app: lives in menu bar, never in Dock
        'LSUIElement': True,
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',

        # Bundle identity
        'CFBundleName':            'cram-ai',
        'CFBundleDisplayName':     'cram-ai',
        'CFBundleIdentifier':      'ai.cram.menu',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion':         VERSION,
        'NSHumanReadableCopyright': 'MIT License',

        # Privacy usage strings (required for notarization if used)
        'NSAppleEventsUsageDescription':
            'cram-ai uses Apple Events to show native folder and dialog pickers.',
        'NSDesktopFolderUsageDescription':
            'cram-ai reads your project folder to show context status.',
        'NSDocumentsFolderUsageDescription':
            'cram-ai reads your project folder to show context status.',
    },
)
