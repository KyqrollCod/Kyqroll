# clipper — 配信アーカイブ → 完成したショート / 横動画

配信のURLから、見どころ探し・カット・無音詰め・テロップ・ズーム・効果音・音量調整・
サムネイル・品質チェックまでを自動で行い、投稿できる MP4 を出力します。
Claude Code からは `/clip` スキルで使います（`.claude/skills/clip/SKILL.md`）。

| 工程 | 中身 |
|---|---|
| fetch | yt-dlp で動画＋チャットのリプレイを取得（YouTube はPC上で、自分のブラウザのログインを使用） |
| transcribe | faster-whisper large-v3（GPU自動）で単語単位のタイムスタンプ付き文字起こし。用語辞書を事前に渡す |
| analyze | チャットの勢い・「草/www/！？」などの反応・声の大きさ・用語・画面イベント（任意）から見どころを採点 |
| draft | 候補から clips.yaml を下書き（テロップは文の切れ目と自然な改行で自動生成） |
| render | 無音詰め → レイアウト（中央配置 / 顔カメラ上下 / 縦切り抜き）→ ズーム → 画像 → テロップ → 効果音 → 2パス音量正規化 |
| qc | 解像度・コーデック・尺・−14 LUFS・ピーク・黒画面・無音・テロップ行長・UIに隠れる領域・**再文字起こしで字幕と音声の一致**を検査、一覧画像も出力 |

## セットアップ（Windows）

PowerShell で:

```powershell
cd clipper
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

ffmpeg・Python・依存パッケージを入れます。NVIDIA GPU がある場合は CUDA 版の文字起こしが自動で使われます
（`style.yaml` の `encode.encoder` を `h264_nvenc` にすると書き出しも GPU）。

## 使い方

```bash
python -m clipper run "https://www.youtube.com/watch?v=XXXX" --cookies-from-browser chrome --pick 1-5
```

一つずつ進める場合と、Claude の編集工程は `.claude/skills/clip/SKILL.md` を参照。
テロップは `clips.yaml` の `script:` に校正済みの文を並べて `python -m clipper align WORK` を実行すると、
文字単位で時刻が付きます（Whisper の単語境界のずれを手で直す必要がありません）。
成果物は `work/<id>/out/` に出ます（`c01s.mp4` ＝ ショート、`c01l.mp4` ＝ 横動画、`*_thumb.jpg`、`qc.json`）。

## チャンネルの「型」を変える

- 見た目: `config/style.yaml`（帯・オチ文・テロップの色/サイズ/位置、話者ごとの色、レイアウト、サムネ）
- 用語: `config/glossary.yaml`（固有名詞・誤認識の置換・盛り上がり語）
- 画面イベント検出（任意）: `config/templates/` にゲームの「ロン」「ツモ」等の切り抜きPNGを置く（640x360基準）
- 効果音・画像: `assets/se/`, `assets/images/`（利用規約上、切り抜き動画に使えるものだけ）

## テスト

```bash
python tests/test_pipeline.py        # 合成した配信で 解析→下書き→書き出し(4種)→QC が全て通ること
python tests/test_events.py          # 画面イベント（テンプレート一致）の検出
python tests/test_regressions.py     # 独立レビューと実配信で見つかった不具合の再発防止
```

フォント: M PLUS Rounded 1c Black / Dela Gothic One（SIL Open Font License、`assets/fonts/OFL.txt`）。
