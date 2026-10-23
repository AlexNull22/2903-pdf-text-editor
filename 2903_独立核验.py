# SPDX-License-Identifier: AGPL-3.0-or-later
"""用独立 Poppler 渲染器和 pypdf 复核；不调用修改引擎。"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

import pymupdf
from PIL import Image, ImageChops, ImageDraw
from pypdf import PdfReader


def verify(source, result, edits, renderer):
    source, result, renderer = Path(source), Path(result), Path(renderer)
    before, after = PdfReader(source), PdfReader(result)
    if len(before.pages) != len(after.pages):
        raise AssertionError("页数改变")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    original_targets = []
    with pymupdf.open(source) as doc:
        for edit in edits:
            spans = [s for b in doc[edit["page"] - 1].get_text("dict")["blocks"]
                     for line in b.get("lines", []) for s in line["spans"]
                     if s["text"] == edit["expected_text"]]
            if len(spans) != 1:
                raise AssertionError("原稿目标定位不唯一")
            original_targets.append((edit["page"], list(spans[0]["bbox"])))
    with tempfile.TemporaryDirectory(prefix="2903_独立渲染_") as work:
        work = Path(work)
        if (work.resolve().parent != Path(tempfile.gettempdir()).resolve()
                or not work.name.startswith("2903_独立渲染_") or work.is_symlink()
                or getattr(work.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError("独立渲染暂存路径异常")
        for path, prefix in ((source, "2903_原稿"), (result, "2903_结果")):
            process = subprocess.run([str(renderer), "-r", "144", "-png", str(path), str(work / prefix)],
                                     capture_output=True, timeout=90)
            if process.returncode:
                raise RuntimeError("Poppler 渲染失败：" + process.stderr.decode(errors="replace"))
        checks = []
        for number, (first, second) in enumerate(zip(before.pages, after.pages), 1):
            if list(first.mediabox) != list(second.mediabox) or list(first.cropbox) != list(second.cropbox):
                raise AssertionError("pypdf 页面边界改变")
            expected_lines = Counter((first.extract_text() or "").splitlines())
            for item in edits:
                if item["page"] == number:
                    if expected_lines[item["expected_text"]] != 1:
                        raise AssertionError("pypdf 原稿文字不唯一")
                    expected_lines[item["expected_text"]] -= 1
                    expected_lines[item["replacement"]] += 1
            if +expected_lines != Counter((second.extract_text() or "").splitlines()):
                raise AssertionError("pypdf 全部非编辑行或替换文字不符")
            with Image.open(work / f"2903_原稿-{number}.png") as a, Image.open(work / f"2903_结果-{number}.png") as b:
                if a.size != b.size:
                    raise AssertionError("Poppler 图像尺寸改变")
                channels = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).split()
                changed = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2]).point(lambda v: 255 if v else 0)
                outside = changed.copy()
                draw = ImageDraw.Draw(outside)
                for page, box in original_targets:
                    if page == number:
                        draw.rectangle((math.floor((box[0] - 2) * 2), math.floor((box[1] - 2) * 2),
                                        math.ceil((box[2] + 2) * 2) - 1, math.ceil((box[3] + 2) * 2) - 1), fill=0)
                outside_count = outside.histogram()[255]
                if outside_count:
                    raise AssertionError(f"Poppler 第 {number} 页框外 {outside_count} 像素变化")
                changes = changed.histogram()[255]
                if number not in [e["page"] for e in edits] and changes:
                    raise AssertionError("Poppler 未修改页出现差异")
                checks.append(dict(page=number, width=a.width, height=a.height,
                                   changed_pixels=changes, outside_changed_pixels=outside_count))
    if original_hash != hashlib.sha256(source.read_bytes()).hexdigest():
        raise AssertionError("原稿改变")
    version = subprocess.run([str(renderer), "-v"], capture_output=True, text=True, timeout=10)
    return dict(independent_verification=True, renderer=(version.stderr or version.stdout).splitlines()[0],
                text_reader="pypdf", rendering_dpi=144, pages=len(before.pages), edits=len(edits),
                all_text_lines_verified=True, all_page_dimensions_unchanged=True,
                outside_changed_pixels=0, unmodified_page_pixels_identical=True,
                source_sha256=original_hash, output_sha256=hashlib.sha256(result.read_bytes()).hexdigest(),
                page_checks=checks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--renderer", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("报告已存在，拒绝覆盖")
    renderer = args.renderer or shutil.which("pdftoppm")
    if not renderer:
        parser.error("找不到 Poppler；请用 --renderer 指定 pdftoppm 可执行文件")
    metrics = verify(args.source, args.result, json.loads(args.plan.read_text(encoding="utf-8-sig")), renderer)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(metrics, output, ensure_ascii=False, indent=2)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
