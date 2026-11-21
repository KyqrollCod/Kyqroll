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
        eta = el / frac * (1 - frac) if frac > 0.03 and not self.result else None
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
        if d["result"]:
            head = ("✅ 完了" if d["result"][0] == "ok" else "❌ 停止") + f"　{html.escape(d['result'][1])}"
            refresh = ""
        else:
            head = f"実行中　全体 {int(d['overall'] * 100)}%　残り目安 {_fmt(eta) if eta else '計算中'}"
            refresh = "<meta http-equiv='refresh' content='3'>"
        return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">{refresh}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>進捗 {html.escape(self.title)}</title>
<style>body{{font-family:'Yu Gothic UI',Meiryo,sans-serif;margin:16px;background:#111;color:#eee}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#aaa;font-size:13px;margin-bottom:12px}}
.top{{font-size:20px;margin:8px 0 12px}} .bar{{background:#333;height:10px;border-radius:5px;overflow:hidden;width:180px}}
.bar i{{display:block;height:100%;background:#3ea8ff}} tr.ok .bar i{{background:#6edb5a}} tr.ng .bar i{{background:#ff5050}}
table{{border-collapse:collapse;font-size:14px}} td{{padding:4px 8px;border-bottom:1px solid #2a2a2a}}
tr.run td{{background:#1d2a38}} tr.wait td{{color:#888}}</style></head><body>
<h1>{html.escape(self.title)}</h1><div class="sub">最終更新 {d['updated']}　経過 {_fmt(el)}（3秒ごとに自動更新）</div>
<div class="top">{head}</div><div class="bar" style="width:100%;height:14px"><i style="width:{int(d['overall'] * 100)}%"></i></div><br>
<table>{''.join(rows)}</table></body></html>"""
