# SOPify

A [Claude Code](https://claude.com/claude-code) skill that turns workflow videos into Standard Operating Procedure (SOP) markdown documents.

Point it at a screen recording of any business workflow and it will:

1. **Hear what you say** — transcribes the narration with [Whisper](https://github.com/openai/whisper), with word-level timestamps.
2. **See what you do** — samples frames at every scene change, and Claude reads each one as an image to describe what's on screen, where the cursor is, and what changed.
3. **Interleave both** into a raw timestamped timeline (`timeline.md`) — auditable, chronological.
4. **Synthesize a polished SOP** — Title, Purpose, Prerequisites, numbered Steps with embedded screenshots, Verification, and Troubleshooting.

No cloud vision APIs. Frame description uses Claude's native multimodal `Read` tool. Runs entirely on your machine.

## Why this exists

Recording a Loom of "how I do X" is fast. Turning that Loom into a written SOP your team can follow is slow. SOPify closes the gap: record once, get a step-by-step doc with screenshots in minutes.

## Requirements

- macOS (uses VideoToolbox for hardware-accelerated decode — works on Linux/Windows if you remove `-hwaccel videotoolbox` from `SKILL.md`)
- [Claude Code](https://claude.com/claude-code)
- `ffmpeg` (`brew install ffmpeg`)
- [`whisper`](https://github.com/openai/whisper) (`pip install openai-whisper`)
- Python 3 (stdlib only — no numpy, no cv2)

## Install

```bash
git clone <this-repo> ~/.claude/skills/sopify
```

Restart Claude Code. The skill activates whenever you mention "sopify" or paste a video path and ask for an SOP.

## Usage

In Claude Code:

```
sopify ~/Desktop/my_workflow.mov
```

The skill will:

1. Extract audio and transcribe with Whisper.
2. Sample scene-change frames into `/tmp/sopify/frames/`.
3. Read each frame and write a `[Visual: ...]` description.
4. Build `/tmp/sopify/timeline.md` — the raw interleaved transcript + visuals.
5. If multiple workflows are present, ask whether to produce one combined SOP or one per workflow.
6. Synthesize `/tmp/sopify/SOP.md` with embedded screenshots.
7. `open` the result.

All artifacts live under `/tmp/sopify/` so you can re-run, inspect, or copy them out.

## How the visual pass works

There's no separate vision API. Frame description uses Claude's multimodal `Read` tool — Claude actually sees each image and writes a 1–3 sentence description (which app, what page, where the cursor is, what changed since the previous frame). A small Python script merges those descriptions with the Whisper transcript into a single chronological markdown file.

### Smart sampling (not just scene change)

Pixel-diff alone is naive for screen recordings — a click that opens a dropdown changes ~5% of the frame and never triggers a "scene." So we combine **four signals**:

1. **Narration boundaries** — sample at the end of every Whisper segment (the result of what was just narrated is on screen).
2. **Action-keyword cues** — when the narrator says `click / open / select / type / navigate / save / scroll / submit / press / hover / fill / paste / drag / upload / search / tap` etc., sample ~0.7s after the word.
3. **Pause boundaries** — silences >1.5s mean the narrator stopped to do something; sample at the end of the pause.
4. **Low-threshold scene change** — ffmpeg `scene=0.05` (tuned for UI changes, not hard cuts).

Each frame in `frames.json` gets a `source` tag (`narration_end`, `action_keyword`, `pause_end`, `scene_change`, `opening`) so you can see *why* it was sampled.

## Repo structure

```
sopify/
├── SKILL.md                  # the skill prompt Claude Code reads
├── scripts/
│   ├── extract_frames.py     # ffmpeg scene-change frame extraction → JSON manifest
│   └── merge_timeline.py     # interleave Whisper segments + described frames → timeline.md
├── README.md
└── LICENSE
```

## Output structure

```
/tmp/sopify/
├── audio.wav                 # mono 16 kHz, fed to Whisper
├── audio.json                # Whisper output, word-level timestamps
├── frames/
│   ├── frame_0001.jpg        # opening state (always)
│   ├── frame_0002.jpg        # first scene change
│   ├── ...
│   └── frames.json           # manifest: index, time, path
├── frames_described.json     # manifest + Claude's descriptions
├── timeline.md               # raw interleaved transcript + visuals
└── SOP.md                    # polished SOP, embedded screenshots
```

## License

MIT — see [LICENSE](LICENSE).
