"""Build 「教室の体験申込・生徒管理表（Excel）」 for the Coconala content market.

Usage: python build.py <out.xlsx>
All sample rows are fictional and marked （サンプル）.
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.chart import BarChart, LineChart, Reference
from _xlsxkit import (FONT, BODY, BORDER, CALC_FILL, WARN_FILL, OK_FILL, guide_sheet, header,
                      style_rows, dropdown, finish)

out = sys.argv[1]
N = 300  # input rows
TS = f"体験申込!$A$2:$A${N+1}"
today = dt.date.today()
month0 = today.replace(day=1)

STATES = ["受付", "日程調整", "体験予定", "体験済み", "入会", "見送り", "連絡なし"]
ROUTES = ["ホームページ・LP", "LINE", "Instagram", "Googleマップ", "紹介", "チラシ・看板", "その他"]
REASONS = ["料金", "日時が合わない", "場所・通い方", "内容が合わない", "他の教室に決めた", "理由不明", "その他"]
COURSES = ["（サンプル）子どもコース", "（サンプル）大人コース", "（サンプル）オンライン"]

wb = Workbook()

# ---------------- はじめに ----------------
g = wb.active
g.title = "はじめに"
guide_sheet(g, [
    ("教室の体験申込・生徒管理表（Excel版）", "title"),
    ("体験レッスン・無料相談の申込から、入会・退会までを1ファイルで管理するテンプレートです。", None),
    ("「どこから来た人が入会しているか」「体験のあと連絡を忘れていないか」「今月の在籍数と月謝はいくらか」が自動で出ます。", None),
    ("", None),
    ("■ シートの構成", "h"),
    ("体験申込 … 1行＝1件の申込。白いセルに入力すると、灰色のセル（フォロー・申込から体験までの日数）が自動で出ます。", None),
    ("生徒 … 1行＝1人。月謝・入会日・退会日を入れると、在籍／退会と在籍月数が自動で出ます。", None),
    ("月次 … 12か月分の申込数・体験数・入会数・入会率・退会数・月末在籍数・月謝（見込み）。「開始月」を変えるだけで切り替わります。", None),
    ("経路別 … ホームページ・LINE・Instagram・紹介など、申込の経路ごとの体験数・入会数・入会率とグラフ。", None),
    ("見送り理由 … 体験のあと入会しなかった理由の件数と割合、グラフ。料金・日時など、直すべき点が見えます。", None),
    ("連絡文例 … 体験の確認・お礼・入会のご案内・見送りの方への連絡など8つ。コピーして書き換えて使えます。", None),
    ("", None),
    ("■ 使い方（毎日1分）", "h"),
    ("1. 申込が来たら、体験申込シートに受付日・お名前・経路を入れ、状態を「受付」にします。", None),
    ("2. 日程が決まったら体験日を入れて「体験予定」、体験が終わったら「体験済み」に。2日たっても「体験済み」のままだと「要フォロー」と出ます。", None),
    ("3. 入会したら状態を「入会」にして、生徒シートにも1行足します。入会しなかったら「見送り」にして、見送り理由を選びます。", None),
    ("4. 「次の連絡日」を入れておくと、その日になったら「今日連絡」と表示されます。", None),
    ("", None),
    ("■ 自動計算のしくみ", "h"),
    ("要フォロー ＝ 状態が「体験済み」で、体験日から2日以上たっている行／次の連絡日が今日以前で、まだ決まっていない行", None),
    ("入会率（月次）＝ その月に体験した人のうち、状態が「入会」の人 ÷ その月の体験数", None),
    ("月末在籍数 ＝ 月末までに入会した人 − 月末までに退会した人", None),
    ("月謝（見込み）＝ その月に在籍していた人の月謝の合計（入会日がその月の末日以前で、退会日が空か、その月の初日以降）", None),
    ("入会率（経路別）＝ その経路の「入会」の数 ÷ その経路で体験した数（体験日が入っている行）", None),
    ("", None),
    ("■ 個人情報について", "h"),
    ("・お名前はイニシャルや「Aさん（小3）」のような書き方でも動きます。電話番号・住所はこのファイルに入れないことをおすすめします。", None),
    ("・ファイルをパソコンやクラウドに保存するときは、教室の方以外が開けない場所に置いてください。", None),
    ("", None),
    ("■ ご注意", "h"),
    ("・（サンプル）と付いた行は動作確認用の架空データです。確認後に行ごと削除してください（コース名のサンプルも書き換えてください）。", None),
    ("・ご購入者さまご本人（ご自身の教室）での利用に限ります。ファイルの再配布・転売はご遠慮ください。", None),
    ("・Microsoft Excel 2016 以降でお使いください（Excel以外の表計算ソフトでの動作は保証していません）。", None),
])

# ---------------- 体験申込 ----------------
ws = wb.create_sheet("体験申込")
cols = [("受付日", 12), ("お名前（イニシャル可）", 20), ("コース", 18), ("経路", 16), ("状態", 11),
        ("体験日", 12), ("入会日", 12), ("見送り理由", 16), ("次の連絡日", 12), ("メモ", 34),
        ("フォロー", 11), ("申込→体験（日）", 11)]
header(ws, cols)
d = lambda n: today + dt.timedelta(days=n)
samples = [
    (d(-62), "（サンプル）Aさん（小2）", COURSES[0], "ホームページ・LP", "入会", d(-55), d(-50), None, None, "兄弟で検討"),
    (d(-58), "（サンプル）Bさん", COURSES[1], "Instagram", "見送り", d(-52), None, "日時が合わない", None, "平日夜を希望"),
    (d(-40), "（サンプル）Cさん（年長）", COURSES[0], "紹介", "入会", d(-33), d(-30), None, None, "Aさんのご紹介"),
    (d(-35), "（サンプル）Dさん", COURSES[2], "ホームページ・LP", "見送り", d(-29), None, "料金", None, ""),
    (d(-30), "（サンプル）Eさん（小5）", COURSES[0], "チラシ・看板", "入会", d(-24), d(-21), None, None, ""),
    (d(-21), "（サンプル）Fさん", COURSES[1], "Googleマップ", "見送り", d(-15), None, "他の教室に決めた", None, ""),
    (d(-12), "（サンプル）Gさん（小1）", COURSES[0], "LINE", "体験済み", d(-4), None, None, d(-1), "入会案内を送る"),
    (d(-6), "（サンプル）Hさん", COURSES[2], "ホームページ・LP", "体験予定", d(3), None, None, None, "オンラインで実施"),
    (d(-2), "（サンプル）Iさん（小4）", COURSES[0], "Instagram", "日程調整", None, None, None, d(0), "土曜午前を希望"),
    (d(-1), "（サンプル）Jさん", COURSES[1], "ホームページ・LP", "受付", None, None, None, d(1), ""),
]
for r in range(2, N + 2):
    s = samples[r - 2] if r - 2 < len(samples) else None
    if s:
        for j, v in enumerate(s, start=1):
            ws.cell(row=r, column=j, value=v)
    ws.cell(row=r, column=11, value=(
        f'=IF(B{r}="","",IF(AND(E{r}="体験済み",F{r}<>"",TODAY()-F{r}>=2),"要フォロー",'
        f'IF(AND(I{r}<>"",I{r}<=TODAY(),OR(E{r}="受付",E{r}="日程調整",E{r}="体験予定",E{r}="体験済み")),"今日連絡","")))'))
    ws.cell(row=r, column=12, value=f'=IF(OR(A{r}="",F{r}=""),"",F{r}-A{r})')
style_rows(ws, 2, N + 1, 12, calc=(11, 12), dates=(1, 6, 7, 9), ints=(12,), wrap=(10,))
dropdown(ws, STATES, f"E2:E{N+1}")
dropdown(ws, ROUTES, f"D2:D{N+1}")
dropdown(ws, REASONS, f"H2:H{N+1}")
ws.conditional_formatting.add(f"K2:K{N+1}", FormulaRule(formula=['K2<>""'], fill=WARN_FILL,
                              font=Font(name=FONT, bold=True, color="9B1C1C")))
ws.conditional_formatting.add(f"A2:J{N+1}", FormulaRule(formula=['$E2="入会"'], fill=OK_FILL))
ws.auto_filter.ref = f"A1:L{N+1}"

# ---------------- 生徒 ----------------
st = wb.create_sheet("生徒")
header(st, [("お名前（イニシャル可）", 20), ("コース", 18), ("月謝（円）", 11), ("入会日", 12), ("退会日", 12),
            ("退会理由", 18), ("経路", 16), ("在籍", 8), ("在籍月数", 9), ("メモ", 30)])
students = [
    ("（サンプル）Kさん（小6）", COURSES[0], 8800, d(-420), None, None, "紹介", ""),
    ("（サンプル）Lさん", COURSES[1], 9900, d(-300), d(-20), "引っ越し", "ホームページ・LP", ""),
    ("（サンプル）Mさん（中1）", COURSES[0], 8800, d(-200), None, None, "チラシ・看板", ""),
    ("（サンプル）Nさん", COURSES[2], 7700, d(-120), None, None, "Instagram", ""),
    ("（サンプル）Aさん（小2）", COURSES[0], 8800, d(-50), None, None, "ホームページ・LP", ""),
    ("（サンプル）Cさん（年長）", COURSES[0], 8800, d(-30), None, None, "紹介", ""),
    ("（サンプル）Eさん（小5）", COURSES[0], 8800, d(-21), None, None, "チラシ・看板", ""),
]
for r in range(2, N + 2):
    s = students[r - 2] if r - 2 < len(students) else None
    if s:
        for j, v in enumerate(s[:7], start=1):
            st.cell(row=r, column=j, value=v)
        st.cell(row=r, column=10, value=s[7] or None)
    st.cell(row=r, column=8, value=f'=IF(A{r}="","",IF(E{r}="","在籍","退会"))')
    st.cell(row=r, column=9, value=f'=IF(OR(A{r}="",D{r}=""),"",DATEDIF(D{r},IF(E{r}="",TODAY(),E{r}),"m"))')
style_rows(st, 2, N + 1, 10, calc=(8, 9), dates=(4, 5), money=(3,), ints=(9,), wrap=(10,))
dropdown(st, ROUTES, f"G2:G{N+1}")
dropdown(st, ["引っ越し", "時間が合わなくなった", "料金", "目標を達成した", "学校・仕事が忙しい", "内容が合わない", "その他"], f"F2:F{N+1}")
st.conditional_formatting.add(f"A2:J{N+1}", FormulaRule(formula=['$H2="退会"'], fill=PatternFill("solid", fgColor="EEEEEE"),
                              font=Font(name=FONT, color="777777")))
st.auto_filter.ref = f"A1:J{N+1}"

# ---------------- 月次 ----------------
mo = wb.create_sheet("月次")
mo["A1"] = "開始月（この月から12か月分を表示）"
mo["A1"].font = Font(name=FONT, bold=True)
mo["B1"] = (month0.replace(day=1) - dt.timedelta(days=60)).replace(day=1)
mo["B1"].number_format = "yyyy/mm"
mo["B1"].fill = PatternFill("solid", fgColor="FFF4CC")
mo["B1"].border = BORDER
mo["C1"] = "← 月の初日を入れてください（例：2027/4/1）"
mo["C1"].font = Font(name=FONT, color="777777")
heads = [("月", 10), ("体験申込", 10), ("体験した", 10), ("入会（体験から）", 12), ("入会率", 9),
         ("入会（生徒）", 11), ("退会", 8), ("月末在籍", 10), ("月謝（見込み・円）", 15)]
for j, (h, w) in enumerate(heads, start=1):
    c = mo.cell(row=3, column=j, value=h)
    c.font = Font(name=FONT, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="2F3A4A")
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    mo.column_dimensions[c.column_letter].width = w
mo.column_dimensions["A"].width = 34
mo.row_dimensions[3].height = 32
T = lambda col: f"体験申込!${col}$2:${col}${N+1}"
S = lambda col: f"生徒!${col}$2:${col}${N+1}"
for i in range(12):
    r = 4 + i
    mo.cell(row=r, column=1, value=f"=EDATE($B$1,{i})")
    nx = f"EDATE(A{r},1)"
    mo.cell(row=r, column=2, value=f'=COUNTIFS({T("A")},">="&A{r},{T("A")},"<"&{nx})')
    mo.cell(row=r, column=3, value=f'=COUNTIFS({T("F")},">="&A{r},{T("F")},"<"&{nx},{T("F")},"<="&TODAY())')
    mo.cell(row=r, column=4, value=f'=COUNTIFS({T("E")},"入会",{T("F")},">="&A{r},{T("F")},"<"&{nx})')
    mo.cell(row=r, column=5, value=f'=IF(C{r}=0,"",D{r}/C{r})')
    mo.cell(row=r, column=6, value=f'=COUNTIFS({S("D")},">="&A{r},{S("D")},"<"&{nx})')
    mo.cell(row=r, column=7, value=f'=COUNTIFS({S("E")},">="&A{r},{S("E")},"<"&{nx})')
    mo.cell(row=r, column=8, value=f'=COUNTIFS({S("D")},"<"&{nx})-COUNTIFS({S("E")},"<"&{nx})')
    mo.cell(row=r, column=9, value=(f'=SUMIFS({S("C")},{S("D")},"<"&{nx},{S("E")},"=")'
                                    f'+SUMIFS({S("C")},{S("D")},"<"&{nx},{S("E")},">="&A{r})'))
style_rows(mo, 4, 15, 9, calc=tuple(range(1, 10)), money=(9,), pct=(5,))
for r in range(4, 16):
    mo.cell(row=r, column=1).number_format = "yyyy/mm"
lc = LineChart()
lc.title = "月末在籍と入会・退会"
lc.add_data(Reference(mo, min_col=6, max_col=8, min_row=3, max_row=15), titles_from_data=True)
lc.set_categories(Reference(mo, min_col=1, min_row=4, max_row=15))
lc.x_axis.number_format = "yyyy/mm"
lc.height, lc.width = 8, 18
mo.add_chart(lc, "K3")

# ---------------- 経路別 ----------------
rt = wb.create_sheet("経路別")
header(rt, [("経路", 18), ("申込", 9), ("体験した", 10), ("入会", 9), ("入会率（体験→入会）", 14), ("申込→入会", 11)], freeze=None)
for i, x in enumerate(ROUTES, start=2):
    rt.cell(row=i, column=1, value=x)
    rt.cell(row=i, column=2, value=f'=COUNTIFS({T("D")},A{i},{T("B")},"<>")')
    rt.cell(row=i, column=3, value=f'=COUNTIFS({T("D")},A{i},{T("F")},"<="&TODAY())')
    rt.cell(row=i, column=4, value=f'=COUNTIFS({T("D")},A{i},{T("E")},"入会")')
    rt.cell(row=i, column=5, value=f'=IF(C{i}=0,"",D{i}/C{i})')
    rt.cell(row=i, column=6, value=f'=IF(B{i}=0,"",D{i}/B{i})')
last = len(ROUTES) + 1
t = last + 1
rt.cell(row=t, column=1, value="合計")
for j, L in zip((2, 3, 4), "BCD"):
    rt.cell(row=t, column=j, value=f"=SUM({L}2:{L}{last})")
rt.cell(row=t, column=5, value=f'=IF(C{t}=0,"",D{t}/C{t})')
rt.cell(row=t, column=6, value=f'=IF(B{t}=0,"",D{t}/B{t})')
style_rows(rt, 2, t, 6, calc=(2, 3, 4, 5, 6), pct=(5, 6))
for j in range(1, 7):
    rt.cell(row=t, column=j).font = Font(name=FONT, bold=True)
bc = BarChart()
bc.type = "bar"
bc.title = "経路別の入会数と体験数"
bc.add_data(Reference(rt, min_col=3, max_col=4, min_row=1, max_row=last), titles_from_data=True)
bc.set_categories(Reference(rt, min_col=1, min_row=2, max_row=last))
bc.height, bc.width = 8, 16
rt.add_chart(bc, "H2")

# ---------------- 見送り理由 ----------------
rs = wb.create_sheet("見送り理由")
header(rs, [("見送り理由", 20), ("件数", 9), ("割合", 9)], freeze=None)
for i, x in enumerate(REASONS, start=2):
    rs.cell(row=i, column=1, value=x)
    rs.cell(row=i, column=2, value=f'=COUNTIFS({T("E")},"見送り",{T("H")},A{i})')
    rs.cell(row=i, column=3, value=f'=IF(SUM($B$2:$B${len(REASONS)+1})=0,"",B{i}/SUM($B$2:$B${len(REASONS)+1}))')
style_rows(rs, 2, len(REASONS) + 1, 3, calc=(2, 3), pct=(3,))
rs.cell(row=len(REASONS) + 3, column=1,
        value="見送りの状態で理由が空の行は数えません。理由を聞けなかったときは「理由不明」を選んでください。").font = Font(name=FONT, color="777777")
pc = BarChart()
pc.type = "bar"
pc.title = "見送り理由"
pc.legend = None
pc.add_data(Reference(rs, min_col=2, min_row=1, max_row=len(REASONS) + 1), titles_from_data=True)
pc.set_categories(Reference(rs, min_col=1, min_row=2, max_row=len(REASONS) + 1))
pc.height, pc.width = 8, 14
rs.add_chart(pc, "E2")

# ---------------- 連絡文例 ----------------
tm = wb.create_sheet("連絡文例")
header(tm, [("場面", 18), ("いつ送るか", 18), ("文例（〔 〕を書き換えて使う）", 90)], freeze="A2")
msgs = [
    ("体験の予約確認", "申込を受けたらすぐ",
     "〔お名前〕様\n体験レッスンのお申込みありがとうございます。〔教室名〕の〔講師名〕です。\n日時：〔月/日（曜）時:分〜〕\n場所：〔住所 または オンラインのURLは前日にお送りします〕\n持ち物：〔なし／筆記用具など〕\nご都合が悪くなった場合は、このメッセージにご返信ください。当日お会いできるのを楽しみにしています。"),
    ("前日のリマインド", "体験の前日",
     "〔お名前〕様\n明日〔時:分〕からの体験レッスンのご確認です。〔場所・行き方の目印〕でお待ちしています。\n変更やご質問があれば、お気軽にご返信ください。"),
    ("体験のお礼", "体験の当日〜翌日",
     "〔お名前〕様\n本日は体験レッスンにお越しいただき、ありがとうございました。〔今日できたこと・印象に残ったこと〕がとても素敵でした。\n入会をご検討の場合は、〔入会方法〕からお手続きいただけます。ご不明な点があれば、何でもお聞きください。"),
    ("入会のご案内", "体験の2〜3日後（お返事がまだのとき）",
     "〔お名前〕様\n先日はありがとうございました。〔教室名〕の〔講師名〕です。\n〔曜日・時間〕の枠は現在〔空き状況（事実のみ）〕です。料金は月〔金額〕円（税込）、入会金〔金額〕円です。\nご検討中のことがあれば、日程や料金のご相談だけでも大丈夫です。"),
    ("見送りの方へ", "「今回は見送ります」と返事が来たとき",
     "〔お名前〕様\nご連絡ありがとうございます。体験にお越しいただけたこと、とても嬉しかったです。\nもしよろしければ、今後の参考に〔日時・料金・内容〕で合わなかった点を一言だけ教えていただけると助かります（お返事は不要です）。\nまたいつでもお気軽にご連絡ください。"),
    ("日程の調整", "希望日が埋まっているとき",
     "〔お名前〕様\nお申込みありがとうございます。ご希望の〔日時〕は満席のため、次の日程はいかがでしょうか。\n・〔候補1〕\n・〔候補2〕\n・〔候補3〕\nご都合のよい日をお知らせください。"),
    ("当日お見えにならなかったとき", "体験日の当日〜翌日",
     "〔お名前〕様\n本日〔時:分〕の体験レッスンでお待ちしておりましたが、お会いできませんでした。何かございましたでしょうか。\nご都合がつけば、別の日程もご用意できます。ご返信をお待ちしています。"),
    ("退会のときのお礼", "退会の連絡を受けたとき",
     "〔お名前〕様\nこれまで〔期間〕、通っていただきありがとうございました。〔印象に残っていること〕を一緒に過ごせて嬉しかったです。\n最後のレッスンは〔日付〕です。またいつでも遊びに来てください。"),
]
for r, row in enumerate(msgs, start=2):
    for j, v in enumerate(row, start=1):
        c = tm.cell(row=r, column=j, value=v)
        c.font = BODY
        c.border = BORDER
        c.alignment = Alignment(wrap_text=True, vertical="top")
    tm.row_dimensions[r].height = 120
tm.cell(row=len(msgs) + 3, column=1,
        value="空き状況・料金・実績は事実だけを書いてください。「残りわずか」などは本当にそうなっているときだけ使います。").font = Font(name=FONT, color="777777")

finish(wb, "教室の体験申込・生徒管理表", out)
