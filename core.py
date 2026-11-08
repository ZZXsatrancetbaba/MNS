# -*- coding: utf-8 -*-
"""
MNS - cekirdek modul.

Bu modul su isleri yapar:
  * Sistem / donanim / ag bilgilerini toplar
  * Gunluk (log) dosyasi yazar
  * Uygulamanin "orijinal" olup olmadigini (SHA-256 + manifest) dogrular
  * Metin rapor uretir
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "MNS"
APP_TITLE = "MNS - Sistem Bilgi Merkezi"
APP_AUTHOR = "tekinbedirhan507-hub"
APP_REPO = "https://github.com/ZZXsatrancetbaba/MNS"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# ---------------------------------------------------------------- build info

try:
    from build_info import (  # type: ignore
        BUILD_DATE,
        BUILD_ID,
        BUILD_TIME,
        BUILD_UTC,
        GIT_COMMIT,
        VERSION,
    )
except Exception:  # pragma: no cover - build_info henuz uretilmemis olabilir
    VERSION = "0.0.0"
    BUILD_DATE = "bilinmiyor"
    BUILD_TIME = "bilinmiyor"
    BUILD_UTC = ""
    BUILD_ID = "dev"
    GIT_COMMIT = "yok"


# ------------------------------------------------------------------- helpers


def is_frozen() -> bool:
    """PyInstaller ile paketlenmis mi?"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Calisan uygulamanin klasoru (EXE ise EXE'nin yani, kaynak ise proje koku)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(relative: str) -> Path:
    """PyInstaller _MEIPASS veya proje klasorunde kaynak yolu."""
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base / relative


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:,.2f} {unit}".replace(",", ".")
        size /= 1024
    return f"{value} B"


def _ps(command: str, timeout: int = 10) -> str:
    """PowerShell komutu calistir, hata olursa bos metin dondur."""
    if os.name != "nt":
        return ""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            errors="replace",
        )
        out = (proc.stdout or "").strip()
        return out
    except Exception:
        return ""


def _cim(class_name: str, prop: str) -> str:
    return _ps(f"(Get-CimInstance -ClassName {class_name} | Select-Object -First 1 -ExpandProperty {prop})")


def format_uptime(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} gun")
    if hours:
        parts.append(f"{hours} saat")
    if minutes:
        parts.append(f"{minutes} dakika")
    parts.append(f"{secs} saniye")
    return " ".join(parts)


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------- logging

_LOG_RING: deque[str] = deque(maxlen=1000)
LOG_DIR: Path | None = None
LOG_FILE: Path | None = None


