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
        parts.append(f"{days} gün")
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
    log("INFO", f"{APP_NAME} v{VERSION} başlatıldı (build {BUILD_ID})")
    log("INFO", f"Yapım tarihi : {BUILD_DATE} {BUILD_TIME}")
    log("INFO", f"Çalışma modu : {'EXE (paketlenmis)' if is_frozen() else 'Kaynak (python)'}")
    log("INFO", f"Günlük dosya : {LOG_FILE}")
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
        return f"Günlük okunamadı: {exc}"
    return "\n".join(content[-lines:])


# ---------------------------------------------------------------- integrity


def verify_integrity() -> dict:
    """
    Uygulama dosyasinin ozeti (SHA-256) ile yanindaki MNS.manifest.json
    dosyasindaki beklenen ozeti karsilastirir.
    """
    result = {
        "status": "BİLİNMİYOR",
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
        result["message"] = f"Dosya okunamadı: {exc}"
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
                log("WARN", f"Manifest okunamadı ({candidate}): {exc}")

    if manifest is None:
        result["status"] = "DOĞRULANAMADI"
        result["message"] = (
            "MNS.manifest.json bulunamadı; özet hesaplandı ancak referans değer yok."
        )
        log("WARN", result["message"])
    else:
        result["manifest"] = manifest
        if is_frozen():
            expected = str(manifest.get("sha256", "")).lower()
            result["expected"] = expected
            if not expected:
                result["status"] = "DOĞRULANAMADI"
                result["message"] = "Manifest içinde sha256 alanı yok."
            elif expected == result["sha256"]:
                result["status"] = "ORİJİNAL"
                result["original"] = True
                result["message"] = "EXE özeti manifest ile birebir aynı. Dosya değiştirilmemiş."
                log("INFO", "Orijinallik doğrulandı: ORİJİNAL")
            else:
                result["status"] = "DEĞİŞTİRİLMİŞ"
                result["original"] = False
                result["message"] = "EXE özeti manifest ile uyuşmuyor! Dosya değiştirilmiş olabilir."
                log("ERROR", "Orijinallik doğrulanamadı: DEĞİŞTİRİLMİŞ")
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
                result["status"] = "DOĞRULANAMADI"
                result["message"] = "Kaynak özetleri manifest içinde yok."
            elif mismatches:
                result["status"] = "DEĞİŞTİRİLMİŞ"
                result["original"] = False
                result["message"] = "Değişen kaynak dosyalar: " + ", ".join(sorted(mismatches))
                log("ERROR", result["message"])
            else:
                result["status"] = "ORİJİNAL (kaynak)"
                result["original"] = True
                result["message"] = "Kaynak dosyalar manifest ile uyumlu."
                log("INFO", "Orijinallik doğrulandı: kaynak dosyalar uyumlu")

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
        ("Program adı", APP_NAME),
        ("Açıklama", "Sistem bilgisi ve orijinallik doğrulama aracı"),
        ("Sürüm", VERSION),
        ("Build kimliği", BUILD_ID),
        ("Yapım tarihi", BUILD_DATE),
        ("Yapım saati", BUILD_TIME),
        ("Yapım zamanı (UTC)", BUILD_UTC or "-"),
        ("Git commit", GIT_COMMIT),
        ("Geliştirici", APP_AUTHOR),
        ("Depo", APP_REPO),
        ("-", "-"),
        ("Çalışma modu", "EXE (PyInstaller)" if is_frozen() else "Kaynak (.py)"),
        ("Dosya", exe.name),
        ("Dosya yolu", str(exe)),
        ("Dosya boyutu", human_bytes(integrity.get("size", 0))),
        ("SHA-256", integrity.get("sha256", "") or "-"),
        ("Beklenen SHA-256", integrity.get("expected", "") or "-"),
        ("Manifest", integrity.get("manifest_path", "") or "bulunamadı"),
        ("Orijinal mi?", integrity.get("status", "?")),
        ("Doğrulama notu", integrity.get("message", "")),
    ]
    if integrity.get("authenticode"):
        rows.append(("Dijital imza", integrity["authenticode"]))
    rows += [
        ("Python sürümü", platform.python_version()),
        ("PyInstaller", _pyinstaller_version()),
        ("Çalıştıran kullanıcı", getpass.getuser()),
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
        ("Bilgisayar adı", socket.gethostname()),
        ("Kullanıcı", getpass.getuser()),
        ("İşletim sistemi", f"{platform.system()} {platform.release()}"),
        ("Sürüm", platform.version()),
        ("Windows sürümü", win_ver or "-"),
        ("Sürüm (edition)", getattr(platform, "win32_edition", lambda: "-")() if os.name == "nt" else "-"),
        ("Mimari", f"{platform.machine()} / {platform.architecture()[0]}"),
        ("İşlemci tanımı", uname.processor or platform.machine()),
        ("Python platformu", sys.platform),
        ("Python yolu", sys.executable),
        ("Dil / bölge", f"{os.environ.get('LANG', '') or '-'} | {time.tzname[0] if time.tzname else '-'}"),
        ("Saat dilimi", time.strftime("%Z %z")),
        ("Yerel saat", datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
        ("UTC saat", datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S")),
        ("Sistem açılış zamanı", datetime.fromtimestamp(boot).strftime("%d.%m.%Y %H:%M:%S") if boot else "-"),
        ("Çalışma süresi", format_uptime(time.time() - boot) if boot else "-"),
        ("Ortam (venv)", "evet" if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else "hayır"),
        ("venv yolu", sys.prefix),
        ("İşlem kimliği (PID)", str(os.getpid())),
        ("Aktif iş parçacığı", str(os.cpu_count() or "-")),
    ]
    return rows


def hardware_info() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    cpu_name = _cim("Win32_Processor", "Name") or platform.processor() or platform.machine()
    rows.append(("İşlemci", cpu_name.strip()))

    physical = _cim("Win32_Processor", "NumberOfCores")
    logical = _cim("Win32_Processor", "NumberOfLogicalProcessors")
    rows.append(("Çekirdek (fiziksel / mantıksal)", f"{physical or '-'} / {logical or os.cpu_count()}"))

    try:
        import psutil  # type: ignore

        freq = psutil.cpu_freq()
        if freq:
            rows.append(("İşlemci frekansı", f"{freq.current:.0f} MHz (max {freq.max:.0f} MHz)"))
        mem = psutil.virtual_memory()
        rows.append(("RAM toplam", human_bytes(mem.total)))
        rows.append(("RAM kullanılabilir", human_bytes(mem.available)))
        rows.append(("RAM kullanım oranı", f"%{mem.percent}"))
        swap = psutil.swap_memory()
        rows.append(("Sanal bellek (swap)", f"{human_bytes(swap.used)} / {human_bytes(swap.total)}"))
        rows.append(("Çalışan işlem sayısı", str(len(psutil.pids()))))

        rows.append(("-", "-"))
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            rows.append(
                (
                    f"Disk {part.device} ({part.fstype or '?'})",
                    f"{human_bytes(usage.used)} / {human_bytes(usage.total)} (%{usage.percent}) - boş {human_bytes(usage.free)}",
                )
            )
    except Exception as exc:  # psutil yoksa
        rows.append(("Donanım ayrıntıları", f"psutil kullanılamadı: {exc}"))

    gpu = _cim("Win32_VideoController", "Name")
    rows.append(("Ekran kartı", gpu or "-"))

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        rows.append(("Ekran çözünürlüğü", f"{root.winfo_screenwidth()} x {root.winfo_screenheight()}"))
        rows.append(("DPI ölçeği", f"{round(root.winfo_fpixels('1i'))} dpi"))
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
    rows: list[tuple[str, str]] = [("Ana makine adı", socket.gethostname())]
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
        rows.append(("Toplam gönderilen", human_bytes(counters.bytes_sent)))
        rows.append(("Toplam alınan", human_bytes(counters.bytes_recv)))
    except Exception as exc:
        rows.append(("Ağ ayrıntıları", f"psutil kullanılamadı: {exc}"))

    try:
        rows.append(("Yerel IP (varsayılan rota)", socket.gethostbyname(socket.gethostname())))
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
        f"{APP_NAME} - SİSTEM RAPORU",
        "=" * 66,
    ]
    titles = {
        "program": "PROGRAM / ORİJİNALLİK",
        "sistem": "SİSTEM",
        "donanim": "DONANIM",
        "ag": "AĞ",
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
    lines.append(f"Rapor zamanı : {datetime.now():%d.%m.%Y %H:%M:%S}")
    lines.append(f"Günlük dosya : {LOG_FILE}")
    lines.append("=" * 66)
    return "\n".join(lines)


def report_path() -> Path:
    """Raporun kaydedilecegi varsayilan yol."""
    desktop = Path.home() / "Desktop"
    folder = desktop if desktop.exists() else Path.home()
    return folder / f"MNS-rapor-{datetime.now():%Y%m%d-%H%M%S}.txt"
