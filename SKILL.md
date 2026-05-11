---
name: sopify
description: Understand the business workflows happening in a screen recording, and produce a Standard Operating Procedure (SOP) markdown document with embedded screenshots. If the video contains multiple workflows, ask the user to confirm scope. Use when the user mentions "sopify", pastes a video file path (e.g. .mp4, .mov, .webm), or attaches a video file and wants an SOP.
---

# SOPify

Turn a workflow video (typically a screen recording) into a detailed Standard Operating Procedure (SOP) markdown document. The skill **hears** what the user says (Whisper transcript) and **sees** what the user does (scene-change frame samples described inline), interleaves both into a raw timeline, and synthesizes a polished SOP.

## Inputs

- A video file path (the user will provide it; otherwise ask).
- Optional: frame-sampling overrides for Step 3 — `--scene <N>` (pixel-diff sensitivity, default `0.05`, lower = more frames), `--max <N>` (cap on total frames, default `200`), `--gap <N>` (merge sampling candidates within N seconds, default `0.4`).
- Optional: SOP title/workflow name (otherwise inferred or asked).

## Tooling (use only the fastest path)

- **Whisper:** `whisper --model tiny.en --word_timestamps True --output_format json` (≈10× faster than `small.en`; quality fine for English). For non-English: `--model base` (drop `--language`).
- **ffmpeg:** add `-hwaccel videotoolbox` for decode on macOS. We never re-encode video — we only extract audio and JPEG stills.
- **Python 3** (stdlib only — no numpy, no cv2, no cloud APIs).
- **Scripts:** `<skill-dir>/scripts/` (where `<skill-dir>` is the directory containing this SKILL.md — typically `~/.claude/skills/sopify/`)
  - `extract_frames.py` — smart frame sampling combining 4 signals (narration boundaries, action keywords, pause endpoints, scene change) → JPEGs + `frames.json` manifest
  - `merge_timeline.py` — interleave Whisper segments + described frames → `timeline.md`

Working dir: `<source_video_dir>/sopify_out/<video_basename>/` (mkdir at start, persistent — every intermediate artifact lives here so the user can audit each step). Never use `/tmp/` for sopify outputs. The bundle co-locates with the source video so it's findable, version-controllable, and survives reboots.

Resolve it at the top of Step 1:

```bash
VIDEO_DIR="$(cd "$(dirname "$VIDEO")" && pwd)"
VIDEO_BASE="$(basename "$VIDEO" | sed 's/\.[^.]*$//')"
WORK="$VIDEO_DIR/sopify_out/$VIDEO_BASE"
```

All subsequent steps reference `$WORK/` — not `/tmp/sopify/`. Example tree for `~/dev/brokerage/sops/walmart-dc-reactive-services.mp4`:

```
~/dev/brokerage/sops/sopify_out/walmart-dc-reactive-services/
├── audio.wav
├── audio.json
├── frames/
│   ├── frames.json
│   └── frame_0001.jpg … frame_NNNN.jpg
├── frames_described.json
├── timeline.md
└── SOP.md
```

---

## Workflow

### Decision tree (read this first)

```
START
  │
  ▼
[Has video path?] ── No ──> Ask user. WAIT.
  │
  Yes
  ▼
Step 1: ffmpeg              →  $WORK/audio.wav
Step 2: whisper             →  $WORK/audio.json
Step 3: extract_frames.py   →  $WORK/frames/, $WORK/frames/frames.json
  │
  ▼
[Frame count?]
  ├─ <8       ──> Offer retry: --scene 0.02 --gap 0.25
  ├─ >180     ──> Offer retry: --max 120 --gap 0.8
  └─ 8 – 180  ──> Continue.
  │
  ▼
Step 4: Vision pass (Read every frame, describe in 1–3 sentences)
        →  $WORK/frames_described.json  (path fields RELATIVE)
Step 5: merge_timeline.py   →  $WORK/timeline.md
  │
  ▼
[How many distinct workflows in timeline?]
  ├─ 1        ──> Continue. Single SOP.
  └─ 2 +      ──> Ask: combined or split? WAIT.
  │
  ▼
Step 7: Compose SOP(s)      →  $WORK/SOP.md  (or SOP_workflow_N.md)
Step 8: Print paths + open. Done.
```

