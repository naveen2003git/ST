import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import streamlit as st

from tools.utils import (
    find_ffmpeg_binaries,
    format_bytes,
    format_duration,
    get_workspace_dir,
    get_ydl_base_opts,
    get_yt_dlp,
    sanitize_filename,
)

# Target resolution tiers mapped to (target_height, display_label, format_notes)
VIDEO_RESOLUTIONS: Dict[str, Tuple[int, str, Set[str]]] = {
    "360p": (360, "360p (SD)", {"360p", "360p60"}),
    "480p": (480, "480p (SD)", {"480p", "480p60"}),
    "720p": (720, "720p (HD)", {"720p", "720p60"}),
    "1080p": (1080, "1080p (Full HD)", {"1080p", "1080p60"}),
    "2K": (1440, "2K (1440p QHD)", {"1440p", "1440p60", "2k"}),
    "4K": (2160, "4K (2160p UHD)", {"2160p", "2160p60", "4k"}),
    "8K": (4320, "8K (4320p FUHD)", {"4320p", "4320p60", "8k"}),
}

AUDIO_BITRATES: Dict[str, int] = {
    "128 kbps": 128,
    "256 kbps": 256,
}

YOUTUBE_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|embed/|live/)|youtu\.be/)[\w\-]+",
    re.IGNORECASE,
)


def is_valid_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_PATTERN.match((url or "").strip()))


