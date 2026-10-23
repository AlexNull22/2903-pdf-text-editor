# SPDX-License-Identifier: AGPL-3.0-or-later
"""2903 自制工程记录与真实定点修改演示；所有内容均为合成数据。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

import fitz
from PIL import Image, ImageChops, ImageDraw
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


BASE = Path(__file__).resolve().parent
PLAN = [
    {"page": 1, "expected_text": "RUN-2026-A", "replacement": "RUN-2026-B"},
    {"page": 2, "expected_text": "STATUS: PENDING", "replacement": "STATUS: CLEARED"},
]


def load_engine():
    name = "2903_演示专用修改引擎"
    spec = importlib.util.spec_from_file_location(name, BASE / "2903_修改引擎.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 2903 修改引擎")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _frame(pdf, page, title, subtitle):
    pdf.setFillColor(HexColor("#163447"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(48, 754, "NORTHFIELD LAB  /  SYNTHETIC ENGINEERING RECORD")
    pdf.setFont("Helvetica", 23)
    pdf.drawString(48, 718, title)
    pdf.setFillColor(HexColor("#526572"))
    pdf.setFont("Helvetica", 10)
    pdf.drawString(48, 696, subtitle)
    pdf.setStrokeColor(HexColor("#B5C8D0"))
    pdf.setLineWidth(0.7)
    pdf.line(48, 685, 564, 685)
    pdf.line(48, 49, 564, 49)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(48, 31, "SYNTHETIC PORTFOLIO DEMO - No customer or operational data")
    pdf.drawRightString(564, 31, f"ENGINEERING NOTES / {page:02d}")


def _label(pdf, x, y, text):
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(HexColor("#526572"))
    pdf.drawString(x, y, text)


def _table(pdf, x, top, widths, headers, rows, row_height=27):
    total = sum(widths)
    pdf.setFillColor(HexColor("#EAF1F4"))
    pdf.rect(x, top - row_height, total, row_height, stroke=0, fill=1)
    pdf.setStrokeColor(HexColor("#CCD9DF"))
    pdf.setLineWidth(0.5)
    for index in range(len(rows) + 2):
        y = top - row_height * index
        pdf.line(x, y, x + total, y)
    left = x
    for width in widths[:-1]:
        left += width
        pdf.line(left, top, left, top - row_height * (len(rows) + 1))
    for number, values in enumerate([headers, *rows]):
        left = x
        pdf.setFont("Helvetica" if number == 0 else "Times-Roman", 10)
        pdf.setFillColor(HexColor("#163447"))
        for width, text in zip(widths, values):
            pdf.drawString(left + 9, top - row_height * number - 18, str(text))
            left += width


def _chart(pdf):
    x, y, width, height = 86, 178, 434, 177
    pdf.setFont("Helvetica", 12)
    pdf.setFillColor(HexColor("#163447"))
    pdf.drawString(48, 392, "Chamber response - synthetic observations")
    pdf.setFont("Helvetica", 8)
    for index in range(5):
        at = y + height * index / 4
        pdf.setStrokeColor(HexColor("#D8E2E7"))
        pdf.setLineWidth(0.5)
        pdf.line(x, at, x + width, at)
        pdf.setFillColor(HexColor("#526572"))
        pdf.drawRightString(x - 9, at - 3, str(20 + index * 5))
    pdf.setStrokeColor(HexColor("#163447"))
    pdf.setLineWidth(0.8)
    pdf.line(x, y, x, y + height)
    pdf.line(x, y, x + width, y)
    observations = [21.0, 23.5, 27.8, 31.2, 33.9, 35.3, 35.9, 36.0]
    points = [(x + width * index / 7, y + (value - 20) / 20 * height) for index, value in enumerate(observations)]
    pdf.setStrokeColor(HexColor("#087D88"))
    pdf.setLineWidth(2)
    path = pdf.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    pdf.drawPath(path)
    for px, py in points:
        pdf.setFillColor(white)
        pdf.circle(px, py, 3, stroke=1, fill=1)
    pdf.setFillColor(HexColor("#526572"))
    pdf.setFont("Helvetica", 8)
    for index in range(8):
        pdf.drawCentredString(x + width * index / 7, y - 16, str(index * 5))
    pdf.drawCentredString(x + width / 2, y - 34, "Elapsed time (minutes)")


def generate_source(path):
    """生成三页固定工程实验记录；拒绝覆盖既有文件。"""
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("演示原稿不接受链接或目录连接点")
    if path.exists() or path.is_symlink():
        raise ValueError("演示原稿路径必须不存在")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, pageCompression=1, invariant=1)
    pdf.setTitle("Synthetic thermal chamber engineering record")
    pdf.setAuthor("Independent synthetic portfolio demonstration")
    pdf.setSubject("Three-page layout preservation fixture; no operational data")

    _frame(pdf, 1, "Thermal chamber validation", "Experiment sheet / reference specimen / revision control")
    _label(pdf, 48, 661, "RUN IDENTIFIER - CONTROLLED TEXT FIELD")
    pdf.setFillColor(HexColor("#163447"))
    pdf.setFont("Helvetica", 16)
    pdf.drawString(48, 633, "RUN-2026-A")
    _label(pdf, 330, 661, "FIXTURE")
    pdf.setFont("Times-Roman", 13)
    pdf.setFillColor(HexColor("#163447"))
    pdf.drawString(330, 633, "CHAMBER 04 / DRY CYCLE")
    _table(pdf, 48, 585, [172, 172, 172], ["Measurement", "Nominal", "Observed"], [
        ("Ambient temperature", "21.0 C", "21.2 C"),
        ("Ramp duration", "35 min", "35 min"),
        ("Hold temperature", "36.0 C", "36.0 C"),
        ("Sensor channels", "08", "08"),
    ])
    _chart(pdf)
    pdf.setFont("Times-Roman", 10)
    pdf.setFillColor(HexColor("#163447"))
    pdf.drawString(48, 99, "Observation: gradual stabilization; no operational conclusion is implied.")
    pdf.showPage()

    _frame(pdf, 2, "Inspection and release notes", "Independent check sheet / built-in fonts / fixed annotation regions")
    _label(pdf, 48, 661, "REVIEW STATUS - CONTROLLED TEXT FIELD")
    pdf.setFillColor(HexColor("#163447"))
    pdf.setFont("Courier", 12)
    pdf.drawString(48, 633, "STATUS: PENDING")
    _label(pdf, 330, 661, "CHECK REFERENCE")
    pdf.setFillColor(HexColor("#163447"))
    pdf.setFont("Times-Roman", 14)
    pdf.drawString(330, 633, "CHECK-01")
    _table(pdf, 48, 579, [150, 220, 146], ["Control", "Method", "Recorded result"], [
        ("Harness inspection", "Visual continuity check", "PASS"),
        ("Sensor alignment", "Reference jig comparison", "PASS"),
        ("Data logging", "Synthetic checksum record", "PASS"),
        ("Safety interlock", "Non-operational simulation", "PASS"),
        ("Run documentation", "Independent field review", "PENDING"),
    ])
    pdf.setFont("Helvetica", 12)
    pdf.setFillColor(HexColor("#163447"))
    pdf.drawString(48, 359, "Review boundary")
    pdf.setFont("Times-Roman", 11)
    for offset, line in enumerate([
        "This record demonstrates isolated wording corrections in an existing PDF.",
        "Tables, vector lines, page dimensions and unrelated text must remain stable.",
        "The text fields above are separate, single-line built-in font spans.",
        "All values were invented for this demonstration and are not engineering advice.",
    ]):
        pdf.drawString(48, 330 - offset * 20, line)
    pdf.setStrokeColor(HexColor("#087D88"))
    pdf.setLineWidth(1)
    pdf.rect(48, 121, 516, 83, stroke=1, fill=0)
    pdf.setFont("Courier", 10)
    pdf.drawString(64, 175, "LOG CHANNELS: 08    SAMPLE INTERVAL: 05 MIN")
    pdf.drawString(64, 153, "DOCUMENT CLASS: SYNTHETIC / REVISION EXERCISE")
    pdf.showPage()

    _frame(pdf, 3, "Appendix - unchanged reference", "Control page / no requested edits / complete visual identity expected")
    pdf.setFont("Times-Roman", 12)
    pdf.setFillColor(HexColor("#163447"))
    pdf.drawString(48, 646, "UNCHANGED CONTROL PAGE")
    pdf.setFont("Times-Roman", 11)
    pdf.drawString(48, 617, "Reference dimensions and trace labels below must remain untouched.")
    _table(pdf, 48, 572, [172, 172, 172], ["Reference", "Unit", "Synthetic value"], [
        ("Housing width", "mm", "145.0"),
        ("Housing height", "mm", "92.0"),
        ("Mounting pitch", "mm", "110.0"),
        ("Trace sample", "count", "008"),
    ])
    pdf.setStrokeColor(HexColor("#163447"))
    pdf.setLineWidth(1)
    pdf.rect(119, 207, 314, 143, fill=0, stroke=1)
    pdf.line(119, 278.5, 433, 278.5)
    pdf.line(276, 207, 276, 350)
    for cx, cy in [(141, 229), (411, 229), (141, 328), (411, 328)]:
        pdf.circle(cx, cy, 6, fill=0, stroke=1)
    pdf.setFont("Courier", 10)
    pdf.setFillColor(HexColor("#087D88"))
    pdf.drawCentredString(197.5, 241, "REFERENCE ONLY")
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(HexColor("#526572"))
    pdf.drawCentredString(276, 186, "Vector reference diagram - arbitrary synthetic geometry")
    pdf.showPage()
    pdf.save()
    return path


def _rgb(page):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _difference_mask(first, second):
    red, green, blue = ImageChops.difference(first, second).split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue).point(lambda value: 255 if value else 0)


def independent_checks(source, result, plan):
    """独立读取文本并渲染；编辑范围取自原稿，而非引擎报告。"""
    page_checks = []
    with fitz.open(source) as original, fitz.open(result) as changed:
        if len(original) != len(changed):
            raise AssertionError("修改前后页数不一致")
        for index, (before, after) in enumerate(zip(original, changed), 1):
            if before.rect != after.rect or before.mediabox != after.mediabox:
                raise AssertionError("修改前后页面尺寸不一致")
            before_image, after_image = _rgb(before), _rgb(after)
            difference = _difference_mask(before_image, after_image)
            changed_pixels = difference.histogram()[255]
            outside = difference.copy()
            drawing = ImageDraw.Draw(outside)
            for edit in [item for item in plan if item["page"] == index]:
                spans = [span for block in before.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"] if span["text"] == edit["expected_text"]]
                if len(spans) != 1:
                    raise AssertionError("演示原稿的目标 span 不是唯一整段")
                box = fitz.Rect(spans[0]["bbox"])
                rectangle = (max(0, math.floor((box.x0 - 2) * 2)), max(0, math.floor((box.y0 - 2) * 2)), min(outside.width, math.ceil((box.x1 + 2) * 2)) - 1, min(outside.height, math.ceil((box.y1 + 2) * 2)) - 1)
                drawing.rectangle(rectangle, fill=0)
                if edit["expected_text"] in after.get_text() or edit["replacement"] not in after.get_text():
                    raise AssertionError("目标文字没有按计划精确替换")
            outside_changed = outside.histogram()[255]
            if outside_changed:
                raise AssertionError("目标框外存在像素变化")
            page_checks.append({"page": index, "width": before_image.width, "height": before_image.height, "changed_pixels": changed_pixels, "outside_changed_pixels": outside_changed})
    return page_checks


def demo(dest):
    """生成新目录内的扁平完整演示；失败时清理自身暂存。"""
    engine = load_engine()
    dest = engine._path(dest)
    if dest.exists() or dest.is_symlink():
        raise ValueError("演示目标目录必须不存在")
    dest.parent.mkdir(parents=True, exist_ok=True)
    engine._path(dest.parent)
    stage = Path(tempfile.mkdtemp(prefix="2903_演示暂存_", dir=dest.parent))
    try:
        source = generate_source(stage / "2903_工程记录原稿.pdf")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        (stage / "2903_修改计划.json").write_text(json.dumps(PLAN, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        intermediate = stage / "2903_中转结果"
        report = engine.edit_pdf(source, [dict(item) for item in PLAN], intermediate)
        for item in intermediate.iterdir():
            item.rename(stage / item.name)
        intermediate.rmdir()
        result = stage / "2903_修改结果.pdf"
        checks = independent_checks(source, result, PLAN)
        if source_sha != hashlib.sha256(source.read_bytes()).hexdigest():
            raise AssertionError("演示原稿发生变化")
        if checks[0]["changed_pixels"] == 0 or checks[1]["changed_pixels"] == 0 or checks[2]["changed_pixels"] != 0:
            raise AssertionError("演示修改页与未修改页的变化范围不符合计划")
        metrics = {"synthetic_demo": True, "pages": 3, "edits": 2, "rendering_dpi": 144, "source_unchanged": True, "all_page_dimensions_unchanged": True, "all_outside_pixels_unchanged": True, "unmodified_page_pixels_identical": True, "extracted_text_verified": True, "source_sha256": source_sha, "output_sha256": hashlib.sha256(result.read_bytes()).hexdigest(), "page_checks": checks, "engine_page_checks": report["page_checks"]}
        (stage / "2903_演示核验.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if dest.exists():
            raise ValueError("演示目标目录已经存在")
        os.rename(stage, dest)
        stage = None
        return metrics
    finally:
        if stage is not None:
            absolute_stage = stage.absolute()
            if (absolute_stage.parent != dest.parent.absolute()
                    or absolute_stage.resolve().parent != dest.parent.resolve()
                    or not absolute_stage.name.startswith("2903_演示暂存_")
                    or absolute_stage.is_symlink()
                    or getattr(absolute_stage.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise RuntimeError("演示暂存清理路径不安全，已停止删除")
            shutil.rmtree(stage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成自制工程记录并完成两处真实定点文字修改")
    parser.add_argument("--output", type=Path, default=BASE / "2903_演示结果")
    options = parser.parse_args()
    print(json.dumps(demo(options.output), ensure_ascii=False, indent=2))
