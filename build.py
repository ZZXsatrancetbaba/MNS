# -*- coding: utf-8 -*-
"""
MNS derleme betigi (PyInstaller).

Kullanim (proje klasorunde, venv aktifken):
    python build.py              -> EXE uret + manifest yaz
    python build.py --temiz      -> once her seyi sil, sifirdan derle
    python build.py --no-icon    -> ikonu yeniden uretme
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "MNS"
ICON = ROOT / "assets" / "mns.ico"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
EXE = DIST / f"{APP_NAME}.exe"
MANIFEST = DIST / f"{APP_NAME}.manifest.json"
VERSION_INFO = ROOT / "version_info.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_source(path: Path) -> str:
    """Kaynak ozeti: satir sonlari LF'e normalize edilerek hesaplanir (git ile uyumlu)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_build_info() -> dict:
    data: dict = {}
    path = ROOT / "build_info.py"
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            if key in ("VERSION", "BUILD_DATE", "BUILD_TIME", "BUILD_UTC", "BUILD_ID", "GIT_COMMIT"):
                data[key] = value
    return data


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in version.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def write_version_info(info: dict) -> Path:
    v = version_tuple(info.get("VERSION", "1.0.0"))
    build_date = info.get("BUILD_DATE", "")
    year = build_date.split(".")[-1] if build_date else str(datetime.now().year)
    template = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'MNS Project'),
         StringStruct('FileDescription', 'MNS - Sistem Bilgi Merkezi'),
         StringStruct('FileVersion', '{info.get('VERSION', '1.0.0')}.0'),
         StringStruct('InternalName', 'MNS'),
         StringStruct('LegalCopyright', 'Copyright (c) {year} MNS Project'),
         StringStruct('OriginalFilename', 'MNS.exe'),
         StringStruct('ProductName', 'MNS'),
         StringStruct('ProductVersion', '{info.get('VERSION', '1.0.0')}'),
         StringStruct('Comments', 'Yapim: {info.get('BUILD_DATE', '')} {info.get('BUILD_TIME', '')} | build {info.get('BUILD_ID', '')} | commit {info.get('GIT_COMMIT', '')}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    VERSION_INFO.write_text(template, encoding="utf-8")
    print(f"version_info.txt yazildi (surum {info.get('VERSION')})")
    return VERSION_INFO


def step_icon(force: bool) -> None:
    if ICON.exists() and not force:
        print(f"Ikon hazir: {ICON} ({ICON.stat().st_size} bayt)")
        return
    run([sys.executable, str(ROOT / "tools" / "make_icon.py")])


def step_build_info() -> None:
    run([sys.executable, str(ROOT / "tools" / "make_build_info.py")])


def step_pyinstaller() -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON),
        "--add-data",
        f"{ICON};assets",
        "--version-file",
        str(VERSION_INFO),
        "--hidden-import",
        "psutil",
        "--hidden-import",
        "PIL._tkinter_finder",
        "app.py",
    ]
    run(cmd)


def step_manifest(info: dict) -> None:
    sources = {}
    for name in ("app.py", "core.py", "build_info.py"):
        path = ROOT / name
        if path.exists():
            sources[name] = sha256_source(path)

    manifest = {
        "app": APP_NAME,
        "version": info.get("VERSION", "1.0.0"),
        "build_id": info.get("BUILD_ID", ""),
        "build_date": f"{info.get('BUILD_DATE', '')} {info.get('BUILD_TIME', '')}".strip(),
        "build_utc": info.get("BUILD_UTC", ""),
        "git_commit": info.get("GIT_COMMIT", ""),
        "exe": f"{APP_NAME}.exe",
        "exe_size_bytes": EXE.stat().st_size,
        "sha256": sha256(EXE),
        "algorithm": "sha256",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0],
        "source_sha256": sources,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest yazildi: {MANIFEST}")
    print(f"EXE SHA-256     : {manifest['sha256']}")
    print(f"EXE boyutu      : {manifest['exe_size_bytes']:,} bayt")


def main(argv: list[str]) -> int:
    temiz = "--temiz" in argv or "--clean" in argv
    no_icon = "--no-icon" in argv

    try:
        import PyInstaller  # noqa: F401
    except Exception:
        print("HATA: PyInstaller bulunamadi. Once 'pip install -r requirements.txt' calistirin.")
        return 2

    if temiz:
        for folder in (BUILD, DIST):
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
                print(f"Silindi: {folder}")

    print("=" * 66)
    print("MNS derleme basliyor")
    print("=" * 66)
    step_icon(force=not no_icon)
    step_build_info()
    info = read_build_info()
    write_version_info(info)
    step_pyinstaller()

    if not EXE.exists():
        print("HATA: EXE uretilmedi.")
        return 1
    step_manifest(info)

    print("=" * 66)
    print(f"TAMAM: {EXE} ({EXE.stat().st_size:,} bayt)")
    print(f"Surum: {info.get('VERSION')} | Build: {info.get('BUILD_ID')} | "
          f"Tarih: {info.get('BUILD_DATE')} {info.get('BUILD_TIME')}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
