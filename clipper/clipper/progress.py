"""Live progress page for long runs: <video folder>/progress.html (auto-refresh) + progress.json.

`build` creates one Progress; render and qc report into it through `current()`, and the main
ffmpeg encode writes `-progress` so the page shows a percentage inside each clip.
"""
import html
import json
import os
import re
import threading
import time

_CUR = None


def current():
    return _CUR


def _fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


class Progress:
    def __init__(self, wd, title, steps):
        """steps: [(key, label, estimated_seconds)]"""
        global _CUR
        self.wd, self.title, self.t0 = wd, title, time.time()
        self.steps = [{"key": k, "label": l, "est": float(e), "state": "wait", "frac": 0.0,
                       "t0": None, "t1": None, "note": ""} for k, l, e in steps]
        self.result = None
        self._lock = threading.Lock()
        self._stop = None
        _CUR = self
        self.write()

    def _s(self, key):
        return next((s for s in self.steps if s["key"] == key), None)

    def start(self, key, note=""):
        s = self._s(key)
        if s:
            s.update(state="run", t0=time.time(), note=note, frac=0.0)
            print(f"  ▶ {s['label']}", flush=True)
            self.write()

    def set_frac(self, key, frac):
        s = self._s(key)
        if s and s["state"] == "run":
            s["frac"] = max(s["frac"], min(0.99, frac))
            self.write()

    def done(self, key, note="", ok=True):
        self.stop_watch()
        s = self._s(key)
        if s:
            s.update(state="ok" if ok else "ng", t1=time.time(), note=note, frac=1.0)
            print(f"  {'✔' if ok else '✖'} {s['label']} {note}", flush=True)
            self.write()

    def watch_ffmpeg(self, key, path, total_sec):
        """Follow an ffmpeg `-progress` file and turn out_time into this step's fraction."""
        self.stop_watch()
        stop = threading.Event()
        self._stop = stop

        def loop():
            while not stop.wait(1.0):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        us = re.findall(r"out_time_us=(\d+)", fh.read())
                    if us and total_sec > 0:
                        self.set_frac(key, int(us[-1]) / 1e6 / total_sec)
                except OSError:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop_watch(self):
        if self._stop:
            self._stop.set()
            self._stop = None

    def finish(self, ok, note=""):
        global _CUR
        self.stop_watch()
        for s in self.steps:  # steps skipped after a failure
            if s["state"] in ("wait", "run"):
                s["state"] = "skip" if not ok else s["state"]
        self.result = ("ok" if ok else "ng", note)
        self.write()
        _CUR = None

    # -- output -----------------------------------------------------------------------------
    def _overall(self):
        tot = sum(s["est"] for s in self.steps) or 1.0
        got = sum(s["est"] * (1.0 if s["state"] in ("ok", "ng") else s["frac"]) for s in self.steps)
        frac = got / tot
        el = time.time() - self.t0
        eta = el / frac * (1 - frac) if frac > 0.03 and el > 8 and not self.result else None
        return frac, el, eta

    def write(self):
        with self._lock:
            frac, el, eta = self._overall()
            data = {"title": self.title, "updated": time.strftime("%H:%M:%S"), "overall": round(frac, 3),
                    "elapsed_sec": round(el), "eta_sec": round(eta) if eta else None, "result": self.result,
                    "steps": [{k: s[k] for k in ("key", "label", "state", "frac", "note")} for s in self.steps]}
            self._atomic("progress.json", json.dumps(data, ensure_ascii=False, indent=1))
            self._atomic("progress.html", self._html(data, el, eta))

    def _atomic(self, name, text):
        path = os.path.join(self.wd, name)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except OSError:
            pass  # the page is a convenience; never fail the run over it

    def _html(self, d, el, eta):
        icon = {"wait": "⬜", "run": "⏳", "ok": "✅", "ng": "❌", "skip": "⏭"}
        word = {"wait": "待機", "run": "実行中", "ok": "完了", "ng": "失敗", "skip": "中止"}
        rows = []
        for s in self.steps:
            pct = int(round((1.0 if s["state"] in ("ok", "ng") else s["frac"]) * 100))
            took = ""
            if s["t0"]:
                took = _fmt((s["t1"] or time.time()) - s["t0"])
            rows.append(
                f"<tr class='{s['state']}'><td>{icon[s['state']]}</td><td>{html.escape(s['label'])}</td>"
                f"<td><div class='bar'><i style='width:{pct}%'></i></div></td><td>{pct}%</td>"
                f"<td>{word[s['state']]}</td><td>{took}</td><td>{html.escape(s['note'])}</td></tr>")
        from .site import CSS
        if d["result"]:
            ok = d["result"][0] == "ok"
            head = (f"<span class='tag {'ok' if ok else 'ng'}'>{'完了' if ok else '停止'}</span> "
                    f"{html.escape(d['result'][1])}")
            refresh = ""
        else:
            head = (f"<span class='tag warn'>実行中</span> 全体 <b>{int(d['overall'] * 100)}%</b>"
                    f"　残り目安 <b>{_fmt(eta) if eta else '計算中'}</b>")
            refresh = "<meta http-equiv='refresh' content='3'>"
        extra = """.bar{background:#262b36;height:10px;border-radius:5px;overflow:hidden;width:100%;min-width:60px}
.bar.big{height:14px;margin:10px 0 18px}
.bar i{display:block;height:100%;background:var(--accent)}tr.ok .bar i{background:var(--ok)}tr.ng .bar i{background:var(--ng)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
td{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}td:nth-child(3){width:40%}
td:last-child{white-space:normal;color:var(--sub);font-size:12px}tr.run td{background:#1d2a38}tr.wait td{color:var(--sub)}
.top{font-size:16px}@media(max-width:600px){td:nth-child(6),td:nth-child(7){display:none}td{padding:7px 6px}}"""
        return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">{refresh}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>進捗 {html.escape(self.title)}</title>
<style>{CSS}{extra}</style></head><body>
<header><a class="crumb" href="../index.html">← 一覧</a><a class="crumb" href="index.html">動画ページ</a>
<h1>{html.escape(self.title)}</h1><span class="crumb">最終更新 {d['updated']}・経過 {_fmt(el)}・3秒ごとに自動更新</span></header>
<main><div class="top">{head}</div><div class="bar big" style="min-width:0"><i style="width:{int(d['overall'] * 100)}%"></i></div>
<table>{''.join(rows)}</table></main></body></html>"""
