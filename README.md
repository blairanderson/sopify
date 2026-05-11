# SOPify

A [Claude Code](https://claude.com/claude-code) skill that turns workflow videos into Standard Operating Procedure (SOP) markdown documents.

Point it at a screen recording of any business workflow and it will:

1. **Hear what you say** — transcribes the narration with [WhisperX](https://github.com/m-bain/whisperX) (faster-whisper + wav2vec2 forced alignment, ~±20ms word-level timestamps).
2. **See what you do** — combines four sampling signals (narration boundaries, action keywords, pause endpoints, scene change) so it catches small UI events like dropdowns opening, then Claude reads each frame as an image to describe what's on screen, where the cursor is, and what changed.
3. **Interleave both** into a raw timestamped timeline (`timeline.md`) — auditable, chronological.
4. **Track decision points** the operator faces (branching choices the narrator describes or the UI exposes) into `decisions.json`.
5. **Synthesize a polished SOP** — Title, Purpose, Prerequisites, numbered Steps with embedded screenshots, Verification, and Troubleshooting.
6. **Render a companion decision tree** (`DECISION_TREE.md`) — ASCII box-drawing diagram of the branches, cross-referenced to SOP step numbers.

No cloud vision APIs. Frame description uses Claude's native multimodal `Read` tool. Runs entirely on your machine.

## Why this exists

Recording a Loom of "how I do X" is fast. Turning that Loom into a written SOP your team can follow is slow. SOPify closes the gap: record once, get a step-by-step doc with screenshots in minutes.

## Requirements

- macOS, Linux, or Windows. On macOS the skill auto-enables VideoToolbox hardware decode (`-hwaccel videotoolbox`); on other platforms it falls back to software decode automatically — no edits needed.
- [Claude Code](https://claude.com/claude-code)
- `ffmpeg` and `ffprobe` (`brew install ffmpeg`)
- [`whisperx`](https://github.com/m-bain/whisperX) — recommended install: `uv tool install whisperx` (or `pip install whisperx`). First run downloads a ~75 MB ASR model plus a ~360 MB English alignment model into `~/.cache/`.
- Python 3 (stdlib only — no numpy, no cv2, no cloud APIs)

## Install

```bash
git clone git@github.com:blairanderson/sopify.git ~/.claude/skills/sopify
```

Restart Claude Code. The skill activates whenever you mention "sopify" or paste a video path and ask for an SOP.

## Usage

In Claude Code:

```
sopify ~/Desktop/my_workflow.mov
```

The skill will:

1. Extract audio and transcribe with WhisperX (forced-aligned, word-level timestamps).
2. Smart-sample frames using the 4-signal heuristic (see below) into `<video_dir>/sopify_out/<video_basename>/frames/`.
3. Read each frame and write a 1–3 sentence visual description, flagging any decision points as it goes.
4. Build `timeline.md` — the raw interleaved transcript + visuals.
5. If multiple workflows are present, ask whether to produce one combined SOP or one per workflow.
6. Consolidate branching choices into `decisions.json`.
7. Synthesize `SOP.md` (embedded screenshots) and `DECISION_TREE.md` (ASCII box-drawing branches cross-referenced to SOP step numbers).
8. `open` both results.

All artifacts live under `<video_dir>/sopify_out/<video_basename>/` — co-located with the source video so they're findable, version-controllable, and survive reboots. Nothing goes to `/tmp/`.

## How the visual pass works

There's no separate vision API. Frame description uses Claude's multimodal `Read` tool — Claude actually sees each image and writes a 1–3 sentence description (which app, what page, where the cursor is, what changed since the previous frame). A small Python script merges those descriptions with the WhisperX transcript into a single chronological markdown file.

### Smart sampling (not just scene change)

Pixel-diff alone is naive for screen recordings — a click that opens a dropdown changes ~5% of the frame and never triggers a "scene." So we combine **four signals**:

1. **Narration boundaries** — sample at the end of every WhisperX segment (the result of what was just narrated is on screen).
2. **Action-keyword cues** — when the narrator says `click / press / open / close / navigate / select / type / enter / save / submit / choose / pick / scroll / drag / drop / copy / paste / highlight / hover / fill / upload / download / delete / search / toggle / check / uncheck / tap`, sample ~0.7s after the word.
3. **Pause boundaries** — silences >1.5s mean the narrator stopped to do something; sample at the end of the pause.
4. **Low-threshold scene change** — ffmpeg `scene=0.05` (tuned for UI changes, not hard cuts).

Each frame in `frames.json` gets a `source` tag (`narration_end`, `action_keyword`, `pause_end`, `scene_change`, `opening`) so you can see *why* it was sampled. When two signals collide within `--gap` seconds (default `0.4`), the higher-priority source wins (`narration_end` > `action_keyword` > `pause_end` > `scene_change` > `opening`).

Tunable flags on `extract_frames.py`:

- `--scene <T>` — pixel-diff sensitivity (default `0.05`, lower = more frames)
- `--max <N>` — cap on total frames (default `200`)
- `--gap <S>` — merge candidate timestamps within S seconds (default `0.4`)

Pass `none` instead of `audio.json` to fall back to scene change + opening frame only (no narration-driven signals).

## Repo structure

```
sopify/
├── SKILL.md                  # the skill prompt Claude Code reads
├── CLAUDE.md                 # contributor guide for Claude Code working on this repo
├── scripts/
│   ├── extract_frames.py     # 4-signal smart frame sampling → JSON manifest
│   └── merge_timeline.py     # interleave WhisperX segments + described frames → timeline.md
├── assets/
│   └── preview.png
├── README.md
├── LICENSE
└── .gitignore
```

## Output structure

For an input video at `~/videos/onboarding.mov`, outputs land at `~/videos/sopify_out/onboarding/`:

```
<video_dir>/sopify_out/<video_basename>/
├── audio.wav                 # mono 16 kHz, fed to WhisperX
├── audio.json                # WhisperX output: segments + forced-aligned word-level timestamps
├── frames/
│   ├── frame_0001.jpg        # opening state (always)
│   ├── frame_0002.jpg        # next sampled moment
│   ├── ...
│   └── frames.json           # manifest: index, time, path, source (why it was sampled)
├── frames_described.json     # manifest + Claude's 1–3 sentence descriptions (paths relative)
├── decisions.json            # branching choices captured from narration + UI
├── timeline.md               # raw interleaved transcript + visuals (auditable)
├── SOP.md                    # polished SOP with embedded screenshots
└── DECISION_TREE.md          # ASCII box-drawing decision tree, cross-referenced to SOP steps
```

If the video contains multiple workflows and you ask for a split, `SOP.md` and `DECISION_TREE.md` become `SOP_workflow_1.md` / `DECISION_TREE_workflow_1.md`, etc.

## License

MIT — see [LICENSE](LICENSE).
