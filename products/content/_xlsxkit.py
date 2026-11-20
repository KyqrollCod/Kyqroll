"""Shared styling helpers for the Coconala content-market Excel templates.

Every workbook built with this kit: Meiryo UI, dark header row, grey calculated cells,
thin borders, empty author metadata (Coconala help: don't leak the seller's name).
"""
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Meiryo UI"
INK = "2F3A4A"
HEAD_FILL = PatternFill("solid", fgColor=INK)
HEAD_FONT = Font(name=FONT, bold=True, color="FFFFFF")
CALC_FILL = PatternFill("solid", fgColor="EEF2F6")
WARN_FILL = PatternFill("solid", fgColor="F8D7DA")
OK_FILL = PatternFill("solid", fgColor="E3F4E8")
BODY = Font(name=FONT)
_thin = Side(style="thin", color="C9D1DA")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def guide_sheet(ws, lines, width=110):
    """lines: list of (text, kind) where kind is 'title', 'h' or None."""
    for i, (text, kind) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        if kind == "title":
            c.font = Font(name=FONT, bold=True, size=16, color=INK)
        elif kind == "h":
            c.font = Font(name=FONT, bold=True, size=12, color=INK)
        else:
            c.font = BODY
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = width
    ws.sheet_view.showGridLines = False


def header(ws, cols, height=32, freeze="B2"):
    """cols: list of (name, width)."""
    for j, (name, w) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=name)
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = w
    ws.row_dimensions[1].height = height
    if freeze:
        ws.freeze_panes = freeze


def style_rows(ws, first, last, ncols, calc=(), dates=(), money=(), pct=(), wrap=(), ints=()):
    for r in range(first, last + 1):
        for j in range(1, ncols + 1):
            c = ws.cell(row=r, column=j)
            c.font = BODY
            c.border = BORDER
            if j in calc:
                c.fill = CALC_FILL
            if j in dates:
                c.number_format = "yyyy/mm/dd"
            if j in money:
                c.number_format = "#,##0"
            if j in pct:
                c.number_format = "0%"
            if j in ints:
                c.number_format = "0"
            if j in wrap:
                c.alignment = Alignment(wrap_text=True, vertical="top")


def dropdown(ws, values, ref):
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(ref)
    return dv


def dropdown_ref(ws, formula, ref):
    dv = DataValidation(type="list", formula1=formula, allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(ref)
    return dv


def finish(wb, title, out):
    for w in wb.worksheets:
        w.sheet_properties.tabColor = INK
    wb.properties.creator = ""
    wb.properties.lastModifiedBy = ""
    wb.properties.title = title
    wb.save(out)
    print("saved", out)
