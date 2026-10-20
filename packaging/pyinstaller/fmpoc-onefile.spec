# PyInstaller spec - ONE-FILE build (v1.5.0 CR-026): a single PennyWarden-<version>-windows-x64.exe.
# Double-click = local mode (127.0.0.1, opens the browser). Data stays in %LOCALAPPDATA%\PennyWarden,
# never inside the .exe. The .exe unpacks itself to a temporary folder at each start (a few seconds).
# Usage (repo root, after `npm --prefix frontend run build`):
#   pyinstaller --noconfirm --distpath dist --workpath build/pyinstaller-onefile packaging/pyinstaller/fmpoc-onefile.spec
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
PKG = os.path.join(ROOT, "backend", "fmpoc")
NAME = os.environ.get("FM_EXE_NAME", "PennyWarden")
ICON = os.path.join(ROOT, "packaging", "windows", "pennywarden.ico")  # 1.6.6: the coin-with-keyhole app icon

datas = [
    (os.path.join(PKG, "static"), "fmpoc/static"),
    (os.path.join(PKG, "migrations"), "fmpoc/migrations"),
    (os.path.join(PKG, "fonts"), "fmpoc/fonts"),  # 2.0.0 (#157): built-in check printing fonts
    (os.path.join(ROOT, "LICENSE"), "legal"),
    (os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt"), "legal"),
] + collect_data_files("reportlab") + collect_data_files("pypdfium2") + collect_data_files("pypdfium2_raw") + collect_data_files("docx") + collect_data_files("pptx")  # fonts used by the audit report
if os.path.isfile(os.path.join(PKG, "build_info.json")):  # written by CI (version, branch, commit)
    datas.append((os.path.join(PKG, "build_info.json"), "fmpoc"))
hidden = (collect_submodules("fmpoc") + collect_submodules("uvicorn") + collect_submodules("alembic")
          + ["sqlalchemy.dialects.sqlite", "argon2", "argon2._password_hasher", "multipart", "python_multipart",
             "PIL.PngImagePlugin", "PIL.JpegImagePlugin", "re2", "re2._re2"] + collect_submodules("reportlab")
          + collect_submodules("pypdf") + collect_submodules("pypdfium2") + collect_submodules("docx") + collect_submodules("pptx")
          + collect_submodules("xlsxwriter")
          + collect_submodules("lxml") + ["pypdfium2_raw"] + collect_submodules("segno") + ["pyotp"])

a = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[os.path.join(ROOT, "backend")], datas=datas,
             binaries=collect_dynamic_libs("pypdfium2_raw"),  # build 11 (#217): PDFium for the Payments previews
             hiddenimports=hidden, excludes=["tkinter", "pytest", "PIL.ImageTk", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
# console=True: the window shows the address and log; closing it stops PennyWarden.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=True, debug=False, strip=False, upx=False,
          runtime_tmpdir=None, icon=ICON, version=os.environ.get("FM_EXE_VERSION_FILE") or None)
