import os
import re
from pathlib import Path
from typing import Any, Dict

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

INSTAGRAM_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/(p|reel|reels|tv)/[\w\-]+",
    re.IGNORECASE,
)


def is_valid_instagram_url(url: str) -> bool:
    return bool(INSTAGRAM_URL_PATTERN.match((url or "").strip()))


def download_instagram_media(
    url: str,
    output_mode: str,
    mp3_bitrate: int,
    ffmpeg_bin: str,
    progress_bar,
    status_text,
) -> Dict[str, Any]:
    """
    Download a public Instagram Post or Reel as MP4 or extract its audio as MP3.
    Does not bypass login walls, privacy restrictions, or authentication controls.
    """
    yt_dlp = get_yt_dlp()
    workspace = get_workspace_dir("instagram")
    for old_file in workspace.glob("*"):
        try:
            old_file.unlink()
        except OSError:
            pass

    def _progress_hook(d: Dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total > 0:
                pct = min(92, int(round((downloaded / total) * 92)))
                progress_bar.progress(pct, text=f"Downloading Instagram media... {pct}%")
            status_text.caption(f"📥 Downloaded: **{format_bytes(downloaded)}**")
        elif status == "finished":
            progress_bar.progress(96, text="Processing media with FFmpeg...")

    outtmpl = str(workspace / "ig_media_%(id)s.%(ext)s")

    ydl_opts: Dict[str, Any] = {
        **get_ydl_base_opts(),
        "ffmpeg_location": ffmpeg_bin,
        "outtmpl": outtmpl,
        "progress_hooks": [_progress_hook],
    }

    if output_mode == "Video (MP4)":
        ydl_opts["format"] = "bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"
    else:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(mp3_bitrate),
            }
        ]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    progress_bar.progress(100, text="Complete! (100%)")
    status_text.empty()

    files = sorted(workspace.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise ValueError(
            "No downloadable video stream was found in this Instagram post (it may be an image-only post)."
        )

    final_file = files[0]
    title = info.get("title") or info.get("description") or f"instagram_{info.get('id', 'media')}"
    safe_name = sanitize_filename(title, default="instagram_media")
    ext = ".mp4" if output_mode == "Video (MP4)" else ".mp3"
    renamed_path = workspace / f"{safe_name}{ext}"
    if final_file != renamed_path:
        final_file.replace(renamed_path)

    return {
        "path": str(renamed_path),
        "name": renamed_path.name,
        "title": info.get("title") or "Instagram Reel / Video",
        "uploader": info.get("uploader") or info.get("channel") or "Instagram User",
        "duration": info.get("duration"),
        "size": renamed_path.stat().st_size,
        "mode": output_mode,
        "mime": "video/mp4" if output_mode == "Video (MP4)" else "audio/mpeg",
    }


def render_instagram_downloader() -> None:
    """Render the Instagram Post & Reel Downloader page."""
    yt_dlp = get_yt_dlp()
    st.header("📸 Instagram Video & Reel Downloader")
    st.markdown(
        "Download publicly accessible **Instagram Reels and Video Posts** as **MP4** "
        "or extract their audio as **MP3**."
    )
    st.caption(
        "🔒 *Privacy & Terms Notice: This tool only supports publicly accessible videos you are authorized to download. "
        "It does not bypass login screens, private accounts, or platform access controls.*"
    )

    ffmpeg_bin, _ = find_ffmpeg_binaries()
    if not ffmpeg_bin:
        st.error(
            "⚠️ **FFmpeg not found.** Please install FFmpeg to merge video/audio streams and extract MP3 files."
        )
        return

    url_input = st.text_input(
        "Instagram Post or Reel URL",
        placeholder="https://www.instagram.com/reel/...",
    )

    col1, col2 = st.columns(2)
    with col1:
        output_mode = st.radio(
            "Output Format",
            options=["Video (MP4)", "Audio Only (MP3)"],
            horizontal=True,
        )
    with col2:
        mp3_bitrate = 192
        if output_mode == "Audio Only (MP3)":
            bitrate_str = st.selectbox(
                "MP3 Audio Bitrate",
                options=["128 kbps", "192 kbps", "256 kbps"],
                index=1,
            )
            mp3_bitrate = int(bitrate_str.split()[0])
        else:
            st.info("Video will be saved in MP4 format with original audio.")

    if st.button("🚀 Fetch & Download Media", type="primary", use_container_width=True):
        st.session_state.pop("ig_result", None)
        cleaned_url = (url_input or "").strip()

        if not cleaned_url:
            st.warning("⚠️ Please enter an Instagram Post or Reel URL.")
        elif not is_valid_instagram_url(cleaned_url):
            st.error(
                "❌ Unsupported URL format. Please enter a direct Instagram Post or Reel link "
                "(e.g., `https://www.instagram.com/reel/...` or `https://www.instagram.com/p/...`)."
            )
        else:
            progress_bar = st.progress(0, text="Connecting to Instagram...")
            status_text = st.empty()
            try:
                result = download_instagram_media(
                    url=cleaned_url,
                    output_mode=output_mode,
                    mp3_bitrate=mp3_bitrate,
                    ffmpeg_bin=ffmpeg_bin,
                    progress_bar=progress_bar,
                    status_text=status_text,
                )
                st.session_state["ig_result"] = result
            except yt_dlp.utils.DownloadError as dl_err:
                progress_bar.empty()
                status_text.empty()
                err_str = str(dl_err).lower()
                if any(
                    kw in err_str
                    for kw in ["login", "private", "cookie", "rate-limit", "not available", "403", "401"]
                ):
                    st.error(
                        "🔒 **Content Restricted or Private:** This Instagram post requires authentication, belongs to a "
                        "private account, or is currently rate-limited by Instagram. In accordance with platform access "
                        "controls, private or login-protected content cannot be downloaded."
                    )
                elif "no video" in err_str or "there is no video" in err_str:
                    st.error(
                        "🖼️ **No Video Found:** This Instagram URL appears to be an image-only post rather than a video or Reel."
                    )
                else:
                    st.error(f"❌ Could not download Instagram media: `{dl_err}`")
            except Exception as exc:
                progress_bar.empty()
                status_text.empty()
                st.error(f"❌ Error processing Instagram URL: {exc}")

    ig_result = st.session_state.get("ig_result")
    if ig_result and os.path.exists(ig_result["path"]):
        out_path = Path(ig_result["path"])
        st.divider()
        st.success(
            f"✅ **{ig_result['title']}** by **{ig_result['uploader']}**  |  "
            f"Duration: **{format_duration(ig_result['duration'])}**  |  "
            f"Size: **{format_bytes(ig_result['size'])}**"
        )

        if ig_result["mode"] == "Video (MP4)":
            st.video(str(out_path))
        else:
            st.audio(str(out_path), format="audio/mp3")

        with open(out_path, "rb") as f_stream:
            st.download_button(
                label=f"⬇️ Download {ig_result['mode']} ({ig_result['name']})",
                data=f_stream,
                file_name=ig_result["name"],
                mime=ig_result["mime"],
                type="primary",
                use_container_width=True,
            )
