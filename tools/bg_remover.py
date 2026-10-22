import io
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps
from rembg import remove

from tools.utils import format_bytes, sanitize_filename


@st.cache_data(show_spinner=False, max_entries=10)
def remove_image_background(image_bytes: bytes, alpha_matting: bool) -> bytes:
    """Run local background removal using rembg (CPU / ONNX Runtime)."""
    return remove(image_bytes, alpha_matting=alpha_matting)


def render_bg_remover() -> None:
    """Render the Image Background Remover page."""
    st.header("✂️ Image Background Remover")
    st.markdown(
        "Automatically remove the background from **PNG, JPG, and JPEG** images locally "
        "on your computer using **rembg** and download a clean, **transparent PNG**."
    )

    uploaded_img = st.file_uploader(
        "Upload an Image (PNG, JPG, JPEG)",
        type=["png", "jpg", "jpeg"],
    )

    alpha_matting = st.checkbox(
        "Enable Fine Edge Alpha Matting (Better for hair, fur & complex edges)",
        value=False,
    )

    if uploaded_img is not None:
        try:
            raw_bytes = uploaded_img.getvalue()
            orig_img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes)))
            # Normalize orientation into bytes for rembg
            norm_buf = io.BytesIO()
            orig_img.save(norm_buf, format="PNG")
            normalized_bytes = norm_buf.getvalue()
        except Exception as img_err:
            st.error(f"❌ Could not open uploaded image: {img_err}")
            return

        col_before, col_after = st.columns(2)

        with col_before:
            st.subheader("🖼️ Before (Original)")
            st.image(
                orig_img,
                caption=f"{uploaded_img.name} ({orig_img.width}×{orig_img.height})",
                use_container_width=True,
            )

        with col_after:
            st.subheader("✨ After (Background Removed)")
            with st.spinner("Removing image background locally (first run may download the local rembg model)..."):
                try:
                    output_png_bytes = remove_image_background(
                        normalized_bytes, alpha_matting=alpha_matting
                    )
                    result_img = Image.open(io.BytesIO(output_png_bytes))
                except Exception as rem_err:
                    st.error(f"❌ Background removal failed: {rem_err}")
                    return

            st.image(
                result_img,
                caption=f"Transparent PNG ({result_img.width}×{result_img.height} — {format_bytes(len(output_png_bytes))})",
                use_container_width=True,
            )

            stem = sanitize_filename(Path(uploaded_img.name).stem, default="image")
            out_filename = f"{stem}_no_bg.png"

            st.download_button(
                label=f"⬇️ Download Transparent PNG ({out_filename})",
                data=output_png_bytes,
                file_name=out_filename,
                mime="image/png",
                type="primary",
                use_container_width=True,
            )
    else:
        st.info("👆 Upload a PNG, JPG, or JPEG image above to remove its background.")
