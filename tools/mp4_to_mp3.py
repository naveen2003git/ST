import collections
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import streamlit as st

from tools.utils import (
    find_ffmpeg_binaries,
    format_bytes,
    format_duration,
    get_workspace_dir,
     sanitize_filename,
    save_uploaded_stream,
    subprocess_flags,
)

BITRATE_OPTIONS: Dict[str, str] = {
    "128 kbps (Standard Quality — Smaller File)": "128k",
    "192 kbps (High Quality — Balanced)": "192k",
    "256 kbps (Studio Quality — Rich Audio)": "256k",
}


def inspect_mp4_audio(video_path: Path, ffmpeg_bin: str) -> Tuple[bool, float, Optional[str]]:
    """Check whether the uploaded MP4 contains an audio stream and return (has_audio, duration, codec)."""
    proc = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-i", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=25,
        creationflags=subprocess_flags(),
    )
    stderr_text = proc.stderr or ""

    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr_text)
    duration = 0.0
    if dur_match:
        hrs, mins, secs = (
            int(dur_match.group(1)),
            int(dur_match.group(2)),
            float(dur_match.group(3)),
        )
        duration = hrs * 3600 + mins * 60 + secs

    audio_match = re.search(r"Stream #.*Audio:\s*([a-zA-Z0-9_]+)", stderr_text)
    if not audio_match:
        return False, duration, None
    return True, duration, audio_match.group(1)


def convert_mp4_to_mp3(
    ffmpeg_bin: str,
    input_path: Path,
    output_path: Path,
    bitrate: str,
    duration: float,
    progress_bar,
    status_text,
) -> Tuple[bool, str, float]:
    """Convert MP4 audio track to MP3 using FFmpeg libmp3lame with real-time progress."""
    start_time = time.perf_counter()
    stderr_buf: collections.deque = collections.deque(maxlen=100)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess_flags(),
    )

    def _drain_stderr(pipe, buf: collections.deque) -> None:
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    buf.append(line.rstrip())
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t = threading.Thread(target=_drain_stderr, args=(proc.stderr, stderr_buf), daemon=True)
    t.start()

    try:
        assert proc.stdout is not None
        for raw_line in iter(proc.stdout.readline, ""):
            line = raw_line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key == "out_time_us" and duration > 0:
                try:
                    sec = max(0.0, int(val) / 1_000_000.0)
                    pct = min(99, int(round((sec / duration) * 100)))
                    progress_bar.progress(pct, text=f"Extracting MP3 audio... {pct}%")
                    status_text.caption(
                        f"⏱️ Processed: **{sec:.1f}s** / **{duration:.1f}s**"
                    )
                except ValueError:
                    pass
            elif key == "progress" and val == "end":
                progress_bar.progress(100, text="Conversion complete! (100%)")
        proc.wait()
        t.join(timeout=2.0)
    except Exception as exc:
        proc.kill()
        return False, str(exc), 0.0

    elapsed = time.perf_counter() - start_time
    if proc.returncode != 0:
        return False, "\n".join(stderr_buf) or "FFmpeg returned a non-zero exit code.", elapsed

    progress_bar.progress(100, text="Conversion complete! (100%)")
    status_text.empty()
    return True, "", elapsed


def render_mp4_to_mp3() -> None:
    """Render the MP4 to MP3 Converter page."""
    st.header("🎵 MP4 to MP3 Audio Converter")
    st.markdown(
        "Upload any **MP4** video file and extract its audio track to a high-quality **MP3** file "
        "at **128 kbps**, **192 kbps**, or **256 kbps** using **FFmpeg**."
    )

    ffmpeg_bin, _ = find_ffmpeg_binaries()
    if not ffmpeg_bin:
        st.error(
            "⚠️ **FFmpeg not found.** Please install FFmpeg to convert MP4 videos to MP3."
        )
        return

    uploaded_mp4 = st.file_uploader(
        "Upload an MP4 Video File",
        type=["mp4"],
        help="Large files are streamed safely to disk without overflowing memory.",
    )

    if uploaded_mp4 is not None:
        file_sig = f"{uploaded_mp4.name}_{uploaded_mp4.size}"
        if st.session_state.get("mp3_input_sig") != file_sig:
            with st.spinner("Reading MP4 file and inspecting audio stream..."):
                saved_path = save_uploaded_stream(uploaded_mp4, subdir="mp4_to_mp3", prefix="input")
                has_audio, duration, codec = inspect_mp4_audio(saved_path, ffmpeg_bin)
                st.session_state["mp3_input_sig"] = file_sig
                st.session_state["mp3_input_info"] = {
                    "path": str(saved_path),
                    "orig_name": uploaded_mp4.name,
                    "size": uploaded_mp4.size,
                    "has_audio": has_audio,
                    "duration": duration,
                    "codec": codec,
                }
                st.session_state.pop("mp3_output_info", None)

        info = st.session_state["mp3_input_info"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Source File", info["orig_name"], format_bytes(info["size"]))
        c2.metric("Duration", format_duration(info["duration"]))
        c3.metric(
            "Audio Track",
            f"Detected ({info['codec']})" if info["has_audio"] else "None Found",
        )

        if not info["has_audio"]:
            st.error(
                "❌ This MP4 video does not contain an audio track to extract. Please upload a video with sound."
            )
            return

        st.divider()
        bitrate_label = st.selectbox(
            "Select Output MP3 Bitrate",
            options=list(BITRATE_OPTIONS.keys()),
            index=1,  # Default 192 kbps
        )
        selected_bitrate = BITRATE_OPTIONS[bitrate_label]

        if st.button(
            f"🎵 Convert to MP3 ({selected_bitrate.replace('k', ' kbps')})",
            type="primary",
            use_container_width=True,
        ):
            workspace = get_workspace_dir("mp4_to_mp3")
            stem = sanitize_filename(Path(info["orig_name"]).stem, default="audio")
            output_filename = f"{stem}_{selected_bitrate}bps.mp3"
            output_path = workspace / output_filename

            progress_bar = st.progress(0, text="Starting FFmpeg audio extraction...")
            status_text = st.empty()

            ok, err_msg, elapsed = convert_mp4_to_mp3(
                ffmpeg_bin=ffmpeg_bin,
                input_path=Path(info["path"]),
                output_path=output_path,
                bitrate=selected_bitrate,
                duration=info["duration"],
                progress_bar=progress_bar,
                status_text=status_text,
            )

            if ok and output_path.is_file() and output_path.stat().st_size > 0:
                st.session_state["mp3_output_info"] = {
                    "path": str(output_path),
                    "name": output_filename,
                    "size": output_path.stat().st_size,
                    "bitrate": selected_bitrate.replace("k", " kbps"),
                    "elapsed": elapsed,
                }
            else:
                st.error(f"❌ Conversion failed:\n```\n{err_msg}\n```")

        out_info = st.session_state.get("mp3_output_info")
        if out_info and os.path.exists(out_info["path"]):
            out_path = Path(out_info["path"])
            st.success(
                f"✅ Converted **{out_info['name']}** ({out_info['bitrate']}) in "
                f"**{out_info['elapsed']:.1f}s**  |  Output Size: **{format_bytes(out_info['size'])}**"
            )
            st.audio(str(out_path), format="audio/mp3")

            with open(out_path, "rb") as f_stream:
                st.download_button(
                    label=f"⬇️ Download MP3 ({out_info['name']})",
                    data=f_stream,
                    file_name=out_info["name"],
                    mime="audio/mpeg",
                    type="primary",
                    use_container_width=True,
                )
    else:
        st.info("👆 Upload an MP4 video above to extract its audio as an MP3 file.")
