"""用 ReportLab 和支持简体中文的 TrueType 字体重建模拟档案。"""

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


OUTPUT = Path(__file__).resolve().parent
FONT = "SampleCJK"
WIDTH, HEIGHT = A4
MARGIN = 48
CONTENT_WIDTH = WIDTH - 2 * MARGIN
INK = HexColor("#172834")
MUTED = HexColor("#475e6a")
ACCENT = HexColor("#146760")
LINE = HexColor("#c9d9db")
PANEL = HexColor("#edf6f4")
PALE = HexColor("#f5f8f9")
PROJECT_A = "青岚站机房基础设施更新"
PROJECT_B = "松泉站业务设备采购"
ASSETS = (
    ("QL-SRV-001", "综合应用服务器", "正面 U4-U5"),
    ("QL-SW-001", "汇聚交换机", "正面 U10"),
    ("QL-PDU-001", "机柜配电单元", "背面 U1"),
)


def label(pdf, x, y, value, size=12, color=INK, align="left"):
    pdf.setFont(FONT, size)
    pdf.setFillColor(color)
    if align == "right":
        pdf.drawRightString(x, y, value)
    elif align == "center":
        pdf.drawCentredString(x, y, value)
    else:
        pdf.drawString(x, y, value)


def rectangle(pdf, x, y, width, height, fill, stroke=None):
    pdf.setFillColor(fill)
    if stroke is not None:
        pdf.setStrokeColor(stroke)
    pdf.rect(x, y, width, height, fill=1, stroke=int(stroke is not None))


def rule(pdf, y, color=LINE):
    pdf.setStrokeColor(color)
    pdf.setLineWidth(0.6)
    pdf.line(MARGIN, y, WIDTH - MARGIN, y)


def page(pdf, title, project, code, current=1, total=1):
    rectangle(pdf, MARGIN, HEIGHT - 59, 5, 18, ACCENT)
    label(pdf, MARGIN + 15, HEIGHT - 54, "机房与联网设备台账", 11, ACCENT)
    label(pdf, WIDTH - MARGIN, HEIGHT - 54, "模拟资料", 11, ACCENT, "right")
    rule(pdf, HEIGHT - 72)
    label(pdf, MARGIN, HEIGHT - 118, title, 27)
    label(pdf, MARGIN, HEIGHT - 147, project, 14, MUTED)
    label(pdf, WIDTH - MARGIN, HEIGHT - 147, code, 11, MUTED, "right")
    rule(pdf, 75)
    label(pdf, MARGIN, 53, "自制样例，仅供原型演示。全部名称、编号和记录均为虚构。", 10, MUTED)
    label(pdf, WIDTH - MARGIN, 53, f"{current} / {total}", 10, MUTED, "right")


def section(pdf, y, heading, lines):
    label(pdf, MARGIN, y, heading, 15, ACCENT)
    for index, line in enumerate(lines, start=1):
        label(pdf, MARGIN, y - index * 24 - 4, line)


def table(pdf, top, headings, widths, rows):
    row_height = 38
    for index, row in enumerate((headings, *rows)):
        y = top - (index + 1) * row_height
        fill = PANEL if index == 0 else (PALE if index % 2 else white)
        rectangle(pdf, MARGIN, y, CONTENT_WIDTH, row_height, fill)
        x = MARGIN
        for width, value in zip(widths, row, strict=True):
            label(pdf, x + 12, y + 13, value, 11 if index == 0 else 12,
                  ACCENT if index == 0 else INK)
            x += width
        rule(pdf, y)


def quantity(pdf):
    page(pdf, "工程量清单", PROJECT_A, "QL-2026-01")
    section(pdf, 645, "设备及安装工程量", ("综合机房 A01 机柜 · 更新设备清单",))
    table(pdf, 588, ("设备编号", "设备名称", "数量", "计划安装位"),
          (120, 153, 66, 162),
          tuple((code, name, "1 台", location) for code, name, location in ASSETS))
    section(pdf, 394, "计价说明", (
        "样例清单仅列设备和安装数量，设备单价与分项金额均未单列。",
        "安装位置以施工设计图为参考，以最终的台账核实记录为准。",
    ))


def elevation(pdf, left, base, side, devices):
    tick = 24
    rack_width = 177
    label(pdf, left + 29 + rack_width / 2, base + 12 * tick + 19, side, 13, ACCENT, "center")
    for unit in range(1, 13):
        y = base + (unit - 1) * tick
        rectangle(pdf, left + 29, y, rack_width, tick, PALE, LINE)
        label(pdf, left + 21, y + 8, f"{unit:02}", 9, MUTED, "right")
    for start, height, description in devices:
        y = base + (start - 1) * tick + 1
        rectangle(pdf, left + 30, y, rack_width - 2, height * tick - 2, PANEL, ACCENT)
        label(pdf, left + 38, y + height * tick / 2 - 4, description, 10, INK)


