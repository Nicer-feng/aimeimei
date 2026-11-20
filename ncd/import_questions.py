#!/usr/bin/env python3
"""从指定复习题工作簿导入可见的 2026 题库，仅使用 Python 标准库。"""

import argparse
import hashlib
import json
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from zipfile import ZipFile


SHEETS = {"2026单选": "single", "2026多选": "multiple"}
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# 中文内置日期格式不会写入 numFmts，需按 Excel 的 zh-cn 格式表补齐。
# https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat
BUILTIN_FORMATS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00",
    9: "0%", 10: "0.00%", 14: "mm-dd-yy", 15: "d-mmm-yy",
    16: "d-mmm", 17: "mmm-yy", 49: "@",
    27: 'yyyy"年"m"月"', 28: 'm"月"d"日"', 29: 'm"月"d"日"',
    30: "m-d-yy", 31: 'yyyy"年"m"月"d"日"', 36: 'yyyy"年"m"月"',
    50: 'yyyy"年"m"月"', 51: 'm"月"d"日"', 52: 'yyyy"年"m"月"',
    53: 'm"月"d"日"', 54: 'm"月"d"日"', 57: 'yyyy"年"m"月"',
    58: 'm"月"d"日"',
}


def read_number_formats(archive):
    if "xl/styles.xml" not in archive.namelist():
        return ["General"]
    styles = ET.fromstring(archive.read("xl/styles.xml"))
    custom = {int(node.get("numFmtId")): node.get("formatCode", "")
              for node in styles.findall("x:numFmts/x:numFmt", NS)}
    formats = []
    for node in styles.findall("x:cellXfs/x:xf", NS):
        identifier = int(node.get("numFmtId", "0"))
        formats.append(custom.get(identifier, BUILTIN_FORMATS.get(identifier, f"不支持的内置格式 {identifier}")))
    return formats or ["General"]


def excel_date(number, date1904=False):
    days = int(number)
    if days < 0:
        raise ValueError("Excel 日期序号不能为负数")
    if date1904:
        value = date(1904, 1, 1) + timedelta(days=days)
    else:
        # Excel 为兼容旧表保留了不存在的 1900-02-29（序号 60）。
        if days == 60:
            return 1900, 2, 29
        if days == 0:
            return 1900, 1, 0
        value = date(1899, 12, 31) + timedelta(days=days - (days > 60))
    return value.year, value.month, value.day


