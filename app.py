# -*- coding: utf-8 -*-
"""
MNS - Sistem Bilgi Merkezi (arayuz)

Calistirma:
    python app.py            -> arayuz
    python app.py --rapor    -> konsola metin rapor
    python app.py --rapor -o rapor.txt
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

import core

BG = "#0f1420"
BG_ALT = "#161d2d"
BG_CARD = "#1b2333"
FG = "#e8eefc"
FG_DIM = "#93a1c0"
ACCENT = "#3ea6ff"
OK = "#2fbf71"
WARN = "#ffb020"
ERR = "#ff5566"

SECTION_TITLES = {
    "program": "PROGRAM / ORİJİNALLİK",
    "sistem": "SİSTEM",
    "donanim": "DONANIM",
    "ag": "AĞ",
}

# Sekme basliklari (basliklarin buyuk harfli hali .title() ile bozulmasin diye ayri)
TAB_TITLES = {
    "program": "Program / Orijinallik",
    "sistem": "Sistem",
    "donanim": "Donanım",
    "ag": "Ağ",
}

ORIGINAL_STATUSES = ("ORİJİNAL", "ORJİNAL")


def enable_dpi_awareness() -> None:
    """Yuksek DPI ekranlarda arayuzun bulanik olmamasini saglar."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class MNSCard(ttk.Frame):
    """Bir bilgi bolumu (baslik + iki kolonlu tablo)."""

    def __init__(self, master, title: str, accent: str = ACCENT, scale: float = 1.0) -> None:
        super().__init__(master, style="Card.TFrame")
        self.title = title
        self.accent = accent
        self.scale = scale

        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x", padx=14, pady=(10, 4))
        ttk.Label(header, text="\u25cf", foreground=accent, background=BG_CARD,
                  font=("Segoe UI", 9)).pack(side="left")
        ttk.Label(header, text=title, foreground=FG, background=BG_CARD,
                  font=("Segoe UI Semibold", 11)).pack(side="left", padx=(6, 0))

        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree = ttk.Treeview(body, columns=("deger",), show="tree headings",
                                 height=int(8))
        self.tree.heading("#0", text="Alan")
        self.tree.heading("deger", text="Değer")
        self.tree.column("#0", width=int(230 * self.scale), minwidth=int(170 * self.scale),
                         stretch=False)
        self.tree.column("deger", width=int(520 * self.scale), minwidth=int(240 * self.scale),
                         stretch=True)

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("odd", background=BG_ALT)
        self.tree.tag_configure("even", background=BG_CARD)
        self.tree.tag_configure("note", foreground=FG_DIM)
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("bad", foreground=ERR)
        self.tree.tag_configure("warn", foreground=WARN)

        self.tree.bind("<Double-1>", self._copy_row)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        index = 0
        for label, value in rows:
            if label == "-":
                self.tree.insert("", "end", text="", values=("",), tags=("note",))
                continue
            tags = ["odd" if index % 2 else "even"]
            if label in ("Orijinal mi?",):
                tags.append("ok" if str(value).startswith(ORIGINAL_STATUSES)
                            else ("bad" if value else "warn"))
            if label in ("Doğrulama notu", "Beklenen SHA-256") and index % 2 == 0:
                tags.append("note")
            self.tree.insert("", "end", text=f" {label}", values=(f" {value}",), tags=tuple(tags))
            index += 1

    def _copy_row(self, _event=None) -> None:
        item = self.tree.focus()
        if not item:
            return
        label = self.tree.item(item, "text").strip()
        value = self.tree.item(item, "values")
        value = str(value[0]).strip() if value else ""
        self.clipboard_clear()
        self.clipboard_append(f"{label}: {value}")
        self.event_generate("<<Status>>")


class MNSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{core.APP_NAME} v{core.VERSION} - Sistem Bilgi Merkezi")
        self.scale = self._detect_scale()
        self.geometry(f"{int(1040 * self.scale)}x{int(720 * self.scale)}")
        self.minsize(int(880 * self.scale), int(600 * self.scale))
        self.configure(bg=BG)

        self._set_icon()
        self._init_style()
        self._build_ui()
        self._bind_keys()

        self.log_file = core.init_logging()
        core.log("INFO", "Arayuz hazir, bilgiler toplaniyor...")
        self.refresh()

    # ------------------------------------------------------------- gorunum
    def _detect_scale(self) -> float:
        """Sistem DPI olcegi (96 dpi = 1.0)."""
        try:
            dpi = self.winfo_fpixels("1i")
            self.tk.call("tk", "scaling", dpi / 72.0)
            return max(1.0, round(dpi / 96.0, 2))
        except Exception:
            return 1.0

    def _set_icon(self) -> None:
        for candidate in (
            core.resource_path("assets/mns.ico"),
            core.app_dir() / "assets" / "mns.ico",
        ):
            try:
                if candidate.exists():
                    self.iconbitmap(str(candidate))
                    return
            except Exception:
                continue

    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=9)
        self.option_add("*Font", default_font)
        self.option_add("*TCombobox*Listbox.font", default_font)

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Dim.TLabel", background=BG, foreground=FG_DIM)
        style.configure("Header.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 16))
        style.configure("Sub.TLabel", background=BG, foreground=FG_DIM, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=BG_ALT, foreground=FG_DIM, font=("Segoe UI", 9))
        style.configure("Badge.TLabel", background=BG_ALT, foreground=ACCENT,
                        font=("Segoe UI Semibold", 9))
        style.configure("TButton", background=BG_CARD, foreground=FG, borderwidth=0,
                        focuscolor=BG_CARD, padding=(12, 6))
        style.map("TButton",
                  background=[("active", "#243047"), ("pressed", "#2b3a55")],
                  foreground=[("disabled", FG_DIM)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#0b1220",
                        font=("Segoe UI Semibold", 9))
        style.map("Accent.TButton", background=[("active", "#66bbff")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_ALT, foreground=FG_DIM,
                        padding=(16, 8), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BG_CARD)],
                  foreground=[("selected", ACCENT)])
        style.configure("Treeview", background=BG_CARD, fieldbackground=BG_CARD,
                        foreground=FG, borderwidth=0, rowheight=int(24 * self.scale))
        style.configure("Treeview.Heading", background=BG_ALT, foreground=FG_DIM,
                        borderwidth=0, font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#2b3a55")])
        style.configure("Vertical.TScrollbar", background=BG_ALT, troughcolor=BG,
                        borderwidth=0, arrowcolor=FG_DIM)

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(14, 6))

        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        title_row = ttk.Frame(left)
        title_row.pack(anchor="w")
        ttk.Label(title_row, text="MNS", style="Header.TLabel").pack(side="left")
        ttk.Label(title_row, text=f"  v{core.VERSION}", style="Badge.TLabel",
                  padding=(8, 3)).pack(side="left", padx=(6, 0), pady=(4, 0))
        ttk.Label(title_row, text=f"  build {core.BUILD_ID}", style="Sub.TLabel").pack(
            side="left", pady=(6, 0))
        ttk.Label(left, text="Sistem bilgileri, yapım kaydı ve orijinallik doğrulaması",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        buttons = ttk.Frame(header)
        buttons.pack(side="right")
        ttk.Button(buttons, text="Yenile (F5)", style="Accent.TButton",
                   command=self.refresh).pack(side="left", padx=4)
        ttk.Button(buttons, text="Raporu kaydet", command=self.save_report).pack(side="left", padx=4)
        ttk.Button(buttons, text="Günlük klasörü", command=self.open_log_folder).pack(side="left", padx=4)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(6, 8))

        self.cards: dict[str, MNSCard] = {}
        accents = {"program": ACCENT, "sistem": "#8f7bff", "donanim": OK, "ag": WARN}
        for key, title in SECTION_TITLES.items():
            card = MNSCard(self.notebook, title, accents[key], scale=self.scale)
            self.notebook.add(card, text=f"  {TAB_TITLES[key]}  ")
            self.cards[key] = card

        log_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(log_page, text="  Günlük  ")
        self.log_text = tk.Text(log_page, bg=BG_CARD, fg=FG, insertbackground=FG,
                                relief="flat", wrap="none", font=("Consolas", 9),
                                padx=12, pady=10, height=20)
        log_scroll_y = ttk.Scrollbar(log_page, orient="vertical", command=self.log_text.yview)
        log_scroll_x = ttk.Scrollbar(log_page, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll_y.grid(row=0, column=1, sticky="ns")
        log_scroll_x.grid(row=1, column=0, sticky="ew")
        log_page.rowconfigure(0, weight=1)
        log_page.columnconfigure(0, weight=1)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed())

        status = ttk.Frame(self, style="TFrame")
        status.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Hazır")
        self.integrity_var = tk.StringVar(value="Orijinallik: kontrol ediliyor...")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel",
                  padding=(18, 6)).pack(side="left")
        self.integrity_label = ttk.Label(status, textvariable=self.integrity_var,
                                         style="Status.TLabel", padding=(18, 6))
        self.integrity_label.pack(side="right")

        self.bind("<<Status>>", lambda _e: self.status_var.set("Satır panoya kopyalandı"))

    def _bind_keys(self) -> None:
        self.bind("<F5>", lambda _e: self.refresh())
        self.bind("<Control-s>", lambda _e: self.save_report())
        self.bind("<Control-c>", lambda _e: self.copy_all())

    # -------------------------------------------------------------- aksiyon
    def refresh(self) -> None:
        self.status_var.set("Bilgiler toplanıyor...")
        for card in self.cards.values():
            for item in card.tree.get_children():
                card.tree.delete(item)
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self) -> None:
        try:
            data = core.all_info()
            integrity = core.verify_integrity()
            core.log("INFO", "Bilgiler yenilendi")
            self.after(0, lambda: self._apply(data, integrity))
        except Exception as exc:  # pragma: no cover
            core.log("ERROR", f"Bilgi toplama hatası: {exc}")
            self.after(0, lambda: self._fail(exc))

    def _apply(self, data: dict, integrity: dict) -> None:
        for key, card in self.cards.items():
            card.set_rows(data.get(key, []))
        status = str(integrity.get("status", "?"))
        self.integrity_var.set(f"Orijinallik: {status}")
        if status.startswith(ORIGINAL_STATUSES):
            self.integrity_label.configure(foreground=OK)
        elif status == "DOĞRULANAMADI":
            self.integrity_label.configure(foreground=WARN)
        else:
            self.integrity_label.configure(foreground=ERR)
        self.status_var.set(
            f"Son güncelleme: {core.datetime.now():%H:%M:%S} | "
            f"Günlük: {core.LOG_FILE}"
        )
        self._refresh_log()

    def _fail(self, exc: Exception) -> None:
        self.status_var.set(f"Hata: {exc}")
        messagebox.showerror(core.APP_NAME, f"Bilgiler alınamadı:\n{exc}")

    def _refresh_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", core.log_tail())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_tab_changed(self) -> None:
        if self.notebook.index("current") == len(SECTION_TITLES):
            self._refresh_log()

    def copy_all(self) -> None:
        text = core.report_text()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Tüm rapor panoya kopyalandı")

    def save_report(self) -> None:
        default = core.report_path()
        path = filedialog.asksaveasfilename(
            title="Raporu kaydet",
            defaultextension=".txt",
            initialdir=str(default.parent),
            initialfile=default.name,
            filetypes=[("Metin dosyası", "*.txt"), ("Tüm dosyalar", "*.*")],
        )
        if not path:
            return
        try:
            content = core.report_text()
            Path(path).write_text(content, encoding="utf-8")
            core.log("INFO", f"Rapor kaydedildi: {path}")
            self.status_var.set(f"Rapor kaydedildi: {path}")
            messagebox.showinfo(core.APP_NAME, f"Rapor kaydedildi:\n{path}")
        except Exception as exc:
            core.log("ERROR", f"Rapor kaydedilemedi: {exc}")
            messagebox.showerror(core.APP_NAME, f"Rapor kaydedilemedi:\n{exc}")

    def open_log_folder(self) -> None:
        if core.LOG_DIR is None:
            core.init_logging()
        try:
            import os

            os.startfile(str(core.LOG_DIR))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showwarning(core.APP_NAME, f"Klasör açılamadı:\n{exc}")


def console_mode(output: str | None) -> int:
    core.init_logging()
    text = core.report_text()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    print(text)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"\nRapor yazıldı: {output}")
    core.log("INFO", "Konsol modunda rapor üretildi")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--rapor" in argv or "--report" in argv or "--console" in argv:
        out = None
        for flag in ("-o", "--output"):
            if flag in argv:
                out = argv[argv.index(flag) + 1]
        return console_mode(out)
    if "--surum" in argv or "--version" in argv:
        print(f"{core.APP_NAME} v{core.VERSION} (build {core.BUILD_ID}, {core.BUILD_DATE})")
        return 0

    enable_dpi_awareness()
    app = MNSApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        core.log("INFO", "Uygulama kapatıldı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