def design(pdf):
    page(pdf, "施工设计图", PROJECT_A, "QL-2026-01")
    section(pdf, 645, "综合机房 · A01 机柜安装立面", (
        "柜高 12U，U 位由下往上编号。空白格表示本图预留位置。",
    ))
    elevation(pdf, MARGIN + 4, 252, "正面", (
        (4, 2, "QL-SRV-001 · 2U"), (10, 1, "QL-SW-001 · 1U"),
    ))
    elevation(pdf, MARGIN + 255, 252, "背面", ((1, 1, "QL-PDU-001 · 1U"),))
    section(pdf, 203, "图纸说明", ("本图仅示意设备标高及占用位置，供台账查阅。",))


def contract(pdf):
    page(pdf, "采购安装合同（样例）", PROJECT_A, "QL-2026-01")
    section(pdf, 645, "采购与安装范围", (
        "交付一台综合应用服务器、一台汇聚交换机和一台机柜配电单元。",
        "设备安装于青岚站综合机房 A01 机柜，随设备提供清单和验收资料。",
    ))
    section(pdf, 532, "交付验收", (
        "以工程量清单核对设备数量，以施工设计图核对拟安装位置。",
        "设备到场后记录设备编号、实际安装位置和附件交接情况。",
    ))
    section(pdf, 419, "价格记录", (
        "本演示合同未单列任何设备的购置价格。",
    ))


def acceptance_a(pdf):
    title = "项目验收报告"
    page(pdf, title, PROJECT_A, "QL-2026-01", 1, 2)
    section(pdf, 645, "验收范围", (
        "青岚站综合机房 A01 机柜内三台模拟设备的到货与安装情况。",
        "本页为资料交接摘要，设备现场核对结果见第 2 页。",
    ))
    section(pdf, 532, "资料交接", (
        "工程量清单、施工设计图和采购安装合同随项目归档。",
        "综合应用服务器另随附一份设备专属交接记录。",
    ))
    pdf.showPage()
    page(pdf, title, PROJECT_A, "QL-2026-01", 2, 2)
    section(pdf, 645, "现场设备核对表", ("青岚站综合机房 · A01 机柜",))
    table(pdf, 588, ("设备编号", "设备名称", "验收位置", "模拟结果"),
          (120, 149, 130, 102),
          tuple((*asset, "已核对") for asset in ASSETS))
    section(pdf, 394, "位置复核", (
        "综合应用服务器占 2U，汇聚交换机和机柜配电单元各占 1U。",
        "记录为演示初始位置，后续移位以台账的现行位置为准。",
    ))


def device_record(pdf):
    page(pdf, "设备专属交接记录", PROJECT_A, "QL-SRV-001")
    section(pdf, 645, "设备身份", (
        "设备名称　综合应用服务器",
        "设备编号　QL-SRV-001",
        "交接位置　青岚站综合机房 A01 机柜正面 U4-U5",
    ))
    section(pdf, 516, "交接范围", (
        "随设备交接机架导轨和标识。设备占用连续两个 U 位。",
        "交接记录随设备单独归档，项目验收情况可查项目验收报告。",
    ))


def acceptance_b(pdf):
    page(pdf, "项目验收报告", PROJECT_B, "SQ-2026-01")
    section(pdf, 645, "现场设备核对表", ("松泉站通信机房 · B01 机柜",))
    table(pdf, 588, ("设备编号", "设备名称", "验收位置", "模拟结果"),
          (120, 149, 130, 102),
          (("SQ-SRV-001", "松泉应用服务器", "正面 U6-U7", "已核对"),))
    section(pdf, 468, "位置复核", (
        "松泉应用服务器占 2U，位置为通信机房 B01 机柜正面。",
        "本份档案随松泉站业务设备采购项目归档。",
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", default="/Library/Fonts/Arial Unicode.ttf",
                        help="支持简体中文的 TrueType 字体路径")
    args = parser.parse_args()
    pdfmetrics.registerFont(TTFont(FONT, args.font))
    output_documents = (
        ("site-a-quantity.pdf", "工程量清单", quantity),
        ("site-a-design.pdf", "施工设计图", design),
        ("site-a-contract.pdf", "采购安装合同（样例）", contract),
        ("site-a-acceptance.pdf", "项目验收报告（青岚站）", acceptance_a),
        ("site-a-device.pdf", "设备专属交接记录", device_record),
        ("site-b-acceptance.pdf", "项目验收报告（松泉站）", acceptance_b),
    )
    for filename, title, draw in output_documents:
        pdf = Canvas(str(OUTPUT / filename), pagesize=A4, pageCompression=1, invariant=1)
        pdf.setTitle(title)
        pdf.setSubject("机房与联网设备台账 · 自制模拟档案")
        pdf.setAuthor("机房与联网设备台账演示")
        draw(pdf)
        pdf.save()


if __name__ == "__main__":
    main()
