#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from excel_export import default_excel_path, write_excel
from onbid_client import (
    CLTR_RE,
    PBANC_RE,
    TrackedError,
    delete_tracked,
    flatten_rows,
    format_won,
    load_snapshot,
    load_tracked,
    refresh_tracked,
    search_onbid,
    upsert_tracked,
)


COLUMNS = (
    ("pbancMngNo", "공고번호", 150),
    ("cltrMngNo", "물건관리번호", 160),
    ("name", "물건명", 360),
    ("status", "진행상태", 110),
    ("round", "회차", 50),
    ("bidStart", "입찰시작", 100),
    ("bidEnd", "입찰종료", 100),
    ("minBid", "최저입찰가", 140),
    ("appraisal", "감정평가액", 140),
    ("org", "공고기관", 160),
)


class TrackedDialog(tk.Toplevel):
    def __init__(self, master: OnbidApp, initial: dict | None = None) -> None:
        super().__init__(master)
        self.master_app = master
        self.title("공고번호 · 물건관리번호")
        self.geometry("920x560")
        self.minsize(760, 420)
        self.transient(master)
        self.original_var = tk.StringVar()
        self.alias_var = tk.StringVar()
        self.cltr_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.form_status = tk.StringVar(
            value="공고번호만 저장해도 다시 조회할 때 물건관리번호를 모두 찾아 각각 조회합니다."
        )
        self._selected_original = ""
        self._build()
        self._reload()
        if initial:
            self.original_var.set(initial.get("originalPbanc") or "")
            self.alias_var.set(initial.get("alias") or "")
            self.cltr_var.set(initial.get("cltrMngNo") or "")
            self.note_var.set(initial.get("note") or "")
            self._select_original(initial.get("originalPbanc") or "")
        self.grab_set()

    def _build(self) -> None:
        form = ttk.LabelFrame(self, text="번호 입력", padding=12)
        form.pack(fill="x", padx=16, pady=(16, 8))
        labels = (
            ("표 공고번호", self.original_var, "예: 202503-06201-00"),
            ("온비드 공고번호", self.alias_var, "다르면 입력, 같으면 비움"),
            ("물건관리번호", self.cltr_var, "비우면 공고번호로 전부 조회"),
            ("비고", self.note_var, "비워 두면 번호로 자동 작성"),
        )
        for row, (label, var, hint) in enumerate(labels):
            ttk.Label(form, text=label, width=16).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
            ttk.Label(form, text=hint).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=3)
        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self, padding=(16, 0))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="추가", command=self.add_entry).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="선택 수정", command=self.update_entry).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="선택 삭제", command=self.remove_entry).pack(side="left")
        ttk.Label(buttons, textvariable=self.form_status).pack(side="left", padx=12)

        table_wrap = ttk.Frame(self, padding=16)
        table_wrap.pack(fill="both", expand=True)
        columns = ("originalPbanc", "alias", "cltrMngNo", "note")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings", selectmode="browse")
        headings = (
            ("originalPbanc", "표 공고번호", 150),
            ("alias", "온비드 공고번호", 150),
            ("cltrMngNo", "물건관리번호", 160),
            ("note", "비고", 360),
        )
        for key, title, width in headings:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=key == "note")
        scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _reload(self, select_original: str = "") -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in load_tracked():
            self.tree.insert(
                "",
                "end",
                iid=entry["originalPbanc"],
                values=(
                    entry["originalPbanc"],
                    entry.get("alias") or "",
                    ", ".join(entry.get("cltrMngNos") or []) or entry.get("cltrMngNo") or "",
                    entry.get("note") or "",
                ),
            )
        if select_original:
            self._select_original(select_original)

    def _select_original(self, original: str) -> None:
        if original and self.tree.exists(original):
            self.tree.selection_set(original)
            self.tree.see(original)
            self._selected_original = original

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        original, alias, cltr, note = self.tree.item(selected[0], "values")
        self._selected_original = original
        self.original_var.set(original)
        self.alias_var.set(alias)
        self.cltr_var.set(cltr)
        self.note_var.set(note)

    def _form_payload(self) -> dict:
        return {
            "originalPbanc": self.original_var.get(),
            "alias": self.alias_var.get(),
            "cltrMngNo": self.cltr_var.get(),
            "note": self.note_var.get(),
        }

    def add_entry(self) -> None:
        try:
            items = upsert_tracked(self._form_payload(), create_only=True)
        except TrackedError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return
        entry = next(item for item in items if item["originalPbanc"] == self.original_var.get().strip())
        self._reload(entry["originalPbanc"])
        self.form_status.set(f"{entry['originalPbanc']} 을(를) 추가했습니다. 다시 조회하면 반영됩니다.")
        self.master_app.status_var.set(self.form_status.get())

    def update_entry(self) -> None:
        if not self._selected_original:
            messagebox.showwarning("선택 필요", "수정할 공고를 목록에서 선택해 주세요.", parent=self)
            return
        try:
            items = upsert_tracked(self._form_payload(), replace_original=self._selected_original)
        except TrackedError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return
        saved = next(item for item in items if item["originalPbanc"] == self.original_var.get().strip())
        self._selected_original = saved["originalPbanc"]
        self._reload(saved["originalPbanc"])
        self.form_status.set(f"{saved['originalPbanc']} 번호를 수정했습니다. 다시 조회하면 반영됩니다.")
        self.master_app.status_var.set(self.form_status.get())

    def remove_entry(self) -> None:
        original = self._selected_original or self.original_var.get().strip()
        if not original:
            messagebox.showwarning("선택 필요", "삭제할 공고를 목록에서 선택해 주세요.", parent=self)
            return
        if not messagebox.askyesno("삭제", f"{original} 을(를) 추적 목록에서 삭제할까요?", parent=self):
            return
        try:
            delete_tracked(original)
        except TrackedError as exc:
            messagebox.showerror("삭제 실패", str(exc), parent=self)
            return
        self._selected_original = ""
        self.original_var.set("")
        self.alias_var.set("")
        self.cltr_var.set("")
        self.note_var.set("")
        self._reload()
        self.form_status.set(f"{original} 을(를) 삭제했습니다.")
        self.master_app.status_var.set(self.form_status.get())


class OnbidApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("온비드 공매 최신 현황")
        self.geometry("1280x760")
        self.minsize(960, 560)
        self.configure(bg="#f4f1ea")
        self.snapshot: dict = {}
        self.rows: list[dict] = []
        self.busy = False
        self._setup_style()
        self._build()
        self._load_initial()

    def _setup_style(self) -> None:
        font_name = "맑은 고딕"
        try:
            import tkinter.font as tkfont

            available = set(tkfont.families())
        except Exception:
            available = set()
        for candidate in ("맑은 고딕", "Malgun Gothic", "Noto Sans CJK KR", "WenQuanYi Micro Hei", "AppleGothic"):
            if candidate in available:
                font_name = candidate
                break
        self.option_add("*Font", (font_name, 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f1ea")
        style.configure("Header.TFrame", background="#173a63")
        style.configure("Header.TLabel", background="#173a63", foreground="white", font=(font_name, 16, "bold"))
        style.configure("Sub.TLabel", background="#173a63", foreground="#d6e8f5", font=(font_name, 9))
        style.configure("TLabel", background="#f4f1ea", foreground="#1c1917")
        style.configure("Stat.TLabelframe", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("Stat.TLabelframe.Label", background="#ffffff", foreground="#57534e", font=(font_name, 8))
        style.configure("StatValue.TLabel", background="#ffffff", foreground="#173a63", font=(font_name, 14, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background="#173a63", foreground="white", padding=(12, 6))
        style.map("Accent.TButton", background=[("active", "#0f2744")])
        style.configure(
            "Treeview",
            background="white",
            fieldbackground="white",
            rowheight=28,
            font=(font_name, 10),
        )
        style.configure("Treeview.Heading", font=(font_name, 10, "bold"), background="#eef3f8", foreground="#173a63")
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#0f2744")])

    def _build(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="온비드 공매 최신 현황", style="Header.TLabel").pack(anchor="w")
        self.subtitle = ttk.Label(header, text="저장된 조회 결과를 불러오는 중…", style="Sub.TLabel")
        self.subtitle.pack(anchor="w", pady=(4, 0))

        stats = ttk.Frame(self, padding=(16, 12, 16, 4))
        stats.pack(fill="x")
        self.stat_vars = {
            "notices": tk.StringVar(value="0건"),
            "items": tk.StringVar(value="0건"),
            "bargain": tk.StringVar(value="0건"),
            "failed": tk.StringVar(value="0건"),
            "sum": tk.StringVar(value="—"),
        }
        labels = (
            ("추적 공고", "notices"),
            ("최신 물건", "items"),
            ("수의계약가능", "bargain"),
            ("유찰", "failed"),
            ("최저입찰가 합계", "sum"),
        )
        for title, key in labels:
            box = ttk.LabelFrame(stats, text=title, style="Stat.TLabelframe", padding=8)
            box.pack(side="left", expand=True, fill="x", padx=4)
            ttk.Label(box, textvariable=self.stat_vars[key], style="StatValue.TLabel").pack(anchor="w")

        toolbar = ttk.Frame(self, padding=(16, 8))
        toolbar.pack(fill="x")
        self.query_var = tk.StringVar()
        entry = ttk.Entry(toolbar, textvariable=self.query_var)
        entry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        entry.bind("<Return>", lambda _e: self.apply_filter())
        ttk.Button(toolbar, text="찾기", command=self.apply_filter).pack(side="left", padx=2)
        ttk.Button(toolbar, text="온비드 검색", style="Accent.TButton", command=self.search_live).pack(side="left", padx=2)
        ttk.Button(toolbar, text="다시 조회", command=self.refresh_live).pack(side="left", padx=2)
        ttk.Button(toolbar, text="번호 관리", command=self.open_tracked_manager).pack(side="left", padx=2)
        ttk.Button(toolbar, text="엑셀 저장", command=self.save_excel).pack(side="left", padx=2)

        filter_bar = ttk.Frame(self, padding=(16, 0, 16, 8))
        filter_bar.pack(fill="x")
        ttk.Label(filter_bar, text="상태").pack(side="left")
        self.filter_var = tk.StringVar(value="전체")
        combo = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_var,
            values=("전체", "수의계약가능", "유찰", "낙찰", "조회불가"),
            state="readonly",
            width=14,
        )
        combo.pack(side="left", padx=8)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filter())

        table_wrap = ttk.Frame(self, padding=(16, 0, 16, 8))
        table_wrap.pack(fill="both", expand=True)
        columns = [key for key, _title, _w in COLUMNS]
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings", selectmode="browse")
        for key, title, width in COLUMNS:
            anchor = "e" if key in {"minBid", "appraisal"} else "w"
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key in {"name", "org"})
        yscroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure("bargain", background="#fff7d6")
        self.tree.tag_configure("failed", background="#ffe4e6")
        self.tree.tag_configure("awarded", background="#d1fae5")
        self.tree.tag_configure("missing", background="#e7e5e4")
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)

        self.status_var = tk.StringVar(value="준비됨")
        ttk.Label(self, textvariable=self.status_var, padding=(16, 8), anchor="w").pack(fill="x")

    def _load_initial(self) -> None:
        try:
            self.snapshot = load_snapshot()
            self.rows = flatten_rows(self.snapshot)
            self.apply_filter()
            self._update_stats()
            fetched = str(self.snapshot.get("fetchedAt") or "")[:16].replace("T", " ")
            self.subtitle.configure(text=f"저장된 온비드 조회 결과 · {fetched}")
            self.status_var.set(f"{len(self.rows)}건을 불러왔습니다. 더블클릭하면 온비드 상세를 엽니다.")
        except FileNotFoundError:
            self.status_var.set("저장된 조회 결과가 없습니다. 다시 조회를 눌러 주세요.")
        except Exception as exc:
            messagebox.showerror("불러오기 실패", str(exc))

    def _update_stats(self) -> None:
        rows = self.rows
        self.stat_vars["notices"].set(f"{self.snapshot.get('announcementCount', 0)}건")
        self.stat_vars["items"].set(f"{self.snapshot.get('itemCount', 0)}건")
        self.stat_vars["bargain"].set(f"{sum(1 for r in rows if '수의' in (r.get('status') or ''))}건")
        self.stat_vars["failed"].set(f"{sum(1 for r in rows if (r.get('status') or '') == '유찰')}건")
        total = sum(r.get("minBid") or 0 for r in rows)
        self.stat_vars["sum"].set(format_won(total) if total else "—")

    def _row_tag(self, status: str) -> str:
        if "수의" in status:
            return "bargain"
        if "낙찰" in status:
            return "awarded"
        if "조회" in status:
            return "missing"
        if "유찰" in status:
            return "failed"
        return ""

    def apply_filter(self) -> None:
        query = self.query_var.get().strip().lower()
        status_filter = self.filter_var.get()
        for item in self.tree.get_children():
            self.tree.delete(item)
        shown = 0
        for idx, row in enumerate(self.rows):
            status = row.get("status") or ""
            if status_filter != "전체":
                if status_filter == "수의계약가능" and "수의" not in status:
                    continue
                if status_filter == "유찰" and status != "유찰":
                    continue
                if status_filter == "낙찰" and "낙찰" not in status:
                    continue
                if status_filter == "조회불가" and "조회" not in status:
                    continue
            hay = " ".join(
                str(row.get(key) or "")
                for key in ("originalPbanc", "pbancMngNo", "cltrMngNo", "name", "status", "org", "note")
            ).lower()
            if query and query not in hay:
                continue
            values = [
                row.get("pbancMngNo") or "",
                row.get("cltrMngNo") or "",
                row.get("name") or "",
                status,
                row.get("round") or "",
                row.get("bidStart") or "",
                row.get("bidEnd") or "",
                format_won(row.get("minBid")),
                format_won(row.get("appraisal")),
                row.get("org") or "",
            ]
            self.tree.insert("", "end", iid=str(idx), values=values, tags=(self._row_tag(status),))
            shown += 1
        self.status_var.set(f"{shown}건 표시 중 / 전체 {len(self.rows)}건")

    def open_selected(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        row = self.rows[int(sel[0])]
        if row.get("url"):
            webbrowser.open(row["url"])

    def _selected_row(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.rows[int(sel[0])]

    def open_tracked_manager(self) -> None:
        initial: dict = {}
        row = self._selected_row()
        query = self.query_var.get().strip()
        if row:
            original = row.get("originalPbanc") or ""
            current = row.get("pbancMngNo") or ""
            initial = {
                "originalPbanc": original or current,
                "alias": current if original and current and original != current else "",
                "cltrMngNo": row.get("cltrMngNo") or "",
                "note": row.get("note") or "",
            }
        elif PBANC_RE.fullmatch(query):
            initial = {"originalPbanc": query}
        elif CLTR_RE.fullmatch(query):
            initial = {"cltrMngNo": query}
        TrackedDialog(self, initial)

    def _run_bg(self, work, done) -> None:
        if self.busy:
            messagebox.showinfo("진행 중", "이미 조회 중입니다.")
            return
        self.busy = True

        def runner() -> None:
            try:
                result = work()
                self.after(0, lambda: done(result, None))
            except Exception as exc:
                self.after(0, lambda err=exc: done(None, err))

        threading.Thread(target=runner, daemon=True).start()

    def refresh_live(self) -> None:
        self.status_var.set("온비드에서 다시 조회하는 중…")

        def done(result, error) -> None:
            self.busy = False
            if error:
                messagebox.showerror("조회 실패", str(error))
                self.status_var.set("조회에 실패했습니다.")
                return
            self.snapshot = result
            self.rows = flatten_rows(result)
            self.apply_filter()
            self._update_stats()
            fetched = str(result.get("fetchedAt") or "")[:16].replace("T", " ")
            self.subtitle.configure(text=f"온비드 다시 조회 완료 · {fetched}")
            self.status_var.set(f"공고 {result.get('foundCount')}건, 물건 {result.get('itemCount')}건을 갱신했습니다.")

        self._run_bg(refresh_tracked, done)

    def _offer_track(self, announcement: dict, cltr_mng_no: str = "") -> None:
        current = announcement.get("currentPbanc") or ""
        original = announcement.get("originalPbanc") or current
        item_no = cltr_mng_no
        if not item_no:
            items = announcement.get("items") or []
            if len(items) == 1:
                item_no = items[0].get("cltrMngNo") or ""
        alias = current if original and current and original != current else ""
        if not messagebox.askyesno(
            "추적 목록에 저장",
            "이 번호를 추적 목록에 저장할까요?\n"
            f"공고번호: {current or original}\n"
            f"물건관리번호: {item_no or '(없음)'}",
        ):
            return
        try:
            upsert_tracked(
                {
                    "originalPbanc": original or current,
                    "alias": alias,
                    "cltrMngNo": item_no,
                }
            )
        except TrackedError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        self.status_var.set(f"{original or current} 을(를) 추적 목록에 저장했습니다.")

    def search_live(self) -> None:
        query = self.query_var.get().strip()
        if len(query) < 2:
            messagebox.showwarning("검색어", "공고번호 또는 물건관리번호를 입력해 주세요.")
            return
        self.status_var.set(f"온비드에서 {query} 검색 중…")

        def work():
            return search_onbid(query)

        def done(result, error) -> None:
            self.busy = False
            if error:
                messagebox.showerror("검색 실패", str(error))
                self.status_var.set("검색에 실패했습니다.")
                return
            announcement = (result or {}).get("announcement") or {}
            if not announcement.get("found"):
                messagebox.showinfo("검색 결과", "온비드에서 해당 번호를 찾지 못했습니다.")
                self.status_var.set("검색 결과 없음")
                return
            extra = {
                **self.snapshot,
                "announcements": [announcement]
                + [
                    a
                    for a in (self.snapshot.get("announcements") or [])
                    if a.get("currentPbanc") != announcement.get("currentPbanc")
                ],
            }
            extra["announcementCount"] = len(extra["announcements"])
            extra["foundCount"] = sum(1 for a in extra["announcements"] if a.get("found"))
            extra["missingCount"] = extra["announcementCount"] - extra["foundCount"]
            extra["itemCount"] = sum(len(a.get("items") or []) for a in extra["announcements"])
            self.snapshot = extra
            self.rows = flatten_rows(extra)
            self.apply_filter()
            self._update_stats()
            self.status_var.set(f"{announcement.get('currentPbanc')} 공고를 찾았습니다.")
            self._offer_track(announcement, (result or {}).get("cltrMngNo") or "")

        self._run_bg(work, done)

    def save_excel(self) -> None:
        if not self.snapshot:
            messagebox.showwarning("데이터 없음", "저장할 조회 결과가 없습니다.")
            return
        dest = filedialog.asksaveasfilename(
            title="엑셀로 저장",
            defaultextension=".xlsx",
            filetypes=[("Excel 파일", "*.xlsx")],
            initialfile=default_excel_path(self.snapshot).name,
        )
        if not dest:
            return
        try:
            path = write_excel(self.snapshot, Path(dest))
            self.status_var.set(f"엑셀 저장: {path}")
            messagebox.showinfo("엑셀 저장", f"저장했습니다.\n{path}")
        except Exception as exc:
            messagebox.showerror("저장 실패", str(exc))


def main() -> None:
    app = OnbidApp()
    app.mainloop()


if __name__ == "__main__":
    main()