def extract_youtube_info(url: str) -> Dict[str, Any]:
    """Fetch YouTube video metadata and format list without downloading."""
    yt_dlp = get_yt_dlp()
    ydl_opts = {
        **get_ydl_base_opts(),
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info


def analyze_available_formats(info: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """
    Inspect all yt-dlp formats and determine which of our target resolutions
    (360p, 480p, 720p, 1080p, 2K, 4K, 8K) and audio streams are available.
    """
    formats = info.get("formats") or []
    available_res: Dict[str, Dict[str, Any]] = {}
    has_audio_stream = False

    for fmt in formats:
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        if acodec and acodec != "none":
            has_audio_stream = True

        if not vcodec or vcodec == "none":
            continue

        height = fmt.get("height") or 0
        width = fmt.get("width") or 0
        short_edge = min(width, height) if (width and height) else height
        note = str(fmt.get("format_note") or "").lower()
        fps = fmt.get("fps") or 30
        filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        ext = fmt.get("ext") or "mp4"

        for res_key, (target_h, label, note_set) in VIDEO_RESOLUTIONS.items():
            if height == target_h or short_edge == target_h or note in note_set:
                existing = available_res.get(res_key)
                if not existing or (filesize > existing.get("filesize", 0)):
                    available_res[res_key] = {
                        "Resolution": res_key,
                        "Label": label,
                        "Dimensions": f"{width}×{height}" if width and height else f"{target_h}p",
                        "FPS": int(round(fps)) if fps else 30,
                        "Codec": vcodec.split(".")[0],
                        "Container": ext.upper(),
                        "Est. Video Size": format_bytes(filesize) if filesize else "Variable",
                        "filesize": filesize,
                        "height": height or target_h,
                    }

    return available_res, has_audio_stream


def download_youtube_media(
    url: str,
    title: str,
    mode: str,
    selected_res: Optional[str],
    matched_height: Optional[int],
    selected_bitrate: Optional[int],
    ffmpeg_bin: str,
    progress_bar,
    status_text,
) -> Path:
    """Download and merge YouTube video or extract MP3 audio using yt-dlp and FFmpeg."""
    yt_dlp = get_yt_dlp()
    workspace = get_workspace_dir("youtube")
    for old_file in workspace.glob("*"):
        try:
            old_file.unlink()
        except OSError:
            pass

    safe_title = sanitize_filename(title, default="youtube_media")

    def _progress_hook(d: Dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            if total > 0:
                pct = min(95, int(round((downloaded / total) * 95)))
                progress_bar.progress(pct, text=f"Downloading stream... {pct}%")
            status_text.caption(
                f"📥 Downloaded: **{format_bytes(downloaded)}** / **{format_bytes(total)}**  |  "
                f"⚡ Speed: **{format_bytes(speed)}/s**"
            )
        elif status == "finished":
            progress_bar.progress(97, text="Merging / processing streams with FFmpeg...")
            status_text.caption("🔧 Running FFmpeg post-processing...")

    common_opts: Dict[str, Any] = {
        **get_ydl_base_opts(),
        "ffmpeg_location": ffmpeg_bin,
        "progress_hooks": [_progress_hook],
    }

    if mode == "Video (MP4)":
        assert selected_res is not None and matched_height is not None
        outtmpl = str(workspace / f"{safe_title}_{selected_res}.%(ext)s")
        fmt_selector = (
            f"bestvideo[height={matched_height}]+bestaudio/"
            f"best[height={matched_height}]/"
            f"bestvideo[width={matched_height}]+bestaudio/"
            f"best[width={matched_height}]"
        )
        ydl_opts = {
            **common_opts,
            "format": fmt_selector,
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
        }
    else:
        assert selected_bitrate is not None
        outtmpl = str(workspace / f"{safe_title}_{selected_bitrate}kbps.%(ext)s")
        ydl_opts = {
            **common_opts,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(selected_bitrate),
                }
            ],
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    progress_bar.progress(100, text="Download complete! (100%)")
    status_text.empty()

    files = sorted(workspace.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("Download finished, but the output file could not be located.")
    return files[0]


def render_youtube_downloader() -> None:
    """Render the YouTube Video & Audio Downloader page."""
    yt_dlp = get_yt_dlp()
    st.header("📺 YouTube Video & Audio Downloader")
    st.markdown(
        "Download YouTube videos in **360p, 480p, 720p, 1080p, 2K, 4K, or 8K** (MP4) "
        "or extract high-quality **MP3 audio** at **128 kbps** or **256 kbps** using **yt-dlp** and **FFmpeg**."
    )
    st.caption(
        "⚖️ *Please respect copyright and YouTube's Terms of Service. Only download videos you own or are authorized to download.*"
    )

    ffmpeg_bin, _ = find_ffmpeg_binaries()
    if not ffmpeg_bin:
        st.error(
            "⚠️ **FFmpeg not found.** FFmpeg is required to merge high-resolution YouTube video/audio streams and convert MP3 audio. "
            "Please check the Windows installation instructions on the Home page."
        )
        return

    url_col, btn_col = st.columns([4, 1])
    with url_col:
        url_input = st.text_input(
            "YouTube Video URL",
            placeholder="https://www.youtube.com/watch?v=...",
            label_visibility="collapsed",
        )
    with btn_col:
        fetch_clicked = st.button(
            "🔍 Check Formats", type="primary", use_container_width=True
        )

    if fetch_clicked:
        st.session_state.pop("yt_downloaded_file", None)
        if not is_valid_youtube_url(url_input):
            st.error(
                "❌ Please enter a valid YouTube video or Shorts URL (e.g., `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`)."
            )
            st.session_state.pop("yt_info", None)
        else:
            with st.spinner("Fetching video metadata and inspecting available resolutions..."):
                try:
                    info = extract_youtube_info(url_input.strip())
                    avail_res, has_audio = analyze_available_formats(info)
                    st.session_state["yt_url"] = url_input.strip()
                    st.session_state["yt_info"] = {
                        "title": info.get("title", "YouTube Video"),
                        "uploader": info.get("uploader", "Unknown Channel"),
                        "duration": info.get("duration"),
                        "thumbnail": info.get("thumbnail"),
                        "view_count": info.get("view_count"),
                        "available_res": avail_res,
                        "has_audio": has_audio,
                    }
                except yt_dlp.utils.DownloadError as dl_err:
                    st.session_state.pop("yt_info", None)
                    st.error(
                        f"❌ Unable to access this YouTube video. It may be private, age-restricted, or unavailable.\n\n**Details:** `{dl_err}`"
                    )
                except Exception as exc:
                    st.session_state.pop("yt_info", None)
                    st.error(f"❌ Error inspecting YouTube URL: {exc}")

    yt_info = st.session_state.get("yt_info")
    if yt_info:
        st.divider()
        meta_col1, meta_col2 = st.columns([1, 2])
        with meta_col1:
            if yt_info.get("thumbnail"):
                st.image(yt_info["thumbnail"], use_container_width=True)
        with meta_col2:
            st.subheader(yt_info["title"])
            st.markdown(
                f"**Channel:** {yt_info['uploader']}  |  "
                f"**Duration:** {format_duration(yt_info['duration'])}"
            )

            avail_res: Dict[str, Dict[str, Any]] = yt_info["available_res"]
            if avail_res:
                badges = "  ".join(
                    f"`✅ {res} ({avail_res[res]['Dimensions']})`"
                    for res in VIDEO_RESOLUTIONS
                    if res in avail_res
                )
                st.markdown(f"**Available Video Resolutions:** {badges}")
            else:
                st.warning("No standard video resolutions detected for this URL.")

            with st.expander("📋 View Detailed Available Formats Table", expanded=False):
                table_rows = []
                for res_key, (target_h, label, _) in VIDEO_RESOLUTIONS.items():
                    if res_key in avail_res:
                        item = avail_res[res_key]
                        table_rows.append(
                            {
                                "Resolution": label,
                                "Status": "✅ Available",
                                "Dimensions": item["Dimensions"],
                                "FPS": str(item["FPS"]),
                                "Codec": item["Codec"],
                                "Est. Stream Size": item["Est. Video Size"],
                            }
                        )
                    else:
                        table_rows.append(
                            {
                                "Resolution": label,
                                "Status": "❌ Unavailable",
                                "Dimensions": "—",
                                "FPS": "—",
                                "Codec": "—",
                                "Est. Stream Size": "—",
                            }
                        )
                st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.divider()
        opt_col1, opt_col2 = st.columns(2)
        with opt_col1:
            dl_mode = st.radio(
                "Download Format Type",
                options=["Video (MP4)", "Audio Only (MP3)"],
                horizontal=True,
            )

        selected_res: Optional[str] = None
        selected_bitrate: Optional[int] = None
        is_selection_available = True

        with opt_col2:
            if dl_mode == "Video (MP4)":
                default_idx = 3 if "1080p" in avail_res else 0
                selected_res = st.selectbox(
                    "Select Video Resolution (360p – 8K)",
                    options=list(VIDEO_RESOLUTIONS.keys()),
                    index=default_idx,
                    format_func=lambda r: (
                        f"{VIDEO_RESOLUTIONS[r][1]} — {'✅ Available' if r in avail_res else '❌ Unavailable'}"
                    ),
                )
                if selected_res not in avail_res:
                    is_selection_available = False
                    avail_list_str = (
                        ", ".join(r for r in VIDEO_RESOLUTIONS if r in avail_res)
                        or "None"
                    )
                    st.error(
                        f"❌ **{VIDEO_RESOLUTIONS[selected_res][1]}** is not available for this video. "
                        f"Please select one of the available resolutions: **{avail_list_str}**."
                    )
            else:
                bitrate_label = st.selectbox(
                    "Select Audio Bitrate (MP3)",
                    options=list(AUDIO_BITRATES.keys()),
                    index=1,
                )
                selected_bitrate = AUDIO_BITRATES[bitrate_label]
                if not yt_info.get("has_audio"):
                    is_selection_available = False
                    st.error("❌ No audio stream was found for this YouTube video.")

        if st.button(
            f"⬇️ Prepare {'Video (' + selected_res + ')' if dl_mode == 'Video (MP4)' else 'MP3 Audio (' + str(selected_bitrate) + ' kbps)'}",
            type="primary",
            disabled=not is_selection_available,
            use_container_width=True,
        ):
            progress_bar = st.progress(0, text="Initializing download...")
            status_text = st.empty()
            try:
                matched_h = (
                    avail_res[selected_res]["height"]
                    if (selected_res and selected_res in avail_res)
                    else None
                )
                output_file = download_youtube_media(
                    url=st.session_state["yt_url"],
                    title=yt_info["title"],
                    mode=dl_mode,
                    selected_res=selected_res,
                    matched_height=matched_h,
                    selected_bitrate=selected_bitrate,
                    ffmpeg_bin=ffmpeg_bin,
                    progress_bar=progress_bar,
                    status_text=status_text,
                )
                st.session_state["yt_downloaded_file"] = {
                    "path": str(output_file),
                    "name": output_file.name,
                    "mime": "video/mp4" if dl_mode == "Video (MP4)" else "audio/mpeg",
                    "mode": dl_mode,
                    "size": output_file.stat().st_size,
                }
            except Exception as dl_exc:
                st.error(f"❌ Download failed: {dl_exc}")

        dl_result = st.session_state.get("yt_downloaded_file")
        if dl_result and os.path.exists(dl_result["path"]):
            result_path = Path(dl_result["path"])
            st.success(
                f"✅ Ready to save: **{dl_result['name']}** ({format_bytes(dl_result['size'])})"
            )
            if dl_result["mode"] == "Video (MP4)":
                st.video(str(result_path))
            else:
                st.audio(str(result_path), format="audio/mp3")

            with open(result_path, "rb") as f_stream:
                st.download_button(
                    label=f"💾 Save {dl_result['name']} to Computer",
                    data=f_stream,
                    file_name=dl_result["name"],
                    mime=dl_result["mime"],
                    type="primary",
                    use_container_width=True,
                )
