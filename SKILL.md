---
name: sopify
description: Understand the business workflows happening in the video, and create an SOP document. If the video contains multiple workflows, as the user to confirm the depth and breadth of the operations.  Use when the user mentions "sopify" or pastes a video file path and wants an SOP document.
---

# SOPify

Turn a workflow video (typically a screen recording) into a detailed Standard Operating Procedure (SOP) markdown document. The skill **hears** what the user says (Whisper transcript) and **sees** what the user does (scene-change frame samples described inline), interleaves both into a raw timeline, and synthesizes a polished SOP.

## Inputs

- A video file path (the user will provide it; otherwise ask).
- Optional: scene-change sensitivity (default `0.3`; lower = more frames).
- Optional: SOP title/workflow name (otherwise inferred or asked).

## Tooling (use only the fastest path)

- **Whisper:** `whisper --model tiny.en --word_timestamps True --output_format json` (≈10× faster than `small.en`; quality fine for English). For non-English: `--model base` (drop `--language`).
- **ffmpeg:** add `-hwaccel videotoolbox` for decode on macOS. We never re-encode video — we only extract audio and JPEG stills.
- **Python 3** (stdlib only — no numpy, no cv2, no cloud APIs).
- **Scripts:** `<skill-dir>/scripts/` (where `<skill-dir>` is the directory containing this SKILL.md — typically `~/.claude/skills/sopify/`)
  - `extract_frames.py` — scene-change frame extraction → JPEGs + `frames.json` manifest
  - `merge_timeline.py` — interleave Whisper segments + described frames → `timeline.md`

Working dir: `/tmp/sopify/` (mkdir at start, leave artifacts for debugging and re-runs).

---

## Workflow

### Step 1 — Set up & extract audio

```bash
mkdir -p /tmp/sopify/frames
ffmpeg -y -hwaccel videotoolbox -i "$VIDEO" -vn -ac 1 -ar 16000 /tmp/sopify/audio.wav
```

### Step 2 — Transcribe

```bash
whisper /tmp/sopify/audio.wav --model tiny.en --word_timestamps True --output_format json --output_dir /tmp/sopify --language en
```

This writes `/tmp/sopify/audio.json` with segments and word-level timestamps.

### Step 3 — Extract scene-change frames

```bash
python3 <skill-dir>/scripts/extract_frames.py "$VIDEO" /tmp/sopify/frames 0.3
```

This writes `frame_0001.jpg` (always, the opening state at t=0) plus one frame per scene change, and a manifest at `/tmp/sopify/frames/frames.json`.

Report the frame count to the user. Heuristics:

- **>120 frames** → the video is long or the threshold is too sensitive. Offer to retry with `0.4` (or split the video first).
- **<5 frames** → the video has little visual variation. Offer to retry with `0.2` to catch subtler UI changes (cursor moves, modal opens, dropdowns).
- **5–120** → proceed.

### Step 4 — Describe each frame (vision pass)

Read `/tmp/sopify/frames/frames.json`. For each entry, use the `Read` tool on the frame's `path` so you actually see the image, then write a 1–3 sentence description focused on:

- Which app, page, or screen is visible (specific names — "Stripe Dashboard → Customers" beats "a dashboard").
- What UI element is highlighted, focused, or being interacted with.
- Where the cursor is and what it is hovering near.
- What state has changed since the previous frame (modal opened, row added, field filled).

Format each description as a single string, e.g.:

> User is on the QuickBooks dashboard, on the "Sales → Invoices" page. The cursor is hovering over the green "+ New invoice" button in the top-right. A previously-open filter dropdown has closed.

Save the augmented manifest to `/tmp/sopify/frames_described.json` — same JSON shape as `frames.json` plus a `"description"` field on each entry.

If two consecutive frames look essentially identical, *merge* their descriptions (write one description that spans both timestamps) rather than producing two near-duplicate `[Visual: ...]` blocks. The simplest way: keep both entries but write the same description twice — `merge_timeline.py` doesn't dedupe, but a human reader can tell they're paired.

### Step 5 — Build the raw timeline

```bash
python3 <skill-dir>/scripts/merge_timeline.py /tmp/sopify/audio.json /tmp/sopify/frames_described.json /tmp/sopify/timeline.md
```

This produces `/tmp/sopify/timeline.md` — chronological blocks of `## [HH:MM:SS] Visual` (with embedded `![](frames/frame_NNNN.jpg)` and `Visual: ...`) and `## [HH:MM:SS] Narration` (with verbatim transcript quotes). This is the auditable record — don't skip it.

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

Compose `/tmp/sopify/SOP.md` (or one file per workflow if the user asked for splits) with this structure:

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

Embed only **key** screenshots — typically one per numbered step at the moment the action commits (button clicked, form submitted, modal confirmed). All frames are still on disk under `/tmp/sopify/frames/` if the reader wants more.

### Step 8 — Deliver

- Print the path: `/tmp/sopify/SOP.md` (and `/tmp/sopify/timeline.md` for audit).
- `open /tmp/sopify/SOP.md`
- Offer to:
  - Re-run with a different scene threshold if the SOP missed a step or has too many redundant frames.
  - Split into multiple SOPs (or merge them) if the scope question was answered wrong.
  - Copy outputs into `<source_dir>/sopify_out/` for permanent storage.

---

## Pitfalls (lessons — don't repeat)

- **Don't paraphrase prerequisites the narrator didn't actually state.** If you derive a prerequisite purely from frames (e.g. "must have admin role"), tag it `(inferred)` so the reader knows.
- **Cursor position matters in screen recordings.** Always call out where the cursor is and what it's near — that's often the only signal of what's about to be clicked.
- **One step per *user intent*, not one step per scene-change frame.** Multiple frames often belong to one step (cursor moves toward button → button hovers → modal opens). Group them.
- **Don't number steps faster than the video does.** If the narrator says "step three" verbatim, your SOP step 3 should match.
- **Verbatim quotes > paraphrasing** when the narrator is precise. When the narrator is rambling, paraphrase.
- **State the plan in one line, then act.** Don't narrate every frame extraction iteration.
