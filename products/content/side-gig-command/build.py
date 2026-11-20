"""Build 「副業コマンドセンター（Excel版）」 for the Coconala content market.

Excel port of the Notion template in E:\\claude\\Notionテンプレ\\20261001_副業コマンドセンター.
Usage: python build.py <out.xlsx>. All sample rows are fictional and marked （サンプル）.
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.chart import BarChart, LineChart, Reference
from _xlsxkit import (FONT, BODY, BORDER, WARN_FILL, OK_FILL, guide_sheet, header, style_rows,
                      dropdown, dropdown_ref, finish)

out = sys.argv[1]
N = 300
today = dt.date.today()
d = lambda n: today + dt.timedelta(days=n)
STATES = ["候補", "応募済み", "受注", "制作中", "納品済み", "完了", "見送り"]
KINDS = ["デザイン", "動画編集", "ライティング", "音楽・音声", "Web制作", "事務・データ", "その他"]
SITES = ["サイトA", "サイトB", "サイトC", "直接"]

wb = Workbook()
g = wb.active
g.title = "はじめに"
guide_sheet(g, [
    ("副業コマンドセンター（Excel版）", "title"),
    ("副業の「応募した案件」「返事待ち・自分の判断待ち」「今週いくら稼げたか」を1ファイルにまとめるテンプレートです。", None),
    ("報酬・手数料・時間を入れると、手取りと時給が自動で出ます。割に合う案件・サイト・種類がひと目でわかります。", None),
    ("", None),
    ("■ シートの構成", "h"),
    ("今日 … 開くたびに見るページ。締切が3日以内の案件、期限切れの「待ち」、今月の手取り・時給が自動で出ます。", None),
    ("案件 … 1行＝1件。状態は「候補 → 応募済み → 受注 → 制作中 → 納品済み → 完了（または見送り）」から選びます。", None),
    ("待ち … 自分の判断・相手の返事・手続きなど、止まっているものを1行ずつ。関連する案件は案件名から選べます。", None),
    ("数字ログ … 週に1回、売上・経費・応募数・受注数・作業時間を入れると、利益・受注率・実質時給とグラフが出ます。", None),
    ("集計 … サイト別・種類別の件数・手取り・時給（受注以降の案件）。どこに時間を使うべきかの判断に使います。", None),
    ("", None),
    ("■ 使い方", "h"),
    ("1. 気になる案件を見つけたら、案件シートに名前・サイト・種類・締切・報酬・手数料率・見込み時間を入れて「候補」に。", None),
    ("2. 「見込み時給」を見て、割に合うものだけ応募 →「応募済み」。受注したら「受注」、作業中は「制作中」に。", None),
    ("3. 作業したら「実作業時間」を足していきます。完了したら「実績時給」が出て、見込みとのずれがわかります。", None),
    ("4. 返事待ちや自分の判断待ちは「待ち」シートへ。期限を入れておくと、過ぎたものが「今日」に赤で出ます。", None),
    ("5. 週に1回（例：日曜の夜10分）、数字ログに1行足します。", None),
    ("", None),
    ("■ 自動計算のしくみ", "h"),
    ("手取り ＝ 報酬 ×（1 − 手数料率）　※手数料率は 20% なら 20 と入力", None),
    ("見込み時給 ＝ 手取り ÷ 見込み時間　／　実績時給 ＝ 手取り ÷ 実作業時間（納品済み・完了の行だけ表示。作業途中の時給は高く出てしまうため）", None),
    ("残り日数 ＝ 締切 − 今日（納品済み・完了・見送りの行は表示しません。3日以内は赤）", None),
    ("待ち日数 ＝ 今日 − 登録日（状態が「済み」の行は表示しません）", None),
    ("利益 ＝ 売上 − 経費　／　受注率 ＝ 受注数 ÷ 応募数　／　実質時給 ＝ 利益 ÷ 作業時間", None),
    ("", None),
    ("■ ご注意", "h"),
    ("・（サンプル）と付いた行は動作確認用の架空データです。確認後に行ごと削除してください。サイト名の「サイトA」なども書き換えて使えます。", None),
    ("・手数料率は各サービスの最新の規約でご確認ください（このファイルには特定サービスの手数料は入っていません）。", None),
    ("・ご購入者さまご本人の利用に限ります。ファイルの再配布・転売はご遠慮ください。", None),
    ("・Microsoft Excel 2016 以降でお使いください。", None),
])

# ---- 案件 ----
ws = wb.create_sheet("案件")
cols = [("案件名", 34), ("サイト", 12), ("種類", 13), ("状態", 10), ("締切", 12), ("報酬（円）", 11),
        ("手数料率（%）", 10), ("見込み時間（h）", 10), ("実作業時間（h）", 10), ("手取り（円）", 11),
        ("見込み時給（円）", 11), ("実績時給（円）", 11), ("残り日数", 8), ("メモ", 30)]
header(ws, cols)
samples = [
    ("（サンプル）カフェのメニュー表デザイン", "サイトA", "デザイン", "完了", d(-14), 15000, 22, 5, 6.5, "修正2回"),
    ("（サンプル）YouTube動画のカット編集（10分）", "サイトB", "動画編集", "制作中", d(2), 8000, 20, 3, 2, "素材は受領済み"),
    ("（サンプル）商品紹介文の作成（3本）", "サイトA", "ライティング", "応募済み", d(5), 6000, 22, 2, None, ""),
    ("（サンプル）料理教室のLP制作", "直接", "Web制作", "受注", d(10), 40000, 0, 12, 1, "ヒアリング中"),
    ("（サンプル）ポッドキャストのノイズ除去", "サイトC", "音楽・音声", "候補", d(7), 3000, 20, 2, None, "時給が低いので検討"),
    ("（サンプル）名刺デザイン", "サイトA", "デザイン", "見送り", d(-3), 5000, 22, 3, None, "条件が合わず"),
    ("（サンプル）アンケート集計の表作成", "サイトB", "事務・データ", "納品済み", d(-1), 12000, 20, 4, 3.5, "検収待ち"),
]
for r in range(2, N + 2):
    s = samples[r - 2] if r - 2 < len(samples) else None
    if s:
        for j, v in enumerate(s[:9], start=1):
            ws.cell(row=r, column=j, value=v)
        ws.cell(row=r, column=14, value=s[9] or None)
    ws.cell(row=r, column=10, value=f'=IF(OR(A{r}="",F{r}=""),"",ROUND(F{r}*(1-N(G{r})/100),0))')
    ws.cell(row=r, column=11, value=f'=IF(OR(J{r}="",N(H{r})=0),"",ROUND(J{r}/H{r},0))')
    ws.cell(row=r, column=12, value=f'=IF(OR(J{r}="",N(I{r})=0,AND(D{r}<>"納品済み",D{r}<>"完了")),"",ROUND(J{r}/I{r},0))')
    ws.cell(row=r, column=13, value=f'=IF(OR(E{r}="",D{r}="納品済み",D{r}="完了",D{r}="見送り"),"",E{r}-TODAY())')
style_rows(ws, 2, N + 1, 14, calc=(10, 11, 12, 13), dates=(5,), money=(6, 10, 11, 12), ints=(13,), wrap=(14,))
dropdown(ws, STATES, f"D2:D{N+1}")
dropdown(ws, KINDS, f"C2:C{N+1}")
dropdown(ws, SITES, f"B2:B{N+1}")
ws.conditional_formatting.add(f"M2:M{N+1}", FormulaRule(formula=['AND(ISNUMBER(M2),M2<=3)'], fill=WARN_FILL,
                              font=Font(name=FONT, bold=True, color="9B1C1C")))
ws.conditional_formatting.add(f"A2:N{N+1}", FormulaRule(formula=['$D2="完了"'], fill=OK_FILL))
ws.conditional_formatting.add(f"A2:N{N+1}", FormulaRule(formula=['$D2="見送り"'], font=Font(name=FONT, color="999999")))
ws.auto_filter.ref = f"A1:N{N+1}"

# ---- 待ち ----
wt = wb.create_sheet("待ち")
header(wt, [("内容", 40), ("関連する案件", 30), ("種類", 14), ("期限", 12), ("状態", 10), ("登録日", 12),
            ("待ち日数", 9), ("期限切れ", 9), ("メモ", 30)])
waits = [
    ("（サンプル）動画のBGMをどれにするか決める", "（サンプル）YouTube動画のカット編集（10分）", "自分の判断", d(1), "未対応", d(-2), ""),
    ("（サンプル）LPの写真を送ってもらう", "（サンプル）料理教室のLP制作", "相手の返事", d(-1), "未対応", d(-5), "催促済み"),
    ("（サンプル）検収の連絡", "（サンプル）アンケート集計の表作成", "相手の返事", d(3), "未対応", d(-1), ""),
    ("（サンプル）開業届の控えをスキャン", "", "手続き", d(-10), "済み", d(-20), ""),
]
for r in range(2, N + 2):
    s = waits[r - 2] if r - 2 < len(waits) else None
    if s:
        for j, v in enumerate(s[:6], start=1):
            wt.cell(row=r, column=j, value=v or None)
        wt.cell(row=r, column=9, value=s[6] or None)
    wt.cell(row=r, column=7, value=f'=IF(OR(A{r}="",F{r}="",E{r}="済み"),"",TODAY()-F{r})')
    wt.cell(row=r, column=8, value=f'=IF(OR(A{r}="",D{r}="",E{r}="済み"),"",IF(D{r}<TODAY(),"期限切れ",""))')
style_rows(wt, 2, N + 1, 9, calc=(7, 8), dates=(4, 6), ints=(7,), wrap=(1, 9))
dropdown(wt, ["自分の判断", "相手の返事", "手続き", "支払い・入金"], f"C2:C{N+1}")
dropdown(wt, ["未対応", "対応中", "済み"], f"E2:E{N+1}")
dropdown_ref(wt, f"=案件!$A$2:$A${N+1}", f"B2:B{N+1}")
wt.conditional_formatting.add(f"H2:H{N+1}", FormulaRule(formula=['H2="期限切れ"'], fill=WARN_FILL,
                              font=Font(name=FONT, bold=True, color="9B1C1C")))
wt.auto_filter.ref = f"A1:I{N+1}"

# ---- 数字ログ ----
wl = wb.create_sheet("数字ログ")
header(wl, [("週の初日", 12), ("売上（円）", 11), ("経費（円）", 11), ("応募数", 8), ("受注数", 8),
            ("作業時間（h）", 10), ("利益（円）", 11), ("受注率", 8), ("実質時給（円）", 11), ("ひとこと", 34)], freeze="A2")
mon = today - dt.timedelta(days=today.weekday())
logs = [(mon - dt.timedelta(weeks=k), sale, cost, app, won, hrs, note) for k, (sale, cost, app, won, hrs, note) in
        zip(range(5, 0, -1), [(8000, 1200, 6, 1, 9, "（サンプル）"), (15000, 0, 4, 2, 11, "（サンプル）"),
                              (0, 2000, 8, 0, 6, "（サンプル）応募ばかり"), (23400, 500, 5, 2, 14, "（サンプル）"),
                              (12000, 0, 3, 1, 7, "（サンプル）単価を上げた")])]
for r in range(2, 202):
    s = logs[r - 2] if r - 2 < len(logs) else None
    if s:
        for j, v in enumerate(s[:6], start=1):
            wl.cell(row=r, column=j, value=v)
        wl.cell(row=r, column=10, value=s[6])
    wl.cell(row=r, column=7, value=f'=IF(A{r}="","",N(B{r})-N(C{r}))')
    wl.cell(row=r, column=8, value=f'=IF(OR(A{r}="",N(D{r})=0),"",E{r}/D{r})')
    wl.cell(row=r, column=9, value=f'=IF(OR(A{r}="",N(F{r})=0),"",ROUND(G{r}/F{r},0))')
style_rows(wl, 2, 201, 10, calc=(7, 8, 9), dates=(1,), money=(2, 3, 7, 9), pct=(8,), wrap=(10,))
lc = LineChart()
lc.title = "週ごとの利益と実質時給"
lc.add_data(Reference(wl, min_col=7, min_row=1, max_row=1 + 26), titles_from_data=True)
lc.set_categories(Reference(wl, min_col=1, min_row=2, max_row=1 + 26))
lc.x_axis.number_format = "mm/dd"
lc.height, lc.width = 8, 18
wl.add_chart(lc, "L2")

# ---- 集計 ----
wa = wb.create_sheet("集計")
A = lambda col: f"案件!${col}$2:${col}${N+1}"
DONE = ["受注", "制作中", "納品済み", "完了"]
FIN = ["納品済み", "完了"]


def block(top, title, labels, keycol):
    wa.cell(row=top, column=1, value=title).font = Font(name=FONT, bold=True, size=12, color="2F3A4A")
    hdr = [title.split("別")[0], "受注以降の件数", "納品・完了の手取り（円）", "その作業時間（h）", "実績時給（円）", "応募以降", "受注率"]
    for j, h in enumerate(hdr, start=1):
        c = wa.cell(row=top + 1, column=j, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F3A4A")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, lab in enumerate(labels):
        r = top + 2 + i
        wa.cell(row=r, column=1, value=lab)
        cnt = "+".join(f'COUNTIFS({A(keycol)},A{r},{A("D")},"{s}")' for s in DONE)
        net = "+".join(f'SUMIFS({A("J")},{A(keycol)},A{r},{A("D")},"{s}")' for s in FIN)
        hrs = "+".join(f'SUMIFS({A("I")},{A(keycol)},A{r},{A("D")},"{s}")' for s in FIN)
        wa.cell(row=r, column=2, value=f"={cnt}")
        wa.cell(row=r, column=3, value=f"={net}")
        wa.cell(row=r, column=4, value=f"={hrs}")
        wa.cell(row=r, column=5, value=f'=IF(D{r}=0,"",ROUND(C{r}/D{r},0))')
        wa.cell(row=r, column=6, value=f'=B{r}+COUNTIFS({A(keycol)},A{r},{A("D")},"応募済み")+COUNTIFS({A(keycol)},A{r},{A("D")},"見送り")')
        wa.cell(row=r, column=7, value=f'=IF(F{r}=0,"",B{r}/F{r})')
    style_rows(wa, top + 2, top + 1 + len(labels), 7, calc=(2, 3, 4, 5, 6, 7), money=(3, 5), pct=(7,))
    return top + 2 + len(labels)


for j, w in enumerate([16, 12, 12, 12, 12, 10, 9], start=1):
    wa.column_dimensions[chr(64 + j)].width = w
end1 = block(1, "サイト別", SITES, "B")
end2 = block(end1 + 2, "種類別", KINDS, "C")
wa.cell(row=end2 + 1, column=1, value="※「見送り」は応募したが受けなかった案件として受注率の分母に入ります。").font = Font(name=FONT, color="777777")
bc = BarChart()
bc.type = "bar"
bc.title = "種類別の実績時給"
bc.legend = None
bc.add_data(Reference(wa, min_col=5, min_row=end1 + 3, max_row=end2 - 1), titles_from_data=True)
bc.set_categories(Reference(wa, min_col=1, min_row=end1 + 4, max_row=end2 - 1))
bc.height, bc.width = 8, 14
wa.add_chart(bc, "I2")

# ---- 今日 ----
td = wb.create_sheet("今日", 1)
td.sheet_view.showGridLines = False
td.column_dimensions["A"].width = 38
for c in "BCD":
    td.column_dimensions[c].width = 16
td["A1"] = "今日見るもの"
td["A1"].font = Font(name=FONT, bold=True, size=16, color="2F3A4A")
td["A2"] = '=TEXT(TODAY(),"yyyy/mm/dd（aaa）")'
td["A2"].font = Font(name=FONT, color="777777")
kpis = [
    ("締切まで3日以内の案件", f'=COUNTIFS({A("M")},">=0",{A("M")},"<=3")'),
    ("締切を過ぎた案件（完了・見送り以外）", f'=COUNTIFS({A("M")},"<0")'),
    ("期限切れの「待ち」", f'=COUNTIF(待ち!$H$2:$H${N+1},"期限切れ")'),
    ("未対応・対応中の「待ち」", f'=COUNTIF(待ち!$E$2:$E${N+1},"未対応")+COUNTIF(待ち!$E$2:$E${N+1},"対応中")'),
    ("制作中・受注の案件", f'=COUNTIF({A("D")},"制作中")+COUNTIF({A("D")},"受注")'),
    ("直近4週の利益（円）", '=SUMIFS(数字ログ!$G$2:$G$201,数字ログ!$A$2:$A$201,">="&(TODAY()-28))'),
    ("直近4週の実質時給（円）", '=IFERROR(ROUND(SUMIFS(数字ログ!$G$2:$G$201,数字ログ!$A$2:$A$201,">="&(TODAY()-28))/SUMIFS(数字ログ!$F$2:$F$201,数字ログ!$A$2:$A$201,">="&(TODAY()-28)),0),"")'),
]
for i, (lab, f) in enumerate(kpis):
    r = 4 + i
    a = td.cell(row=r, column=1, value=lab)
    b = td.cell(row=r, column=2, value=f)
    for c in (a, b):
        c.font = Font(name=FONT, bold=(c is b), size=12)
        c.border = BORDER
    b.fill = PatternFill("solid", fgColor="EEF2F6")
    b.number_format = "#,##0"
td.conditional_formatting.add("B4:B7", FormulaRule(formula=['N(B4)>0'], fill=WARN_FILL, font=Font(name=FONT, bold=True, color="9B1C1C")))
td["A12"] = "週1回の見直し（10分）"
td["A12"].font = Font(name=FONT, bold=True, size=12, color="2F3A4A")
checks = ["数字ログに今週の1行を足した", "「待ち」の期限切れを片づけた（催促・判断・あきらめる）",
          "集計シートで、時給が一番低いサイト・種類を確認した", "来週応募する案件を「候補」に3件以上入れた",
          "見込み時給と実績時給が大きくずれた案件の理由をメモした"]
for i, t in enumerate(checks):
    c = td.cell(row=13 + i, column=1, value="□ " + t)
    c.font = BODY

finish(wb, "副業コマンドセンター", out)
