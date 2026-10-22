import atexit
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import streamlit as st

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB streaming chunks for low RAM usage


def get_yt_dlp():
    """
    Import yt_dlp and automatically reload it from disk if an older (<2026) version
    was cached in sys.modules before a pip upgrade.
    """
    import yt_dlp

    ver = getattr(getattr(yt_dlp, "version", None), "__version__", "")
    if ver and ver.startswith(("2023.", "2024.", "2025.")):
        for mod_name in [
            k for k in list(sys.modules.keys()) if k == "yt_dlp" or k.startswith("yt_dlp.")
        ]:
            sys.modules.pop(mod_name, None)
        yt_dlp = importlib.import_module("yt_dlp")
    return yt_dlp


def get_ydl_base_opts() -> Dict[str, Any]:
    """
    Return base yt-dlp options optimized for Windows:
    - Enables Node.js and Deno JS runtimes for YouTube signature/n-challenge solving.
    - Forces IPv4 (`source_address: 0.0.0.0`) to prevent 2-minute IPv6 timeouts on YouTube & Instagram.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "source_address": "0.0.0.0",
        "socket_timeout": 25,
        "js_runtimes": {"node": {}, "deno": {}},
    }


def subprocess_flags() -> int:
    """Return CREATE_NO_WINDOW on Windows so subprocesses do not spawn console popups."""
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@st.cache_resource(show_spinner=False)
def find_ffmpeg_binaries() -> Tuple[Optional[str], Optional[str]]:
    """
    Locate ffmpeg and ffprobe executables on system PATH, standard Windows directories,
    or via the bundled imageio-ffmpeg fallback.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if os.name == "nt" and not ffmpeg_path:
        candidate_dirs = [
            Path("C:/ffmpeg/bin"),
            Path("C:/Program Files/ffmpeg/bin"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links",
            Path(os.environ.get("USERPROFILE", "")) / "scoop/shims",
            Path("C:/ProgramData/chocolatey/bin"),
        ]
        for folder in candidate_dirs:
            exe = folder / "ffmpeg.exe"
            if exe.is_file():
                ffmpeg_path = str(exe)
                probe_exe = folder / "ffprobe.exe"
                if probe_exe.is_file():
                    ffprobe_path = str(probe_exe)
                break

    if not ffmpeg_path:
        try:
            import imageio_ffmpeg

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_path = None

    if ffmpeg_path and not ffprobe_path:
        sibling = Path(ffmpeg_path).with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe"
        )
        if sibling.is_file():
            ffprobe_path = str(sibling)

    return ffmpeg_path, ffprobe_path


def get_workspace_dir(subdir: Optional[str] = None) -> Path:
    """
    Return a session-scoped temporary directory that is automatically cleaned up on exit.
    Optionally creates and returns a tool-specific subdirectory.
    """
    if "media_tools_workspace" not in st.session_state or not os.path.exists(
        st.session_state["media_tools_workspace"]
    ):
        base_dir = tempfile.mkdtemp(prefix="st_media_tools_")
        st.session_state["media_tools_workspace"] = base_dir
        atexit.register(lambda d=base_dir: shutil.rmtree(d, ignore_errors=True))

    root = Path(st.session_state["media_tools_workspace"])
    if subdir:
        target = root / subdir
        target.mkdir(parents=True, exist_ok=True)
        return target
    return root


def cleanup_all_workspaces() -> None:
    """Delete all temporary files in the current session workspace."""
    if "media_tools_workspace" in st.session_state:
        shutil.rmtree(st.session_state["media_tools_workspace"], ignore_errors=True)
        del st.session_state["media_tools_workspace"]

    keys_to_clear = [
        k
        for k in list(st.session_state.keys())
        if k.startswith(("yt_", "ig_", "mp3_", "pdf_", "bg_"))
    ]
    for k in keys_to_clear:
        st.session_state.pop(k, None)


def save_uploaded_stream(uploaded_file, subdir: str, prefix: str = "upload") -> Path:
    """Stream an uploaded file to disk in 4 MB chunks without duplicating it in memory."""
    folder = get_workspace_dir(subdir)
    for existing in folder.glob(f"{prefix}_*"):
        try:
            existing.unlink()
        except OSError:
            pass

    suffix = Path(uploaded_file.name).suffix.lower()
    safe_stem = sanitize_filename(Path(uploaded_file.name).stem)
    dest = folder / f"{prefix}_{safe_stem}{suffix}"

    uploaded_file.seek(0)
    with open(dest, "wb") as out_f:
        shutil.copyfileobj(uploaded_file, out_f, length=CHUNK_SIZE)
    return dest


def sanitize_filename(name: str, default: str = "media_file") -> str:
    """Remove unsafe filesystem characters from a filename stem."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "")
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:90] or default


def format_bytes(num_bytes: Optional[float]) -> str:
    """Format byte count into human-readable KB / MB / GB."""
    if not num_bytes or num_bytes <= 0:
        return "Unknown size"
    if num_bytes < 1024:
        return f"{int(num_bytes)} B"
    if num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024**3:
        return f"{num_bytes / (1024**2):.2f} MB"
    return f"{num_bytes / (1024**3):.2f} GB"


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS."""
    if not seconds or seconds <= 0:
        return "Unknown"
    total_sec = int(round(seconds))
    mins, secs = divmod(total_sec, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"
