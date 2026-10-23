# SPDX-License-Identifier: AGPL-3.0-or-later
"""2903：受限 PDF 整段文字修改；不支持的输入直接拒绝。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

import pymupdf as fitz
from PIL import Image, ImageChops, ImageDraw, ImageOps

DPI = 144
FONTS = {
    "Helvetica": "helv", "Helvetica-Bold": "hebo",
    "Helvetica-Oblique": "heit", "Helvetica-BoldOblique": "hebi",
    "Times-Roman": "tiro", "Times-Bold": "tibo",
    "Times-Italic": "tiit", "Times-BoldItalic": "tibi",
    "Courier": "cour", "Courier-Bold": "cobo",
    "Courier-Oblique": "coit", "Courier-BoldOblique": "cobi",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if item.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("不接受符号链接或目录连接点路径")
    return path


def _spans(page):
    result = []
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                result.append(dict(span, direction=line["dir"]))
    return result


def _ascii(text):
    return (isinstance(text, str) and 1 <= len(text) <= 200
            and text == text.strip() and all(32 <= ord(c) <= 126 for c in text))


def _intersection(a, b):
    rect = fitz.Rect(a) & fitz.Rect(b)
    return not rect.is_empty and rect.get_area() > 0


def _image(page):
    pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csRGB, alpha=False, annots=True)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _changed(a, b):
    diff = ImageChops.difference(a, b)
    r, g, blue = diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), blue).point(lambda v: 255 if v else 0)


def _mask_box(rect, size):
    scale = DPI / 72
    return (max(0, math.floor(rect[0] * scale)), max(0, math.floor(rect[1] * scale)),
            min(size[0] - 1, math.ceil(rect[2] * scale) - 1),
            min(size[1] - 1, math.ceil(rect[3] * scale) - 1))


def _preflight(doc, edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 20:
        raise ValueError("修改计划必须为包含 1 至 20 项的数组")
    if (not doc.is_pdf or doc.is_encrypted or doc.needs_pass or doc.is_repaired
            or (doc.metadata or {}).get("encryption")):
        raise ValueError("仅接受无需修复、未加密的正常 PDF")
    if not 1 <= len(doc) <= 20 or doc.get_sigflags() > 0 or doc.embfile_count() or doc.get_ocgs():
        raise ValueError("页数须为 1 至 20；不接受签名、附件或图层")
    span_pages = []
    for page in doc:
        if (page.rotation != 0 or page.cropbox != page.mediabox
                or page.rect.x0 != 0 or page.rect.y0 != 0
                or not 72 <= page.rect.width <= 1200 or not 72 <= page.rect.height <= 1200):
            raise ValueError("不支持旋转、裁剪或超出尺寸范围的页面")
        if list(page.widgets()) or list(page.annots()) or page.get_links():
            raise ValueError("不接受包含表单、批注、签名或链接的 PDF")
        span_pages.append(_spans(page))
    planned = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"page", "expected_text", "replacement"}:
            raise ValueError("计划项目仅允许 page、expected_text、replacement 三个字段")
        number, expected, replacement = edit["page"], edit["expected_text"], edit["replacement"]
        if type(number) is not int or not 1 <= number <= len(doc):
            raise ValueError("页码须为范围内的整数，从 1 开始")
        if not _ascii(expected) or not _ascii(replacement) or expected == replacement:
            raise ValueError("文字须为 1 至 200 个可打印 ASCII 字符，无首尾空格，且确实发生修改")
        page = doc[number - 1]
        spans = span_pages[number - 1]
        hits = [s for s in spans if s["text"] == expected]
        if len(hits) != 1:
            raise ValueError(f"第 {number} 页的整段文字匹配须恰好一处，实际为 {len(hits)} 处")
        target = hits[0]
        font = target["font"]
        if font not in FONTS or tuple(target["direction"]) != (1.0, 0.0):
            raise ValueError("仅支持水平的标准 Helvetica、Times 或 Courier 字体")
        refs = [f for f in page.get_fonts() if f[3] == font]
        if not refs or any(doc.extract_font(f[0])[3] for f in refs):
            raise ValueError("不支持嵌入或自定义字体")
        traces = [t for t in page.get_texttrace()
                  if "".join(chr(c[0]) for c in t["chars"]) == expected]
        if (len(traces) != 1 or traces[0]["type"] != 0
                or traces[0]["opacity"] != 1 or tuple(traces[0]["dir"]) != (1.0, 0.0)):
            raise ValueError("不支持隐藏、透明、描边、分片或变形文字")
        box = fitz.Rect(target["bbox"])
        if box.is_empty or box.is_infinite or not all(math.isfinite(x) for x in box):
            raise ValueError("文字边界无效")
        size = target["size"]
        alias = FONTS[font]
        original_width = fitz.get_text_length(expected, fontname=alias, fontsize=size)
        if abs(original_width - box.width) > 0.05:
            raise ValueError("不支持非标准字符间距或水平缩放")
        width = fitz.get_text_length(replacement, fontname=alias, fontsize=size)
        if width > box.width + 0.01:
            raise ValueError("替换文字超出原宽度；不会自动缩小字体")
        mask = box + (-2, -2, 2, 2)
        if not page.rect.contains(mask):
            raise ValueError("修改框过于靠近页面边缘")
        if any(s is not target and _intersection(mask, s["bbox"]) for s in spans):
            raise ValueError("修改框与其他文字相交")
        # bboxlog 同时覆盖矢量、图像、渐变背景；白底必须是没有这些对象的空白区域。
        if any(kind not in {"fill-text", "stroke-text", "ignore-text"} and _intersection(mask, rect)
               for kind, rect, *_ in page.get_bboxlog()):
            raise ValueError("修改框与图片、矢量或背景相交；仅支持空白白底")
        if any(p["page"] == number and _intersection(mask, p["mask_bbox"]) for p in planned):
            raise ValueError("计划中的修改区域重复或相交")
        planned.append(dict(edit, bbox=list(box), mask_bbox=list(mask), origin=list(target["origin"]),
                            font=font, font_alias=alias, font_size=size,
                            color=target["color"], insertion_color=list(traces[0]["color"])))
    return planned, span_pages


def edit_pdf(source: Path, edits: list[dict], output_dir: Path) -> dict:
    """生成一个新目录。任何预检/核验失败均不发布结果，且不写入原稿。"""
    started = time.perf_counter()
    source, output_dir = _path(source), _path(output_dir)
    if not source.is_file() or source.suffix.lower() != ".pdf" or not 0 < source.stat().st_size <= 25_000_000:
        raise ValueError("原稿须为不超过 25 MB 的普通 PDF 文件")
    if output_dir.exists():
        raise ValueError("输出目录已存在；请选择全新的目录")
    if not output_dir.parent.is_dir():
        raise ValueError("输出目录的父目录不存在")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    stage = None
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            planned, originals = _preflight(doc, edits)
            shapes = [(list(p.mediabox), list(p.cropbox), p.rotation) for p in doc]
            toc = doc.get_toc()
            stage = Path(tempfile.mkdtemp(prefix="2903_暂存_", dir=output_dir.parent))
            before = []
            for page in doc:
                picture = _image(page)
                picture.save(stage / f"2903_原稿第{page.number + 1}页.png")
                before.append(picture)
            for index in range(len(doc)):
                page = doc[index]
                current = [p for p in planned if p["page"] == index + 1]
                for item in current:
                    page.add_redact_annot(item["bbox"], fill=(1, 1, 1), cross_out=False)
                if current:
                    page.apply_redactions(images=0, graphics=0, text=0)
                    for item in current:
                        page.insert_text(item["origin"], item["replacement"], fontsize=item["font_size"],
                                         fontname=item["font_alias"], color=item["insertion_color"])
            result = stage / "2903_修改结果.pdf"
            doc.save(result, garbage=4, deflate=True)
        checks = []
        with fitz.open(result) as verified:
            if len(verified) != len(shapes) or verified.get_toc() != toc:
                raise RuntimeError("核验失败：页数或目录发生变化")
            for index, page in enumerate(verified):
                if (list(page.mediabox), list(page.cropbox), page.rotation) != shapes[index]:
                    raise RuntimeError("核验失败：页面几何发生变化")
                current = [p for p in planned if p["page"] == index + 1]
                expected_spans = Counter(s["text"] for s in originals[index])
                for item in current:
                    expected_spans[item["expected_text"]] -= 1
                    expected_spans[item["replacement"]] += 1
                actual_spans = _spans(page)
                if +expected_spans != Counter(s["text"] for s in actual_spans):
                    raise RuntimeError("核验失败：抽取文字与计划不一致")
                for item in current:
                    matches = [s for s in actual_spans if s["text"] == item["replacement"]
                               and abs(s["origin"][0] - item["origin"][0]) < 0.01
                               and abs(s["origin"][1] - item["origin"][1]) < 0.01
                               and s["font"] == item["font"]
                               and abs(s["size"] - item["font_size"]) < 0.01
                               and s["color"] == item["color"]]
                    if len(matches) != 1:
                        raise RuntimeError("核验失败：替换文字的位置、字体、大小或颜色不一致")
                after = _image(page)
                if after.size != before[index].size:
                    raise RuntimeError("核验失败：渲染尺寸发生变化")
                diff = _changed(before[index], after)
                mask = Image.new("L", diff.size, 0)
                draw = ImageDraw.Draw(mask)
                for item in current:
                    box = _mask_box(item["mask_bbox"], diff.size)
                    draw.rectangle(box, fill=255)
                    if not diff.crop((box[0], box[1], box[2] + 1, box[3] + 1)).getbbox():
                        raise RuntimeError("核验失败：指定区域没有产生可见文字变化")
                outside = ImageChops.multiply(diff, ImageOps.invert(mask)).histogram()[255]
                if outside:
                    raise RuntimeError(f"核验失败：第 {index + 1} 页修改框外有 {outside} 个像素变化")
                after.save(stage / f"2903_结果第{index + 1}页.png")
                checks.append(dict(page=index + 1, width=after.width, height=after.height,
                                   changed_pixels=diff.histogram()[255], outside_changed_pixels=outside))
        if sha256(source) != digest:
            raise RuntimeError("处理中原稿已被其他程序改变，结果未发布")
        report = dict(schema_version=1, independent_demo=True, pages=len(shapes), edits=planned,
                      rendering_dpi=DPI, source_file=source.name, source_sha256=digest,
                      output_sha256=sha256(result), page_checks=checks,
                      all_outside_pixels_unchanged=True, source_unchanged=True,
                      drive_live_integration_configured=False,
                      pymupdf_version=fitz.VersionBind,
                      elapsed_seconds=round(time.perf_counter() - started, 3))
        (stage / "2903_核验报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _path(source)
        _path(output_dir)
        if output_dir.exists():
            raise ValueError("输出目录已出现，结果未覆盖")
        os.rename(stage, output_dir)
        stage = None
        return report
    except (fitz.FileDataError, fitz.EmptyFileError) as error:
        raise ValueError("PDF 无法正常读取") from error
    finally:
        if stage is not None and stage.exists():
            # 只清理本次自行创建的直接子目录；不跟随链接删除其他目录。
            if (stage.parent == output_dir.parent and stage.name.startswith("2903_暂存_")
                    and not stage.is_symlink() and stage.resolve().parent == output_dir.parent.resolve()):
                shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="输入 PDF")
    parser.add_argument("--plan", required=True, type=Path, help="UTF-8 修改计划 JSON 数组")
    parser.add_argument("--output", required=True, type=Path, help="全新的结果目录")
    args = parser.parse_args()
    try:
        plan = json.loads(_path(args.plan).read_text(encoding="utf-8-sig"))
        report = edit_pdf(args.source, plan, args.output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"未生成结果：{error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
