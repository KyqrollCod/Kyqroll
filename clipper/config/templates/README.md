# 画面イベントのテンプレート（任意）

ゲーム画面に出る決まった演出（例: 雀魂の「ロン」「ツモ」、FPSの「VICTORY」）を
640x360 に縮小したフレームから切り抜いて PNG で置くと、analyze が見どころの根拠に加えます。
`python -m clipper calibrate WORK --at 秒` でフレームを書き出して切り抜くと作れます。
opencv-python-headless が必要です。
