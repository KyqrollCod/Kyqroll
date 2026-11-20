"""Screen-event detection: a banner shown at t=30..32 must be found from its template."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FONT = os.path.join(os.path.dirname(HERE), "assets", "fonts", "DelaGothicOne-Regular.ttf")


def test_event_template():
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("SKIP: opencv not installed")
        return
    from clipper.analyze import event_series
    d = tempfile.mkdtemp(prefix="clipper_ev_")
    src = os.path.join(d, "src.mp4")
    font = FONT.replace("\\", "/").replace(":", "\\:")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=1280x720:r=30:d=60", "-vf",
                    f"drawtext=fontfile='{font}':text='ロン':fontsize=200:fontcolor=red:borderw=12:"
                    f"x=(w-tw)/2:y=(h-th)/2:enable='between(t,30,32)'",
                    "-c:v", "libx264", "-preset", "ultrafast", src], check=True)
    tdir = os.path.join(d, "templates")
    os.makedirs(tdir)
    frame = os.path.join(d, "f.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "31", "-i", src, "-frames:v", "1",
                    "-vf", "scale=640:360,crop=200:110:220:125", os.path.join(tdir, "ron.png")], check=True)
    ev, hits = event_series(src, 60, 60, 1.0, tdir)
    times = sorted({int(h["t"]) for h in hits if isinstance(h, dict)})
    assert times and all(29 <= t <= 33 for t in times), times
    assert ev[30:33].max() > 0 and ev[:28].max() == 0
    print("OK events at", times)


if __name__ == "__main__":
    test_event_template()