Two WAIT points only — missing video path, and >1 workflow detected in Step 6. Everything else flows straight through; the heuristic branches in Step 3 are *offered* to the user but don't block — if the count is in range, proceed without asking.

### Step 1 — Set up & extract audio

```bash
VIDEO_DIR="$(cd "$(dirname "$VIDEO")" && pwd)"
VIDEO_BASE="$(basename "$VIDEO" | sed 's/\.[^.]*$//')"
WORK="$VIDEO_DIR/sopify_out/$VIDEO_BASE"
mkdir -p "$WORK/frames"

# Hardware-decode flag is macOS-only; omit on Linux.
HWACCEL=""
[ "$(uname)" = "Darwin" ] && HWACCEL="-hwaccel videotoolbox"

ffmpeg -y $HWACCEL -i "$VIDEO" -vn -ac 1 -ar 16000 "$WORK/audio.wav"
```

### Step 2 — Transcribe

```bash
whisper "$WORK/audio.wav" --model tiny.en --word_timestamps True --output_format json --output_dir "$WORK"
```

This writes `$WORK/audio.json` with segments and word-level timestamps.

### Step 3 — Smart frame sampling (4 signals combined)

Pixel-diff alone is naive for screen recordings: a click that opens a small dropdown only changes ~5% of the frame and slides under `scene=0.3`. `extract_frames.py` combines **four signals** so we sample at moments the workflow actually advanced:

1. **Narration boundaries** — sample at the end of every Whisper segment (the result of what was just described is on screen now).
2. **Action-keyword cues** — when the narrator says `click / open / select / type / navigate / save / scroll / submit / press / choose / enter / paste / drag / hover / fill / upload / search / toggle / check / tap`, sample ~0.7s after that word's timestamp.
3. **Pause boundaries** — silences >1.5s between segments mean the narrator stopped to *do* something; sample at the end of the pause.
4. **Low-threshold scene change** — `select='gt(scene,0.05)'` (default), tuned for UI changes, not video cuts.

```bash
python3 <skill-dir>/scripts/extract_frames.py "$VIDEO" "$WORK/frames" "$WORK/audio.json"
```

Optional flags: `--scene 0.05` (sensitivity), `--max 200` (cap), `--gap 0.4` (merge candidates within N seconds). Pass `none` instead of `audio.json` to fall back to scene-change + opening frame only.

The manifest at `$WORK/frames/frames.json` includes a `source` field per frame (`opening | narration_end | action_keyword | pause_end | scene_change`) so you can see *why* each frame was picked.

Report the frame count to the user. Heuristics:

- **>180 frames** → the video is dense or thresholds are too sensitive. Offer to retry with `--max 120 --gap 0.8`.
- **<8 frames** → the narrator is quiet and the screen is static. Offer to retry with `--scene 0.02 --gap 0.25`.
- **8–180** → proceed.

### Step 4 — Describe each frame (vision pass)

Read `$WORK/frames/frames.json`. For each entry, use the `Read` tool on the frame's `path` so you actually see the image, then write a 1–3 sentence description focused on:

- Which app, page, or screen is visible (specific names — "Stripe Dashboard → Customers" beats "a dashboard").
- What UI element is highlighted, focused, or being interacted with.
- Where the cursor is and what it is hovering near.
- What state has changed since the previous frame (modal opened, row added, field filled).

Format each description as a single string, e.g.:

> User is on the QuickBooks dashboard, on the "Sales → Invoices" page. The cursor is hovering over the green "+ New invoice" button in the top-right. A previously-open filter dropdown has closed.

Save the augmented manifest to `$WORK/frames_described.json` — same JSON shape as `frames.json` plus a `"description"` field on each entry. **Important:** rewrite the `path` field on each entry from absolute to relative (`frames/frame_NNNN.jpg`, not `$WORK/frames/...` or `/tmp/...`). This matches the relative paths the final SOP will embed (`![](frames/frame_0001.jpg)`) and keeps the bundle portable if the user moves it.

If two consecutive frames look essentially identical, **drop the redundant entry from `frames_described.json` before running merge_timeline.py.** The script doesn't dedupe — pre-filtering the manifest is the cleanest fix. If you're unsure whether two frames are truly identical, keep both; the synthesis step in Step 7 can still embed only one screenshot per logical step.

### Step 5 — Build the raw timeline

```bash
python3 <skill-dir>/scripts/merge_timeline.py "$WORK/audio.json" "$WORK/frames_described.json" "$WORK/timeline.md"
```

