# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Claude Code **skill**, not a runtime application. The deliverable Claude Code loads is `SKILL.md` (frontmatter + prompt). The two Python files under `scripts/` are helpers that prompt calls out to. There is no build step, no package manager, no test suite — edits are validated by running the skill end-to-end on a real video.

When the skill is installed (cloned to `~/.claude/skills/sopify/`), Claude Code activates it when the user says "sopify" or pastes a video path.

## Architecture: how the four pieces fit

The pipeline is intentionally split so each stage is auditable in isolation:

```
video ──► ffmpeg ──► audio.wav
                       │
                       ▼
                  whisperx (tiny.en, forced alignment) ──► audio.json
                       │
                       ▼
   extract_frames.py (4-signal smart sampling) ──► frames/*.jpg + frames.json
                       │
                       ▼
       Claude reads each frame via Read tool, writes description
                       │
                       ▼
                  frames_described.json   ──┐
                                            ├──► merge_timeline.py ──► timeline.md
                  audio.json              ──┘
                       │
                       ▼
          Claude synthesizes from timeline.md + decisions.json
                       │
                       ▼
              SOP.md + DECISION_TREE.md
```

The **vision pass has no separate API**: Claude itself reads each JPEG via the `Read` tool. That's the whole reason the skill works without cloud vision credentials. `extract_frames.py` just picks *which* frames to sample; the description loop lives in the skill prompt, not in code.

`extract_frames.py` combines four signals because pixel-diff alone is naive for screen recordings — a dropdown opening changes ~5% of pixels and slides under any sane scene threshold. The four signals are tagged in `frames.json`'s `source` field (`opening | narration_end | action_keyword | pause_end | scene_change`) and merged with a priority order in `dedupe()`/`cap()` — when two candidates collide within `--gap` seconds, the higher-priority source wins. Keep that priority table consistent across both functions if you edit it.

## Working directory contract

Output goes to `<video_dir>/sopify_out/<video_basename>/`, **never** `/tmp/`. The bundle co-locates with the source video so it's findable, version-controllable, and survives reboots. The skill resolves `$WORK` at the top of Step 1 — every later step references `$WORK/`.

Inside the bundle, **`path` fields in `frames_described.json` must be relative** (`frames/frame_NNNN.jpg`), not absolute. The final SOP embeds them as `![](frames/...)`, so the bundle stays portable if the user moves it. `extract_frames.py` currently emits absolute paths in `frames.json`; the skill prompt rewrites them to relative when it produces `frames_described.json`. If you change this, change both ends.

## Editing the skill

- `SKILL.md` is the source of truth for behavior. The frontmatter `description` controls when Claude Code activates the skill — keep its trigger phrases ("sopify", video file paths) intact.
- The internal "Decision tree" at the top of the Workflow section mirrors actual control flow. If you add or remove a WAIT point (currently: missing video path, multiple workflows detected), update that diagram.
- The pitfalls list at the bottom is hard-won. Don't drop entries without a good reason — each one corresponds to a real failure mode from past runs.

## Editing the scripts

Constraints, in order of importance:

1. **Python stdlib only.** No numpy, no cv2, no `requests`. The README advertises this; users `pip install` nothing.
2. **`ffmpeg` and `ffprobe` are the only external binaries.** `-hwaccel videotoolbox` is macOS-only — keep it gated on `uname == Darwin` in the skill prompt (the scripts themselves don't use it).
3. **Never re-encode video.** Audio extraction and single-frame JPEG stills only.
4. `extract_frames.py` prints the output JSON path to stdout and a summary line to stderr. Don't swap those — the skill prompt may pipe stdout.

## Testing changes

There's no automated test. To validate an edit:

```bash
# Pick a short screen recording you have on disk
VIDEO=~/path/to/some_workflow.mov
VIDEO_DIR="$(cd "$(dirname "$VIDEO")" && pwd)"
VIDEO_BASE="$(basename "$VIDEO" | sed 's/\.[^.]*$//')"
WORK="$VIDEO_DIR/sopify_out/$VIDEO_BASE"
mkdir -p "$WORK/frames"

ffmpeg -y -hwaccel videotoolbox -i "$VIDEO" -vn -ac 1 -ar 16000 "$WORK/audio.wav"
whisperx "$WORK/audio.wav" --model tiny.en --output_format json --compute_type int8 --device cpu --output_dir "$WORK"
python3 scripts/extract_frames.py "$VIDEO" "$WORK/frames" "$WORK/audio.json"
```

Then inspect `$WORK/frames/frames.json` — the `source` distribution tells you whether the heuristics fired sensibly. Sanity targets: 8–180 frames, a mix of sources (not all `scene_change`).

To test the merge in isolation, hand-edit `frames.json` into a `frames_described.json` by adding a `"description"` field to each entry, then:

```bash
python3 scripts/merge_timeline.py "$WORK/audio.json" "$WORK/frames_described.json" "$WORK/timeline.md"
```

## Installation note

The skill lives at `~/.claude/skills/sopify/`. If `<skill-dir>` references in `SKILL.md` ever stop working, that's because the user installed somewhere else — the skill resolves the path from where Claude Code loaded it. Don't hardcode `~/.claude/skills/sopify/` in command examples; keep the `<skill-dir>` placeholder.
