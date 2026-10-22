from typing import Dict, List

import streamlit as st

from tools.bg_remover import render_bg_remover
from tools.image_to_pdf import render_image_to_pdf
from tools.instagram_downloader import render_instagram_downloader
from tools.mp4_to_mp3 import render_mp4_to_mp3
from tools.utils import cleanup_all_workspaces, find_ffmpeg_binaries
from tools.youtube_downloader import render_youtube_downloader

# ---------------------------------------------------------------------------
# Page Configuration & Global Styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Media Tools Studio",
    page_icon="🧰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 2.5rem;
    }
    .tool-card {
        background: rgba(128, 128, 128, 0.07);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 0.85rem;
        padding: 1.25rem 1.35rem;
        margin-bottom: 0.75rem;
        min-height: 175px;
    }
    .tool-card h4 {
        margin-top: 0;
        margin-bottom: 0.45rem;
    }
    .tool-card p {
        font-size: 0.94rem;
        opacity: 0.88;
        margin-bottom: 0.5rem;
    }
    div[data-testid="stMetric"] {
        background: rgba(128, 128, 128, 0.07);
        border: 1px solid rgba(128, 128, 128, 0.18);
        padding: 0.75rem 1rem;
        border-radius: 0.65rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Navigation Registry
# ---------------------------------------------------------------------------
PAGES: List[Dict[str, str]] = [
    {
        "id": "Home",
        "nav_label": "🏠 Home Dashboard",
        "title": "Home Dashboard",
        "icon": "🏠",
        "desc": "Overview of all five local media utilities and setup guide.",
    },
    {
        "id": "YouTube Downloader",
        "nav_label": "📺 YouTube Downloader",
        "title": "YouTube Video Downloader",
        "icon": "📺",
        "desc": "Download YouTube videos from 360p up to 8K MP4 or extract 128/256 kbps MP3 audio.",
    },
    {
        "id": "Instagram Downloader",
        "nav_label": "📸 Instagram Downloader",
        "title": "Instagram Downloader",
        "icon": "📸",
        "desc": "Save public Instagram Reels and video posts as MP4 or extract audio as MP3.",
    },
    {
        "id": "MP4 to MP3 Converter",
        "nav_label": "🎵 MP4 to MP3 Converter",
        "title": "MP4 to MP3 Converter",
        "icon": "🎵",
        "desc": "Convert uploaded MP4 videos to MP3 audio at 128 kbps, 192 kbps, or 256 kbps.",
    },
    {
        "id": "Image to PDF Converter",
        "nav_label": "📄 Image to PDF Converter",
        "title": "Image to PDF Converter",
        "icon": "📄",
        "desc": "Convert single or multiple JPG, JPEG, PNG, and WEBP images into one PDF document.",
    },
    {
        "id": "Image Background Remover",
        "nav_label": "✂️ Background Remover",
        "title": "Image Background Remover",
        "icon": "✂️",
        "desc": "Remove backgrounds from PNG, JPG, and JPEG images locally using rembg.",
    },
]

PAGE_IDS = [p["id"] for p in PAGES]
ID_TO_LABEL = {p["id"]: p["nav_label"] for p in PAGES}

if "active_page" not in st.session_state or st.session_state["active_page"] not in PAGE_IDS:
    st.session_state["active_page"] = "Home"


def switch_page(page_id: str) -> None:
    st.session_state["active_page"] = page_id


# ---------------------------------------------------------------------------
# Sidebar Navigation & System Status
# ---------------------------------------------------------------------------
ffmpeg_bin, _ = find_ffmpeg_binaries()

with st.sidebar:
    st.title("🧰 Media Tools")
    st.caption("All-in-One Local Media Suite")

    selected_page = st.radio(
        "Navigation",
        options=PAGE_IDS,
        index=PAGE_IDS.index(st.session_state["active_page"]),
        format_func=lambda pid: ID_TO_LABEL[pid],
        label_visibility="collapsed",
    )
    if selected_page != st.session_state["active_page"]:
        st.session_state["active_page"] = selected_page
        st.rerun()

    st.divider()
    st.subheader("🖥️ System Status")
    if ffmpeg_bin:
        st.success("✅ FFmpeg Ready (Local Engine)")
    else:
        st.error("⚠️ FFmpeg Not Detected")

    if st.button("🧹 Clean Temp Files", use_container_width=True):
        cleanup_all_workspaces()
        st.toast("Temporary workspace files cleaned up!", icon="🧹")
        st.rerun()


# ---------------------------------------------------------------------------
# Home Dashboard Page
# ---------------------------------------------------------------------------
def render_home_page() -> None:
    st.title("🧰 Media Tools Web Application")
    st.markdown(
        "Welcome to **Media Tools Studio** — a complete, modular suite of **five local media utilities** "
        "powered by **Python**, **Streamlit**, **FFmpeg**, **yt-dlp**, **Pillow**, and **rembg**. "
        "All processing happens locally on your machine with **zero paid APIs or cloud services**."
    )

    st.subheader("🚀 Select a Tool to Get Started")
    tool_pages = PAGES[1:]  # All 5 tools

    row1 = st.columns(3)
    for col, tool in zip(row1, tool_pages[:3]):
        with col:
            st.markdown(
                f"""
                <div class="tool-card">
                    <h4>{tool['icon']} {tool['title']}</h4>
                    <p>{tool['desc']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                f"Open {tool['title']} ➔",
                key=f"btn_{tool['id']}",
                on_click=switch_page,
                args=(tool["id"],),
                type="primary",
                use_container_width=True,
            )

    row2 = st.columns(3)
    for col, tool in zip(row2[:2], tool_pages[3:]):
        with col:
            st.markdown(
                f"""
                <div class="tool-card">
                    <h4>{tool['icon']} {tool['title']}</h4>
                    <p>{tool['desc']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                f"Open {tool['title']} ➔",
                key=f"btn_{tool['id']}",
                on_click=switch_page,
                args=(tool["id"],),
                type="primary",
                use_container_width=True,
            )

    st.divider()
    with st.expander("🪟 Windows Setup & FFmpeg Installation Guide", expanded=not bool(ffmpeg_bin)):
        st.markdown(
            """
            ### 1. Installing FFmpeg on Windows & Configuring `PATH`
            - **Option A — Windows Package Manager (Winget, recommended on Windows 10/11):**
              ```powershell
              winget install Gyan.FFmpeg
              ```
              *Restart your terminal after installation so Windows updates your `PATH`.*
            - **Option B — Manual Installation & PATH Setup:**
              1. Download `ffmpeg-release-essentials.zip` from [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/).
              2. Extract the archive to `C:\\ffmpeg` so that `C:\\ffmpeg\\bin\\ffmpeg.exe` exists.
              3. Press **Win + S**, search for **Edit the system environment variables**, and click **Environment Variables**.
              4. Under **System variables**, select **Path** → **Edit** → **New**, add `C:\\ffmpeg\\bin`, and click **OK**.
              5. Verify in a new PowerShell window with `ffmpeg -version`.
            - **Automatic Fallback:** `imageio-ffmpeg` in `requirements.txt` also supplies a bundled FFmpeg binary automatically if system FFmpeg is not found on `PATH`.

            ### 2. Installing Dependencies & Running the Application
            ```powershell
            python -m pip install -r requirements.txt
            python -m streamlit run main.py
            ```
            """
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
current_page = st.session_state["active_page"]

if current_page == "Home":
    render_home_page()
elif current_page == "YouTube Downloader":
    render_youtube_downloader()
elif current_page == "Instagram Downloader":
    render_instagram_downloader()
elif current_page == "MP4 to MP3 Converter":
    render_mp4_to_mp3()
elif current_page == "Image to PDF Converter":
    render_image_to_pdf()
elif current_page == "Image Background Remover":
    render_bg_remover()