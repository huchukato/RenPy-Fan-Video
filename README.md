# RenPy-Fan-Video

Standalone PySide6 tool to create fan video patches for Ren'Py games.

## What it does

RenPy-Fan-Video extracts the static images used in scenes from a Ren'Py game and lets you replace them with externally created `.webm` videos. It generates a `fan_videos.rpy` patch that redefines the original `image` definitions with `Movie(...)`, using `init 999` to guarantee the patch loads **after** the original definitions — so the latest `image` wins without modifying any game files.

## Features

- **Extract & decompile**: extracts `.rpa` archives and decompiles `.rpyc` files automatically
- **Scan**: finds all `scene`/`show` statements and resolves the image files on disk
- **Gallery**: filter/search thousands of images, preview them, pick which ones to animate
- **Associate**: pick a `.webm` video — the last frame is extracted automatically via ffmpeg so the video freezes on the final frame instead of going black
- **Generate patch**: creates `game/fan_videos.rpy` with `init 999:` block, copies videos and frames
- **Export mod**: create a shareable ZIP with the patch, videos, and install instructions
- **Multi-language**: English, Italian, Spanish with live switching
- **Auto-save/restore**: session state is saved automatically and restored on restart

## Requirements

- Python 3.9+
- PySide6 6.6+
- Pillow 10+
- ffmpeg (for automatic last-frame extraction)
- uv (automatically handled by `start.sh` / `start.bat`)

## Launch

### macOS / Linux

```bash
./start.sh
```

### Windows

```bat
start.bat
```

## Usage

1. **Select the game**: choose the macOS `.app` or the folder containing `game/`.
2. **Analyze**: the tool extracts `.rpa` archives, decompiles `.rpyc` files, and scans `scene`/`show` statements for static images.
3. **Gallery**: filter and search images, preview them, and pick the one to replace.
4. **Add to Patch**: export the image and add it to the patch list.
5. **Associate video**: double-click a patch entry, pick a `.webm` file. The last frame is extracted automatically.
6. **Generate patch**: creates `game/fan_videos.rpy`, copies videos into `game/videos/`, and last frames into `game/images/video frames/`.
7. **Export mod** (optional): create a ZIP to share with others.
8. **Run the game**: scenes that showed the original image will now play the video.

## Generated files

- `game/fan_videos.rpy` — `init 999:` block with `image ... = Movie(...)` definitions
- `game/videos/*.webm` — copied videos
- `game/images/video frames/*.jpg` — last frames (auto-extracted)

## Uninstall

Delete `game/fan_videos.rpy` and the associated video files in `game/videos/`.

## Project structure

```
RenPy-Fan-Video/
├── fv_tool.py        # PySide6 GUI (main entry point)
├── fv_extractor.py   # .rpa extraction + .rpyc decompilation
├── fv_scanner.py     # scene/show scanning + image resolution
├── fv_generator.py   # patch generation (fan_videos.rpy)
├── fv_project.py     # project state management (sources/, videos/)
├── pyproject.toml    # Dependencies
├── start.sh          # macOS/Linux launcher
├── start.bat         # Windows launcher
├── img/              # Logo and icons
└── UnRen Tools/      # rpatool + unrpyc (decompilation)
```

## How it works

The tool leverages a simple Ren'Py behavior: **the last `image` definition wins**. By placing our patch in `game/fan_videos.rpy` with `init 999:`, we guarantee it loads after all original definitions. Each `image <name> = Movie(...)` replaces the original static image with a video that plays when the scene shows that image.

## Notes

- The tool does not modify the original game files.
- Videos must be `.webm` (Ren'Py's native video format).
- ffmpeg is used to extract the last frame automatically — without it, videos will loop or go black at the end.
