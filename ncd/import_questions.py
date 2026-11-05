#!/usr/bin/env python3
"""从指定复习题工作簿导入可见的 2026 题库，仅使用 Python 标准库。"""

import argparse
import hashlib
import json
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


SHEETS = {"2026单选": "single", "2026多选": "multiple"}
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def column_index(reference):
    result = 0
    for letter in re.match(r"[A-Z]+", reference).group(0):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def cell_text(cell, shared):
    kind = cell.get("t", "")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", NS))
    value = cell.find("x:v", NS)
    raw = value.text if value is not None and value.text else ""
    if kind == "s":
        return shared[int(raw)] if raw else ""
    if kind == "e":
        raise ValueError(f"单元格 {cell.get('r')} 存在公式错误：{raw}")
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
                cells = {column_index(c.get("r")): clean_text(cell_text(c, shared)) for c in row.findall("x:c", NS)}
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
