# SPDX-License-Identifier: AGPL-3.0-or-later
"""2903 桌面入口，与命令行共用同一修改及核验引擎。"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pdf_engine_2903", BASE / "2903_修改引擎.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class App:
    def __init__(self, root, dialogs=True):
        self.root, self.dialogs = root, dialogs
        self.last_report, self.last_error = None, None
        self.source_var = tk.StringVar()
        self.plan_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar(value="选择原稿和修改计划，再指定全新的输出目录。")
        self.page_var = tk.StringVar(value="1")
        self.images = []
        root.title("2903 定点文字修改与版面核验")
        root.geometry("1120x820")
        root.minsize(940, 680)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", padding=7)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="定点修改 · 逐页核验", font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
        ttk.Label(frame, text="独立演示｜白底单行整段 ASCII｜Helvetica / Times / Courier｜原稿只读").pack(anchor="w", pady=(4, 12))
        form = ttk.Frame(frame)
        form.pack(fill="x")
        for row, (label, variable, action) in enumerate([
            ("原稿 PDF", self.source_var, self.choose_source),
            ("修改计划", self.plan_var, self.choose_plan),
            ("新输出目录", self.output_var, self.choose_output),
        ]):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew")
            ttk.Button(form, text="选择", command=action).grid(row=row, column=2, padx=(8, 0))
        form.columnconfigure(1, weight=1)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=10)
        self.run_button = ttk.Button(actions, text="执行修改并核验", command=self.run)
        self.run_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="打开结果目录", command=self.open_output, state="disabled")
        self.open_button.pack(side="left", padx=8)
        ttk.Label(actions, text="预览页码").pack(side="left", padx=(20, 5))
        self.page_selector = ttk.Combobox(actions, textvariable=self.page_var, values=["1"], width=5, state="readonly")
        self.page_selector.pack(side="left")
        self.page_selector.bind("<<ComboboxSelected>>", lambda e: self.show_page())
        ttk.Label(frame, textvariable=self.status_var, wraplength=1040, foreground="#166534").pack(anchor="w", pady=(0, 8))
        preview = ttk.Panedwindow(frame, orient="horizontal")
        preview.pack(fill="both", expand=True)
        self.before = ttk.LabelFrame(preview, text="原稿（实际渲染）", padding=8)
        self.after = ttk.LabelFrame(preview, text="修改结果（实际渲染）", padding=8)
        preview.add(self.before, weight=1)
        preview.add(self.after, weight=1)
        self.before_label = ttk.Label(self.before, anchor="center", text="执行后显示")
        self.before_label.pack(fill="both", expand=True)
        self.after_label = ttk.Label(self.after, anchor="center", text="执行后显示")
        self.after_label.pack(fill="both", expand=True)
        ttk.Label(frame, text="范围之外会拒绝处理；云端 Drive API、OCR、嵌入字体和复杂排版未接入。").pack(anchor="w", pady=(8, 0))

    def choose_source(self):
        value = filedialog.askopenfilename(title="选择原稿", filetypes=[("PDF 文件", "*.pdf")])
        if value:
            self.source_var.set(value)

    def choose_plan(self):
        value = filedialog.askopenfilename(title="选择修改计划", filetypes=[("修改计划", "*.json")])
        if value:
            self.plan_var.set(value)

    def choose_output(self):
        parent = filedialog.askdirectory(title="选择父目录（将在其下新建结果目录）")
        if parent:
            self.output_var.set(str(Path(parent) / "2903_修改输出"))

    def run(self):
        self.last_report = self.last_error = None
        self.open_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.status_var.set("正在检查支持范围、修改文字并核验全部页面…")
        self.root.update_idletasks()
        try:
            if not all(v.get().strip() for v in (self.source_var, self.plan_var, self.output_var)):
                raise ValueError("请先填写三个路径")
            plan = json.loads(engine._path(self.plan_var.get()).read_text(encoding="utf-8-sig"))
            report = engine.edit_pdf(Path(self.source_var.get()), plan, Path(self.output_var.get()))
            self.last_report = report
            self.page_selector.configure(values=[str(i) for i in range(1, report["pages"] + 1)])
            self.page_var.set("1")
            self.open_button.configure(state="normal")
            self.status_var.set(f"完成：{report['pages']} 页，{len(report['edits'])} 处修改；144 DPI 修改框外变化 0 像素；原稿哈希未变。")
            try:
                self.show_page()
            except Exception as preview_error:
                # PDF 已完成核验并发布；预览组件失败不能误报为没有生成结果。
                for label in (self.before_label, self.after_label):
                    label.configure(image="", text="预览未能加载，请打开结果目录")
                self.images.clear()
                self.status_var.set(f"结果已核验并保存；预览未能加载：{preview_error}")
        except Exception as error:
            self.last_error = str(error)
            self.status_var.set("未生成结果：" + str(error))
            for label in (self.before_label, self.after_label):
                label.configure(image="", text="本次没有成功结果")
            self.images.clear()
            if self.dialogs:
                messagebox.showerror("处理未完成", str(error), parent=self.root)
        finally:
            self.run_button.configure(state="normal")

    def show_page(self):
        if not self.last_report:
            return
        self.images.clear()
        page = int(self.page_var.get())
        for label, name in ((self.before_label, "原稿"), (self.after_label, "结果")):
            with Image.open(Path(self.output_var.get()) / f"2903_{name}第{page}页.png") as picture:
                image = picture.copy()
            image.thumbnail((490, 480), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image, master=self.root)
            self.images.append(photo)
            label.configure(image=photo, text="")

    def open_output(self):
        if self.last_report and sys.platform == "win32":
            os.startfile(self.output_var.get())


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