def format_number(raw, format_code, date1904=False):
    """按原单元格格式显示，不能仅凭数值大小猜测日期或百分比。"""
    try:
        number = Decimal(raw)
        if not number.is_finite():
            raise ValueError("单元格包含无效数字")
        if format_code in {"General", "@"}:
            # Excel 数值精度为 15 位，去除 XML 中浮点序列化产生的尾差。
            with localcontext() as context:
                context.prec = 15
                text = format(+number, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text

        # 支持本题库使用的完整日期、年月和月日；保留原表的显示粒度。
        date_format = format_code.split(";", 1)[0]
        tokens = re.findall(r'"[^"]*"|\\.|yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|.', date_format)
        date_tokens = {token for token in tokens if token in {"yyyy", "yy", "m", "mm", "mmm", "mmmm", "d", "dd", "ddd", "dddd"}}
        if date_tokens and all(token in date_tokens or token.startswith(('"', '\\')) or token in "-/ .年月日" for token in tokens):
            if date_tokens & {"mmm", "mmmm", "ddd", "dddd"}:
                raise ValueError(f"暂不支持日期格式：{format_code}")
            year, month, day = excel_date(number, date1904)
            replacements = {"yyyy": f"{year:04d}", "yy": f"{year % 100:02d}",
                            "m": str(month), "mm": f"{month:02d}", "d": str(day), "dd": f"{day:02d}"}
            return "".join(token[1:-1] if token.startswith('"') else token[1:] if token.startswith('\\') else replacements.get(token, token) for token in tokens)

        numeric = re.fullmatch(r"(#,##)?(0+)(?:\.(0+))?(%)?", format_code)
        if numeric:
            grouping, integer_digits, decimals, percent = numeric.groups()
            precision = len(decimals or "")
            scaled = number * 100 if percent else number
            rounded = scaled.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
            text = format(rounded, f",.{precision}f" if grouping else f".{precision}f")
            if not grouping and len(integer_digits) > 1:
                sign = "-" if text.startswith("-") else ""
                digits, dot, fraction = text.lstrip("-").partition(".")
                text = sign + digits.zfill(len(integer_digits)) + dot + fraction
            return text + ("%" if percent else "")
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError(f"无法按格式 {format_code} 显示数值") from exc
    # 新格式必须明确适配，不能悄悄回退为底层日期序号或比例数值。
    raise ValueError(f"暂不支持数字格式：{format_code}")


def clean_text(value):
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def column_index(reference):
    result = 0
    for letter in re.match(r"[A-Z]+", reference).group(0):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def cell_text(cell, shared, number_formats=None, date1904=False):
    kind = cell.get("t", "")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", NS))
    value = cell.find("x:v", NS)
    raw = value.text if value is not None and value.text else ""
    if cell.find("x:f", NS) is not None and not raw:
        raise ValueError(f"单元格 {cell.get('r')} 的公式没有缓存结果，请先用表格软件重新计算并保存")
    if kind == "s":
        return shared[int(raw)] if raw else ""
    if kind == "e":
        raise ValueError(f"单元格 {cell.get('r')} 存在公式错误：{raw}")
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if raw and kind in {"", "n"}:
        formats = number_formats or ["General"]
        style = int(cell.get("s", "0"))
        if not 0 <= style < len(formats):
            raise ValueError(f"单元格 {cell.get('r')} 引用了无效格式")
        try:
            return format_number(raw, formats[style], date1904)
        except ValueError as exc:
            raise ValueError(f"单元格 {cell.get('r')}：{exc}") from exc
    return raw


def import_workbook(source):
    source = Path(source)
    records = {}
    issues = []
    sheet_counts = {}
    with ZipFile(source) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in node.findall(".//x:t", NS)) for node in root]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in relationships}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        properties = workbook.find("x:workbookPr", NS)
        date1904 = properties is not None and properties.get("date1904", "0").lower() in {"1", "true"}
        number_formats = read_number_formats(archive)
        sheets = {s.get("name"): s for s in workbook.findall("x:sheets/x:sheet", NS)}
        for name, question_type in SHEETS.items():
            if name not in sheets or sheets[name].get("state", "visible") != "visible":
                raise ValueError(f"找不到可见工作表：{name}")
            target = targets[sheets[name].get(f"{{{REL_NS}}}id")]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            root = ET.fromstring(archive.read(member))
            count = 0
            for row in root.findall("x:sheetData/x:row", NS):
                row_number = int(row.get("r"))
                try:
                    cells = {column_index(c.get("r")): clean_text(cell_text(c, shared, number_formats, date1904)) for c in row.findall("x:c", NS)}
                except ValueError as exc:
                    raise ValueError(f"{name} 第 {row_number} 行：{exc}") from exc
                if row_number == 1:
                    if [cells.get(i) for i in range(5)] != ["序号", "分类", "题目", "选项个数", "答案"]:
                        raise ValueError(f"{name} 的表头与预期不一致")
                    continue
                question = cells.get(2, "")
                if not question:
                    continue
                try:
                    declared = int(cells.get(3, "0"))
                except ValueError as exc:
                    raise ValueError(f"{name} 第 {row_number} 行选项个数无效") from exc
                options = [{"key": chr(65 + col - 5), "text": text} for col, text in sorted(cells.items()) if 5 <= col < 31 and text]
                if not 2 <= len(options) <= 26:
                    raise ValueError(f"{name} 第 {row_number} 行缺少有效选项")
                answer_raw = unicodedata.normalize("NFKC", cells.get(4, "")).upper()
                if not re.fullmatch(r"[A-Z]+", answer_raw) or len(set(answer_raw)) != len(answer_raw):
                    raise ValueError(f"{name} 第 {row_number} 行答案格式无效")
                answer = sorted(answer_raw)
                option_map = {item["key"]: item["text"] for item in options}
                if any(letter not in option_map for letter in answer):
                    raise ValueError(f"{name} 第 {row_number} 行答案引用了空选项")
                if question_type == "single" and len(answer) != 1:
                    raise ValueError(f"{name} 第 {row_number} 行单选题含多个答案")
                if declared != len(options):
                    issues.append({"sheet": name, "row": row_number, "issue": "选项个数与实际非空选项不一致", "declared": declared, "actual": len(options)})
                identity = json.dumps([question_type, cells.get(1, ""), question, options, answer], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                key = hashlib.sha256(identity.encode()).hexdigest()[:20]
                location = {"sheet": name, "row": row_number, "number": cells.get(0, "")}
                if key in records:
                    records[key]["sources"].append(location)
                else:
                    records[key] = {"id": key, "type": question_type, "category": cells.get(1, ""), "question": question, "options": options, "answer": answer, "answer_text": [option_map[letter] for letter in answer], "sources": [location]}
                count += 1
            sheet_counts[name] = count
    return {"schema_version": 1, "source_file": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "sheet_counts": sheet_counts, "source_count": sum(sheet_counts.values()), "question_count": len(records), "issues": issues, "questions": list(records.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("questions.json"))
    args = parser.parse_args()
    result = import_workbook(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("sheet_counts", "source_count", "question_count", "issues")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
