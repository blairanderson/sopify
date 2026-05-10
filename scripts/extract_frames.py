#!/usr/bin/env python3
"""
extract_frames.py — extract scene-change frames from a video for SOPify.

Usage:
    extract_frames.py VIDEO OUT_DIR [SCENE_THRESHOLD]

Args:
    VIDEO            path to source video
    OUT_DIR          directory to write frame_NNNN.jpg files into
    SCENE_THRESHOLD  ffmpeg scene-detection threshold 0.0-1.0 (default 0.3).
                     Lower = more sensitive (more frames). 0.2 catches
                     subtle UI changes; 0.4+ only catches hard cuts.

Behavior:
    - Always emits frame_0001.jpg at t=0.0 (the opening state).
    - Then runs ffmpeg with select='gt(scene,T)',showinfo and parses
      pts_time from stderr to learn each captured frame's timestamp.
    - Writes OUT_DIR/frames.json with the manifest.

Output JSON shape:
    [
      {"index": 1, "time": 0.000, "path": "<OUT_DIR>/frame_0001.jpg"},
      {"index": 2, "time": 4.213, "path": "<OUT_DIR>/frame_0002.jpg"},
      ...
    ]

No external Python deps. Requires ffmpeg in PATH.
"""

import json
import os
import re
import subprocess
import sys


def usage():
    sys.stderr.write(__doc__)
    sys.exit(2)


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        usage()

    video = sys.argv[1]
    out_dir = sys.argv[2]
    threshold = float(sys.argv[3]) if len(sys.argv) >= 4 else 0.3

    if not os.path.isfile(video):
        sys.stderr.write(f"error: video not found: {video}\n")
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)

    # Step 1: emit frame_0001.jpg at t=0.0 as the opening state.
    opening = os.path.join(out_dir, "frame_0001.jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", "0",
            "-i", video,
            "-frames:v", "1",
            "-q:v", "3",
            opening,
        ],
        check=True,
    )

    # Step 2: extract scene-change frames into frame_0002.jpg onward.
    # We use start_number=2 so the scene frames don't collide with frame_0001.
    pattern = os.path.join(out_dir, "frame_%04d.jpg")
    proc = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video,
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-vsync", "vfr",
            "-q:v", "3",
            "-start_number", "2",
            pattern,
        ],
        capture_output=True,
        text=True,
    )

    # ffmpeg writes showinfo lines to stderr like:
    #   [Parsed_showinfo_1 @ 0x...] n:   0 pts: 12345 pts_time:4.213 ...
    # Parse pts_time values in order — they correspond to frame_0002, frame_0003, ...
    pts_times = []
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            pts_times.append(float(m.group(1)))

    # Build manifest. frame_0001 is always t=0.0, then one entry per pts_time.
    manifest = [{"index": 1, "time": 0.0, "path": opening}]
    for i, t in enumerate(pts_times, start=2):
        path = os.path.join(out_dir, f"frame_{i:04d}.jpg")
        if not os.path.isfile(path):
            # ffmpeg may have reported a pts_time but not written a file
            # (rare, but skip safely).
            continue
        manifest.append({"index": i, "time": round(t, 3), "path": path})

    # Sanity: drop any extra files ffmpeg wrote past what we tracked.
    # (Don't actively delete — just don't list them.)

    out_json = os.path.join(out_dir, "frames.json")
    with open(out_json, "w") as f:
        json.dump(manifest, f, indent=2)

    sys.stderr.write(
        f"sopify/extract_frames: wrote {len(manifest)} frames "
        f"(threshold={threshold}) -> {out_json}\n"
    )
    print(out_json)


if __name__ == "__main__":
    main()