This produces `$WORK/timeline.md` — chronological blocks of `## [HH:MM:SS] Visual` (with embedded `![](frames/frame_NNNN.jpg)` and `Visual: ...`) and `## [HH:MM:SS] Narration` (with verbatim transcript quotes). This is the auditable record — don't skip it.

### Step 6 — Disambiguate workflow scope

Read `timeline.md` end to end. If the video contains **multiple distinct workflows** (e.g. "first I'll show invoicing, then payroll"), surface the boundaries to the user:

> I see roughly 3 workflows in this video:
> 1. Creating a new customer (00:00–02:14)
> 2. Generating an invoice (02:14–05:30)
> 3. Recording a payment (05:30–end)
>
> Do you want one combined SOP or one SOP per workflow?

If it's a single workflow, skip the question and proceed.

### Step 7 — Synthesize the polished SOP

Compose `$WORK/SOP.md` (or one file per workflow if the user asked for splits — `$WORK/SOP_workflow_1.md`, `$WORK/SOP_workflow_2.md`, etc.) with this structure:

```markdown
# <Workflow Title>

## Purpose
1–2 sentences on what this SOP accomplishes and why someone would run it.

## Prerequisites
- Account / permission requirements (mark "(inferred)" if not stated by the narrator)
- Tools, browser tabs, files needed before starting
- State the workflow assumes (e.g. "Customer must already exist")

## Steps

### 1. <Action sentence in imperative mood>

![](frames/frame_NNNN.jpg)

Detailed instruction. Use the narrator's verbatim wording where useful:

> "Click the green New Invoice button in the top-right corner."

- Sub-bullet for sub-action
- Sub-bullet for sub-action

**Note:** Any warning/gotcha the narrator mentioned.

### 2. <Next action>
...

## Verification
How to confirm the workflow succeeded — inferred from the end of the video (success state, confirmation message, expected outcome).

## Troubleshooting
Only if the narrator mentioned what to do when X fails. Otherwise omit.
```

Embed only **key** screenshots — typically one per numbered step at the moment the action commits (button clicked, form submitted, modal confirmed). All frames are still on disk under `$WORK/frames/` if the reader wants more.

### Step 8 — Deliver

- Print all paths on separate lines so the user knows where everything is:
  - **SOP:** `$WORK/SOP.md`
  - **Audit timeline:** `$WORK/timeline.md`
  - **Full bundle:** `$WORK/` (also contains `audio.wav`, `audio.json`, `frames/`, `frames_described.json` — every intermediate the model produced, kept for auditing)
- `open "$WORK/SOP.md"`
- Offer to:
  - Re-run with a different scene threshold (`--scene 0.02` for more frames, `--scene 0.05 --gap 0.8` for fewer) if the SOP missed a step or has too many redundant frames.
  - Split into multiple SOPs (or merge them) if the scope question in Step 6 was answered wrong.
  - Delete `$WORK/audio.wav` once the user has finished auditing — it's the largest file in the bundle.

---

## Pitfalls (lessons — don't repeat)

- **Don't paraphrase prerequisites the narrator didn't actually state.** If you derive a prerequisite purely from frames (e.g. "must have admin role"), tag it `(inferred)` so the reader knows.
- **Cursor position matters in screen recordings.** Always call out where the cursor is and what it's near — that's often the only signal of what's about to be clicked.
- **One step per *user intent*, not one step per scene-change frame.** Multiple frames often belong to one step (cursor moves toward button → button hovers → modal opens). Group them.
- **Don't number steps faster than the video does.** If the narrator says "step three" verbatim, your SOP step 3 should match.
- **Verbatim quotes > paraphrasing** when the narrator is precise. When the narrator is rambling, paraphrase.
- **State the plan in one line, then act.** Don't narrate every frame extraction iteration.
- **`path` fields in `frames_described.json` are relative, not absolute.** The bundle is portable — `sops/sopify_out/<video>/` can be moved to another machine. Absolute `/tmp/...` or `$WORK/...` paths break this; always emit `frames/frame_NNNN.jpg`.
- **Describe what you see, not what you guess the screenshot says.** Low-res screen recordings invite OCR-style hallucination (claiming the button reads "Submit Form" when it actually reads "Submit Order"). When text is small or blurry, describe the UI element ("a blue primary button in the form footer") instead of inventing the label.