def init_logging() -> Path:
    """Gunluk klasorunu hazirla ve oturum basligi yaz."""
    global LOG_DIR, LOG_FILE

    candidates = []
    env_dir = os.environ.get("MNS_LOG_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / APP_NAME / "logs")
    candidates.append(app_dir() / "logs")
    candidates.append(Path.home() / APP_NAME / "logs")

    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            LOG_DIR = folder
            break
        except Exception:
            continue

    if LOG_DIR is None:
        LOG_DIR = Path(os.environ.get("TEMP", ".")) / APP_NAME
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    LOG_FILE = LOG_DIR / f"mns_{datetime.now():%Y-%m-%d}.log"
    log("INFO", "-" * 66)
    log("INFO", f"{APP_NAME} v{VERSION} baslatildi (build {BUILD_ID})")
    log("INFO", f"Yapim tarihi : {BUILD_DATE} {BUILD_TIME}")
    log("INFO", f"Calisma modu : {'EXE (paketlenmis)' if is_frozen() else 'Kaynak (python)'}")
    log("INFO", f"Gunluk dosya : {LOG_FILE}")
    return LOG_FILE


def log(level: str, message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {level:<7} | {message}"
    _LOG_RING.append(line)
    if LOG_FILE is not None:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass


def log_tail(lines: int = 400) -> str:
    if LOG_FILE is None or not LOG_FILE.exists():
        return "\n".join(_LOG_RING)
    try:
        content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:  # pragma: no cover
        return f"Gunluk okunamadi: {exc}"
    return "\n".join(content[-lines:])


# ---------------------------------------------------------------- integrity


def verify_integrity() -> dict:
    """
    Uygulama dosyasinin ozeti (SHA-256) ile yanindaki MNS.manifest.json
    dosyasindaki beklenen ozeti karsilastirir.
    """
    result = {
        "status": "BILINMIYOR",
        "original": None,
        "sha256": "",
        "expected": "",
        "size": 0,
        "manifest_path": "",
        "manifest": {},
        "message": "",
        "authenticode": "",
    }

    if is_frozen():
        target = Path(sys.executable).resolve()
    else:
        target = Path(__file__).resolve()  # kaynak modda core.py dogrulanir

    result["target"] = str(target)
    result["size"] = target.stat().st_size if target.exists() else 0

    try:
        result["sha256"] = sha256_file(target)
    except Exception as exc:
        result["status"] = "HATA"
        result["message"] = f"Dosya okunamadi: {exc}"
        log("ERROR", result["message"])
        return result

    manifest_candidates = [
        app_dir() / "MNS.manifest.json",
        app_dir() / "dist" / "MNS.manifest.json",
    ]
    manifest = None
    for candidate in manifest_candidates:
        if candidate.exists():
            try:
                manifest = json.loads(candidate.read_text(encoding="utf-8"))
                result["manifest_path"] = str(candidate)
                break
            except Exception as exc:
                log("WARN", f"Manifest okunamadi ({candidate}): {exc}")

    if manifest is None:
        result["status"] = "DOGRULANAMADI"
        result["message"] = (
            "MNS.manifest.json bulunamadi; ozet hesaplandi ancak referans deger yok."
        )
        log("WARN", result["message"])
    else:
        result["manifest"] = manifest
        if is_frozen():
            expected = str(manifest.get("sha256", "")).lower()
            result["expected"] = expected
            if not expected:
                result["status"] = "DOGRULANAMADI"
                result["message"] = "Manifest icinde sha256 alani yok."
            elif expected == result["sha256"]:
                result["status"] = "ORIJINAL"
                result["original"] = True
                result["message"] = "EXE ozeti manifest ile birebir ayni. Dosya degistirilmemis."
                log("INFO", "Orijinallik dogrulandi: ORIJINAL")
            else:
                result["status"] = "DEGISTIRILMIS"
                result["original"] = False
                result["message"] = "EXE ozeti manifest ile uyusmuyor! Dosya degistirilmis olabilir."
                log("ERROR", "Orijinallik dogrulanamadi: DEGISTIRILMIS")
        else:
            files = manifest.get("source_sha256") or {}
            mismatches = []
            for name, expected_hash in files.items():
                path = app_dir() / name
                if not path.exists():
                    mismatches.append(name)
                    continue
                if sha256_file(path) != expected_hash:
                    mismatches.append(name)
            result["expected"] = str(manifest.get("sha256", ""))
            if not files:
                result["status"] = "DOGRULANAMADI"
                result["message"] = "Kaynak ozetleri manifest icinde yok."
            elif mismatches:
                result["status"] = "DEGISTIRILMIS"
                result["original"] = False
                result["message"] = "Degisen kaynak dosyalar: " + ", ".join(sorted(mismatches))
                log("ERROR", result["message"])
            else:
                result["status"] = "ORIJINAL (kaynak)"
                result["original"] = True
                result["message"] = "Kaynak dosyalar manifest ile uyumlu."
                log("INFO", "Orijinallik dogrulandi: kaynak dosyalar uyumlu")

    if is_frozen() and os.name == "nt":
        status = _ps(
            f"(Get-AuthenticodeSignature -FilePath '{sys.executable}').Status"
        )
        result["authenticode"] = status or "Bilinmiyor"
        log("INFO", f"Authenticode imza durumu: {result['authenticode']}")

    return result


# -------------------------------------------------------------- info blocks


def program_info() -> list[tuple[str, str]]:
    integrity = verify_integrity()
    exe = Path(sys.executable).resolve() if is_frozen() else Path(__file__).resolve()
    rows = [
        ("Program adi", APP_NAME),
        ("Aciklama", "Sistem bilgi ve orijinallik dogrulama araci"),
        ("Surum", VERSION),
        ("Build kimligi", BUILD_ID),
        ("Yapim tarihi", BUILD_DATE),
        ("Yapim saati", BUILD_TIME),
        ("Yapim zamani (UTC)", BUILD_UTC or "-"),
        ("Git commit", GIT_COMMIT),
        ("Gelistirici", APP_AUTHOR),
        ("Depo", APP_REPO),
        ("-", "-"),
        ("Calisma modu", "EXE (PyInstaller)" if is_frozen() else "Kaynak (.py)"),
        ("Dosya", exe.name),
        ("Dosya yolu", str(exe)),
        ("Dosya boyutu", human_bytes(integrity.get("size", 0))),
        ("SHA-256", integrity.get("sha256", "") or "-"),
        ("Beklenen SHA-256", integrity.get("expected", "") or "-"),
        ("Manifest", integrity.get("manifest_path", "") or "bulunamadi"),
        ("Orijinal mi?", integrity.get("status", "?")),
        ("Dogrulama notu", integrity.get("message", "")),
    ]
    if integrity.get("authenticode"):
        rows.append(("Dijital imza", integrity["authenticode"]))
    rows += [
        ("Python surumu", platform.python_version()),
        ("PyInstaller", _pyinstaller_version()),
        ("Calistiran kullanici", getpass.getuser()),
    ]
    return rows


def _pyinstaller_version() -> str:
    try:  # paket icinde PyInstaller bulunmayabilir
        import PyInstaller  # type: ignore

        return PyInstaller.__version__
    except Exception:
        return "-"


def system_info() -> list[tuple[str, str]]:
    uname = platform.uname()
    boot = None
    try:
        import psutil  # type: ignore

        boot = psutil.boot_time()
    except Exception:
        boot = None

    win_ver = ""
    if os.name == "nt":
        try:
            win_ver = " ".join(part for part in platform.win32_ver() if part)
        except Exception:
            win_ver = ""

    rows = [
        ("Bilgisayar adi", socket.gethostname()),
        ("Kullanici", getpass.getuser()),
        ("Isletim sistemi", f"{platform.system()} {platform.release()}"),
        ("Surum", platform.version()),
        ("Windows surumu", win_ver or "-"),
        ("Surum (edition)", getattr(platform, "win32_edition", lambda: "-")() if os.name == "nt" else "-"),
        ("Mimari", f"{platform.machine()} / {platform.architecture()[0]}"),
        ("Islemci tanimi", uname.processor or platform.machine()),
        ("Python platformu", sys.platform),
        ("Python yolu", sys.executable),
        ("Dil / bolge", f"{os.environ.get('LANG', '') or '-'} | {time.tzname[0] if time.tzname else '-'}"),
        ("Saat dilimi", time.strftime("%Z %z")),
        ("Yerel saat", datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
        ("UTC saat", datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S")),
        ("Sistem acilis zamani", datetime.fromtimestamp(boot).strftime("%d.%m.%Y %H:%M:%S") if boot else "-"),
        ("Calisma suresi", format_uptime(time.time() - boot) if boot else "-"),
        ("Ortam (venv)", "evet" if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else "hayir"),
        ("venv yolu", sys.prefix),
        ("Islem kimligi (PID)", str(os.getpid())),
        ("Aktif is parcacigi", str(os.cpu_count() or "-")),
    ]
    return rows


def hardware_info() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    cpu_name = _cim("Win32_Processor", "Name") or platform.processor() or platform.machine()
    rows.append(("Islemci", cpu_name.strip()))

    physical = _cim("Win32_Processor", "NumberOfCores")
    logical = _cim("Win32_Processor", "NumberOfLogicalProcessors")
    rows.append(("Cekirdek (fiziksel / mantiksal)", f"{physical or '-'} / {logical or os.cpu_count()}"))

    try:
        import psutil  # type: ignore

        freq = psutil.cpu_freq()
        if freq:
            rows.append(("Islemci frekansi", f"{freq.current:.0f} MHz (max {freq.max:.0f} MHz)"))
        mem = psutil.virtual_memory()
        rows.append(("RAM toplam", human_bytes(mem.total)))
        rows.append(("RAM kullanilabilir", human_bytes(mem.available)))
        rows.append(("RAM kullanim orani", f"%{mem.percent}"))
        swap = psutil.swap_memory()
        rows.append(("Sanal bellek (swap)", f"{human_bytes(swap.used)} / {human_bytes(swap.total)}"))
        rows.append(("Calisan islem sayisi", str(len(psutil.pids()))))

        rows.append(("-", "-"))
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            rows.append(
                (
                    f"Disk {part.device} ({part.fstype or '?'})",
                    f"{human_bytes(usage.used)} / {human_bytes(usage.total)} (%{usage.percent}) - bos {human_bytes(usage.free)}",
                )
            )
    except Exception as exc:  # psutil yoksa
        rows.append(("Donanim ayrintilari", f"psutil kullanilamadi: {exc}"))

    gpu = _cim("Win32_VideoController", "Name")
    rows.append(("Ekran karti", gpu or "-"))

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        rows.append(("Ekran cozunurlugu", f"{root.winfo_screenwidth()} x {root.winfo_screenheight()}"))
        rows.append(("DPI olcegi", f"{round(root.winfo_fpixels('1i'))} dpi"))
        root.destroy()
    except Exception:
        pass

    board = _cim("Win32_BaseBoard", "Product")
    if board:
        rows.append(("Anakart", board))
    bios = _ps("(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")
    if bios:
        rows.append(("BIOS", bios))
    model = _cim("Win32_ComputerSystem", "Model")
    if model:
        rows.append(("Bilgisayar modeli", model))

    return rows


def network_info() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("Ana makine adi", socket.gethostname())]
    try:
        rows.append(("FQDN", socket.getfqdn()))
    except Exception:
        pass

    try:
        import psutil  # type: ignore

        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addrs in interfaces.items():
            state = stats.get(name)
            flags = "aktif" if (state and state.isup) else "pasif"
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    rows.append((f"{name} (IPv4)", f"{addr.address} / {addr.netmask or '-'} [{flags}]"))
                elif addr.family == socket.AF_INET6:
                    if addr.address.lower().startswith("fe80"):
                        continue
                    rows.append((f"{name} (IPv6)", f"{addr.address} [{flags}]"))
                elif getattr(psutil, "AF_LINK", None) and addr.family == psutil.AF_LINK:
                    rows.append((f"{name} (MAC)", addr.address))
        counters = psutil.net_io_counters()
        rows.append(("Toplam gonderilen", human_bytes(counters.bytes_sent)))
        rows.append(("Toplam alinan", human_bytes(counters.bytes_recv)))
    except Exception as exc:
        rows.append(("Ag ayrintilari", f"psutil kullanilamadi: {exc}"))

    try:
        rows.append(("Yerel IP (varsayilan rota)", socket.gethostbyname(socket.gethostname())))
    except Exception:
        pass

    return rows


def all_info() -> dict[str, list[tuple[str, str]]]:
    init_guard = LOG_FILE is None
    if init_guard:
        init_logging()
    data = {
        "program": program_info(),
        "sistem": system_info(),
        "donanim": hardware_info(),
        "ag": network_info(),
    }
    return data


def report_text() -> str:
    data = all_info()
    lines = [
        "=" * 66,
        f"{APP_NAME} - SISTEM RAPORU",
        "=" * 66,
    ]
    titles = {
        "program": "PROGRAM / ORJINALLIK",
        "sistem": "SISTEM",
        "donanim": "DONANIM",
        "ag": "AG",
    }
    for key in ("program", "sistem", "donanim", "ag"):
        lines.append("")
        lines.append(f"[{titles[key]}]")
        lines.append("-" * 66)
        width = max((len(label) for label, _ in data[key] if label != "-"), default=28)
        width = min(max(width, 28), 40)
        for label, value in data[key]:
            if label == "-":
                lines.append("")
                continue
            lines.append(f"{label:<{width}} : {value}")
    lines.append("")
    lines.append("=" * 66)
    lines.append(f"Rapor zamani : {datetime.now():%d.%m.%Y %H:%M:%S}")
    lines.append(f"Gunluk dosya : {LOG_FILE}")
    lines.append("=" * 66)
    return "\n".join(lines)


def report_path() -> Path:
    """Raporun kaydedilecegi varsayilan yol."""
    desktop = Path.home() / "Desktop"
    folder = desktop if desktop.exists() else Path.home()
    return folder / f"MNS-rapor-{datetime.now():%Y%m%d-%H%M%S}.txt"
