# SPDX-License-Identifier: AGPL-3.0-or-later
"""2903 真实 PDF 业务验收：独立文字抽取、渲染、事务和输入边界。

运行：2903 运行环境中的 python -B 2903_验收测试.py。
所有原稿、图片和输出只在自行创建的临时目录中生成。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import fitz
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
import reportlab
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject


BASE = Path(__file__).resolve().parent


def import_local(filename, name):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 2903 本地模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def spans(page):
    return [span for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]]


class PdfEditAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = import_local("2903_修改引擎.py", "2903_业务验收引擎")
        cls.fixture = import_local("2903_演示数据.py", "2903_业务验收演示")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="2903_业务验收_")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.cleanup_owned_temporary)
        self.source = self.fixture.generate_source(self.root / "2903_工程记录原稿.pdf")
        self.output = self.root / "2903_修改输出"
        self.plan = [dict(item) for item in self.fixture.PLAN]

    def cleanup_owned_temporary(self):
        absolute = self.root.absolute()
        self.assertEqual(absolute.resolve().parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(absolute.name.startswith("2903_业务验收_"))
        self.assertFalse(absolute.is_symlink())
        self.assertFalse(getattr(absolute.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        self.temporary.cleanup()

    def edit(self, plan=None, source=None, output=None):
        return self.engine.edit_pdf(source or self.source, self.plan if plan is None else plan, output or self.output)

    def reject(self, plan=None, source=None, output=None):
        source = source or self.source
        output = output or self.output
        original = source.read_bytes() if source.is_file() else None
        before = set(output.parent.iterdir())
        with self.assertRaises((ValueError, RuntimeError)):
            self.edit(plan=plan, source=source, output=output)
        self.assertFalse(output.exists(), "失败时不应发布最终输出目录")
        self.assertEqual(set(output.parent.iterdir()), before, "失败后不应留下暂存目录")
        if original is not None:
            self.assertEqual(source.read_bytes(), original, "失败时不应写入原稿")

    def simple(self, name="2903_单页原稿.pdf", draw=None, pages=1):
        path = self.root / name
        pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1)
        for page in range(pages):
            pdf.setFont("Helvetica", 14)
            if draw:
                draw(pdf, page)
            else:
                pdf.drawString(72, 500, "TARGET")
            pdf.showPage()
        pdf.save()
        return path

    def assert_exact_target(self, source, expected="TARGET", page=0):
        with fitz.open(source) as pdf:
            hits = [item for item in spans(pdf[page]) if item["text"] == expected]
        self.assertEqual(len(hits), 1, "拒绝案例必须确实有唯一可抽取整 span，而非误测找不到文字")

    def test_01_two_page_edits_extract_correctly_and_preserve_source_and_geometry(self):
        original = self.source.read_bytes()
        report = self.edit()
        result = self.output / "2903_修改结果.pdf"
        self.assertEqual(report["pages"], 3)
        self.assertEqual(report["rendering_dpi"], 144)
        self.assertEqual(report["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(report["output_sha256"], digest(result))
        self.assertEqual(self.source.read_bytes(), original)
        with fitz.open(self.source) as before, fitz.open(result) as after:
            self.assertEqual(len(before), len(after))
            for first, second in zip(before, after):
                self.assertEqual(first.mediabox, second.mediabox)
                self.assertEqual(first.cropbox, second.cropbox)
            self.assertIn("RUN-2026-B", after[0].get_text())
            self.assertNotIn("RUN-2026-A", after[0].get_text())
            self.assertIn("STATUS: CLEARED", after[1].get_text())
            self.assertNotIn("STATUS: PENDING", after[1].get_text())
            self.assertEqual(before[2].get_text(), after[2].get_text())

    def test_02_independent_pixel_check_preserves_tables_vectors_and_entire_third_page(self):
        report = self.edit()
        checks = self.fixture.independent_checks(self.source, self.output / "2903_修改结果.pdf", self.plan)
        self.assertTrue(all(item["outside_changed_pixels"] == 0 for item in checks))
        self.assertGreater(checks[0]["changed_pixels"], 0)
        self.assertGreater(checks[1]["changed_pixels"], 0)
        self.assertEqual(checks[2]["changed_pixels"], 0)
        self.assertEqual([item["changed_pixels"] for item in report["page_checks"]], [item["changed_pixels"] for item in checks])

    def test_03_all_six_audit_images_match_independently_rendered_pages(self):
        self.edit()
        with fitz.open(self.source) as before, fitz.open(self.output / "2903_修改结果.pdf") as after:
            for number in range(1, 4):
                for prefix, document in [("原稿", before), ("结果", after)]:
                    with Image.open(self.output / f"2903_{prefix}第{number}页.png") as image:
                        expected = self.fixture._rgb(document[number - 1])
                        self.assertEqual(image.size, expected.size)
                        self.assertEqual(image.convert("RGB").tobytes(), expected.tobytes())
        saved = json.loads((self.output / "2903_核验报告.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["source_sha256"], digest(self.source))
        self.assertEqual(saved["output_sha256"], digest(self.output / "2903_修改结果.pdf"))

    def test_04_two_independent_targets_on_same_page_keep_fonts_sizes_and_origins(self):
        plan = [{"page": 2, "expected_text": "STATUS: PENDING", "replacement": "STATUS: CLEARED"}, {"page": 2, "expected_text": "CHECK-01", "replacement": "CHECK-02"}]
        self.edit(plan=plan)
        with fitz.open(self.source) as original, fitz.open(self.output / "2903_修改结果.pdf") as changed:
            first = {item["text"]: item for item in spans(original[1])}
            second = {item["text"]: item for item in spans(changed[1])}
            for item in plan:
                before, after = first[item["expected_text"]], second[item["replacement"]]
                self.assertEqual(before["font"], after["font"])
                self.assertAlmostEqual(before["size"], after["size"], places=3)
                self.assertEqual(before["color"], after["color"])
                self.assertAlmostEqual(before["origin"][0], after["origin"][0], places=3)
                self.assertAlmostEqual(before["origin"][1], after["origin"][1], places=3)
            self.assertEqual(original[0].get_text(), changed[0].get_text())

    def test_05_shorter_replacement_is_not_auto_scaled_or_padded(self):
        plan = [{"page": 1, "expected_text": "RUN-2026-A", "replacement": "RUN-B"}]
        self.edit(plan=plan)
        with fitz.open(self.output / "2903_修改结果.pdf") as pdf:
            target = [item for item in spans(pdf[0]) if item["text"] == "RUN-B"]
            self.assertEqual(len(target), 1)
            self.assertAlmostEqual(target[0]["size"], 16, places=3)
            self.assertNotIn("RUN-2026-A", pdf[0].get_text())

    def test_06_replacement_too_wide_is_rejected_without_shrinking(self):
        self.reject(plan=[{"page": 1, "expected_text": "RUN-2026-A", "replacement": "RUN-2026-THIS-IS-TOO-WIDE"}])

    def test_07_partial_span_missing_text_and_whitespace_are_rejected(self):
        for expected in ["RUN", "NOT-IN-THIS-PDF", " RUN-2026-A", "RUN-2026-A "]:
            with self.subTest(expected=expected):
                self.reject(plan=[{"page": 1, "expected_text": expected, "replacement": "RUN-B"}])

    def test_08_ambiguous_same_page_text_is_rejected_without_guessing(self):
        source = self.simple(draw=lambda pdf, _: (pdf.drawString(72, 500, "TARGET"), pdf.drawString(72, 430, "TARGET")))
        with fitz.open(source) as pdf:
            self.assertEqual(sum(item["text"] == "TARGET" for item in spans(pdf[0])), 2)
        self.reject(source=source, plan=[{"page": 1, "expected_text": "TARGET", "replacement": "EDIT"}])

    def test_09_page_number_scopes_same_text_on_different_pages(self):
        source = self.simple(pages=2)
        plan = [{"page": 2, "expected_text": "TARGET", "replacement": "EDIT"}]
        self.edit(source=source, plan=plan)
        with fitz.open(self.output / "2903_修改结果.pdf") as pdf:
            self.assertIn("TARGET", pdf[0].get_text())
            self.assertNotIn("EDIT", pdf[0].get_text())
            self.assertIn("EDIT", pdf[1].get_text())
            self.assertNotIn("TARGET", pdf[1].get_text())

    def test_10_bad_later_edit_rolls_back_entire_plan(self):
        self.reject(plan=[self.plan[0], {"page": 2, "expected_text": "NOT-PRESENT", "replacement": "READY"}])

    def test_11_duplicate_target_region_is_rejected(self):
        self.reject(plan=[self.plan[0], dict(self.plan[0])])

    def test_12_invalid_plan_shapes_exact_keys_and_page_types_are_rejected(self):
        invalid = [[], None, {}, "not a plan", [None], [dict(self.plan[0], unexpected=True)], [{"page": 1, "expected_text": "RUN-2026-A"}]]
        invalid += [[dict(self.plan[0], page=page)] for page in [True, False, 0, -1, 4, 1.0, "1"]]
        for plan in invalid:
            with self.subTest(plan=plan):
                # None is a genuine invalid API argument here, not the edit helper default.
                if plan is None:
                    with self.assertRaises((ValueError, RuntimeError)):
                        self.engine.edit_pdf(self.source, None, self.output)
                    self.assertFalse(self.output.exists())
                else:
                    self.reject(plan=plan)

    def test_13_non_ascii_multiline_empty_unchanged_and_non_text_replacements_rejected(self):
        for replacement in ["", "中文", "A\nB", "A\tB", " A", "A ", "RUN-2026-A", 123, None, "A" * 201]:
            with self.subTest(replacement=replacement):
                self.reject(plan=[dict(self.plan[0], replacement=replacement)])

    def test_14_scanned_page_is_not_treated_as_editable_text(self):
        image = self.root / "2903_扫描图片.png"
        Image.new("RGB", (300, 100), "white").save(image)
        source = self.simple(draw=lambda pdf, _: pdf.drawImage(str(image), 72, 450, width=300, height=100))
        with fitz.open(source) as document:
            self.assertEqual(document[0].get_text().strip(), "")
        self.reject(source=source, plan=[{"page": 1, "expected_text": "TARGET", "replacement": "EDIT"}])

    def test_15_rotated_and_cropped_pages_are_refused(self):
        for label, transform in [("旋转", lambda page: page.set_rotation(90)), ("裁剪", lambda page: page.set_cropbox(fitz.Rect(10, 10, 602, 782)))]:
            with self.subTest(kind=label):
                source = self.root / f"2903_{label}原稿.pdf"
                with fitz.open(self.source) as document:
                    transform(document[0])
                    document.save(source)
                self.reject(source=source)

    def test_16_embedded_font_is_refused_even_when_text_is_extractable(self):
        font_path = Path(reportlab.__file__).resolve().parent / "fonts" / "Vera.ttf"
        pdfmetrics.registerFont(TTFont("2903_EmbeddedVera", str(font_path)))
        def draw(pdf, _):
            pdf.setFont("2903_EmbeddedVera", 14)
            pdf.drawString(72, 500, "TARGET")
        source = self.simple(draw=draw)
        self.assert_exact_target(source)
        self.reject(source=source, plan=[{"page": 1, "expected_text": "TARGET", "replacement": "EDIT"}])

    def test_17_overlapping_extractable_text_is_refused(self):
        def draw(pdf, _):
            pdf.drawString(72, 500, "TARGET")
            pdf.setFont("Times-Roman", 14)
            pdf.drawString(75, 505, "OTHER")
        source = self.simple(draw=draw)
        self.assert_exact_target(source)
        self.reject(source=source, plan=[{"page": 1, "expected_text": "TARGET", "replacement": "EDIT"}])

    def test_18_vector_background_and_image_under_target_are_refused(self):
        image = self.root / "2903_背景图片.png"
        Image.new("RGB", (100, 30), "#EEEEEE").save(image)
        for label in ["矢量", "图片"]:
            def draw(pdf, _, kind=label):
                if kind == "矢量":
                    pdf.setFillColorRGB(0.9, 0.9, 0.9)
                    pdf.rect(65, 490, 130, 35, fill=1, stroke=0)
                else:
                    pdf.drawImage(str(image), 65, 490, width=130, height=35)
                pdf.setFillColorRGB(0, 0, 0)
                pdf.drawString(72, 500, "TARGET")
            source = self.simple(name=f"2903_{label}背景原稿.pdf", draw=draw)
            self.assert_exact_target(source)
            self.reject(source=source, plan=[{"page": 1, "expected_text": "TARGET", "replacement": "EDIT"}])

    def test_19_form_annotation_link_and_signature_documents_are_refused(self):
        cases = ["表单", "批注", "链接", "签名"]
        for label in cases:
            with self.subTest(kind=label):
                source = self.root / f"2903_{label}原稿.pdf"
                if label == "签名":
                    writer = PdfWriter()
                    writer.append(str(self.source))
                    signature = DictionaryObject({NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject("2903SyntheticSignature"), NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"), NameObject("/Rect"): ArrayObject([NumberObject(20), NumberObject(20), NumberObject(40), NumberObject(40)])})
                    reference = writer._add_object(signature)
                    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([reference]), NameObject("/SigFlags"): NumberObject(3)})
                    with source.open("wb") as handle:
                        writer.write(handle)
                    writer.close()
                else:
                    with fitz.open(self.source) as document:
                        if label == "表单":
                            widget = fitz.Widget()
                            widget.field_name = "2903_synthetic_field"
                            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                            widget.rect = fitz.Rect(30, 100, 100, 120)
                            document[2].add_widget(widget)
                        elif label == "批注":
                            document[2].add_text_annot(fitz.Point(30, 100), "2903 synthetic note")
                        else:
                            document[2].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(30, 100, 100, 120), "uri": "https://example.invalid/2903"})
                        document.save(source)
                self.reject(source=source)

    def test_20_encrypted_and_corrupt_pdf_are_refused(self):
        encrypted = self.root / "2903_加密原稿.pdf"
        writer = PdfWriter()
        writer.append(str(self.source))
        writer.encrypt("2903-synthetic-password")
        with encrypted.open("wb") as handle:
            writer.write(handle)
        writer.close()
        self.reject(source=encrypted)
        owner_only = self.root / "2903_仅所有者密码加密原稿.pdf"
        with fitz.open(self.source) as document:
            document.save(owner_only, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="2903-synthetic-owner", user_pw="")
        with fitz.open(owner_only) as document:
            self.assertTrue(document.metadata.get("encryption"), "必须测试真实加密 PDF，而不是仅名称含加密")
            self.assertFalse(document.needs_pass, "此回归必须覆盖可无口令打开的加密 PDF")
        self.reject(source=owner_only)
        corrupt = self.root / "2903_损坏原稿.pdf"
        corrupt.write_bytes(b"%PDF-1.7\n2903 not a valid PDF\n")
        self.reject(source=corrupt)

    def test_21_existing_output_empty_or_populated_is_never_overwritten(self):
        original = self.source.read_bytes()
        self.output.mkdir()
        with self.assertRaises((ValueError, RuntimeError)):
            self.edit()
        self.assertEqual(list(self.output.iterdir()), [])
        marker = self.output / "2903_已有文件.txt"
        marker.write_bytes(b"2903 keep original output")
        with self.assertRaises((ValueError, RuntimeError)):
            self.edit()
        self.assertEqual(marker.read_bytes(), b"2903 keep original output")
        self.assertEqual(self.source.read_bytes(), original)

    def test_22_junction_or_symlink_ancestors_are_refused(self):
        target = self.root / "2903_真实目录"
        target.mkdir()
        copied = target / "2903_原稿.pdf"
        copied.write_bytes(self.source.read_bytes())
        link = self.root / "2903_目录链接"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("环境无法创建目录链接")
            process = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            if process.returncode or not link.is_junction():
                self.skipTest("环境无法创建符号链接或 Windows 目录连接点")
        with self.assertRaises((ValueError, RuntimeError)):
            self.edit(source=link / copied.name)
        with self.assertRaises((ValueError, RuntimeError)):
            self.edit(output=link / "2903_危险输出")
        self.assertEqual(copied.read_bytes(), self.source.read_bytes())
        self.assertEqual(list(target.iterdir()), [copied])

    def test_23_failed_visual_verification_removes_staged_output(self):
        original = self.source.read_bytes()
        before = set(self.root.iterdir())
        original_get_pixmap = fitz.Page.get_pixmap
        calls = 0
        def changed_render(page, *args, **kwargs):
            nonlocal calls
            picture = original_get_pixmap(page, *args, **kwargs)
            calls += 1
            if calls == 4:
                picture.set_pixel(0, 0, (0, 0, 0))
            return picture
        with patch.object(fitz.Page, "get_pixmap", changed_render):
            with self.assertRaises((ValueError, RuntimeError)):
                self.edit()
        self.assertGreaterEqual(calls, 4, "必须实际进入保存后的视觉核验")
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(self.source.read_bytes(), original)

    def test_24_demo_is_flat_complete_and_preserves_untouched_page(self):
        target = self.root / "2903_完整演示"
        metrics = self.fixture.demo(target)
        self.assertEqual(metrics["pages"], 3)
        self.assertEqual(metrics["edits"], 2)
        self.assertTrue(metrics["all_outside_pixels_unchanged"])
        self.assertTrue(metrics["unmodified_page_pixels_identical"])
        files = list(target.iterdir())
        self.assertTrue(all(item.is_file() and item.name.startswith("2903_") for item in files))
        self.assertEqual(len(list(target.glob("*.pdf"))), 2)
        self.assertEqual(len(list(target.glob("*.png"))), 6)
        self.assertEqual(len(list(target.glob("*.json"))), 3)
        self.assertEqual(metrics["source_sha256"], digest(target / "2903_工程记录原稿.pdf"))
        self.assertEqual(metrics["output_sha256"], digest(target / "2903_修改结果.pdf"))
        with self.assertRaises(ValueError):
            self.fixture.demo(target)

    def test_25_real_tk_button_previews_both_pages_and_clears_stale_success_on_error(self):
        desktop = import_local("2903_桌面工具.py", "2903_业务验收桌面")
        plan_path = self.root / "2903_桌面计划.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        before = digest(self.source)
        window = tk.Tk()
        window.withdraw()
        try:
            app = desktop.App(window, dialogs=False)
            app.source_var.set(str(self.source))
            app.plan_var.set(str(plan_path))
            app.output_var.set(str(self.output))
            app.run_button.invoke()
            window.update_idletasks()
            self.assertIsNotNone(app.last_report)
            self.assertFalse(app.last_error)
            self.assertEqual(len(app.images), 2)
            self.assertFalse(app.open_button.instate(["disabled"]))
            app.page_var.set("3")
            app.show_page()
            window.update_idletasks()
            self.assertEqual(len(app.images), 2)
            app.run_button.invoke()
            window.update_idletasks()
            self.assertIsNone(app.last_report)
            self.assertIn("已存在", app.last_error)
            self.assertTrue(app.open_button.instate(["disabled"]))
            self.assertEqual(app.images, [])
            self.assertEqual(digest(self.source), before)
        finally:
            window.destroy()

    def test_26_real_tk_preview_failure_preserves_verified_success_and_output(self):
        desktop = import_local("2903_桌面工具.py", "2903_预览故障验收桌面")
        plan_path = self.root / "2903_预览故障计划.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        original = digest(self.source)
        window = tk.Tk()
        window.withdraw()
        try:
            app = desktop.App(window, dialogs=False)
            app.source_var.set(str(self.source))
            app.plan_var.set(str(plan_path))
            app.output_var.set(str(self.output))
            with patch.object(app, "show_page", side_effect=OSError("2903 自制预览故障")):
                app.run_button.invoke()
            window.update_idletasks()
            self.assertIsNotNone(app.last_report)
            self.assertTrue((self.output / "2903_修改结果.pdf").is_file())
            self.assertTrue((self.output / "2903_核验报告.json").is_file())
            self.assertFalse(app.open_button.instate(["disabled"]))
            self.assertIn("结果已核验并保存", app.status_var.get())
            self.assertIn("预览", app.status_var.get())
            self.assertEqual(app.images, [])
            self.assertEqual(digest(self.source), original)
        finally:
            window.destroy()

    def test_27_first_pixel_beyond_right_and_bottom_mask_edges_must_fail_verification(self):
        with fitz.open(self.source) as document:
            target = [item for item in spans(document[0]) if item["text"] == "RUN-2026-A"]
        self.assertEqual(len(target), 1)
        x0, y0, x1, y1 = target[0]["bbox"]
        outside_pixels = {
            "右边界": (math.ceil((x1 + 2) * 2), math.floor((y0 + y1))),
            "下边界": (math.floor((x0 + x1)), math.ceil((y1 + 2) * 2)),
        }
        original_source = self.source.read_bytes()
        original_image = self.engine._image
        before = set(self.root.iterdir())
        for edge, position in outside_pixels.items():
            with self.subTest(edge=edge):
                calls = 0

                def inject_boundary_pixel(page):
                    nonlocal calls
                    picture = original_image(page)
                    calls += 1
                    if calls == 4:  # three originals, then the edited first page
                        self.assertTrue(0 <= position[0] < picture.width)
                        self.assertTrue(0 <= position[1] < picture.height)
                        color = picture.getpixel(position)
                        picture.putpixel(position, tuple(255 - channel for channel in color))
                    return picture

                output = self.root / f"2903_{edge}拒绝输出"
                with patch.object(self.engine, "_image", inject_boundary_pixel):
                    with self.assertRaisesRegex(RuntimeError, "修改框外"):
                        self.edit(output=output)
                self.assertGreaterEqual(calls, 4, "必须实际进入结果 PDF 的渲染核验")
                self.assertFalse(output.exists())
                self.assertEqual(set(self.root.iterdir()), before, "边界核验失败不能留下最终或暂存目录")
                self.assertEqual(self.source.read_bytes(), original_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
