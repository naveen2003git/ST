import io
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st
from PIL import Image, ImageOps

from tools.utils import format_bytes, sanitize_filename

PAGE_SIZES_PX_AT_150_DPI: Dict[str, Tuple[int, int]] = {
    "Fit to Image (Preserve Exact Original Dimensions)": (0, 0),
    "A4 Page (210 × 297 mm — Auto Orientation, Preserves Proportions)": (1240, 1754),
    "US Letter (8.5 × 11 in — Auto Orientation, Preserves Proportions)": (1275, 1650),
}


def prepare_image_for_pdf(
    raw_bytes: bytes,
    page_size: Tuple[int, int],
    margin_px: int,
) -> Image.Image:
    """
    Open an image, apply EXIF orientation, composite any transparency onto white,
    and optionally center it on a standard page while strictly preserving proportions.
    """
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = ImageOps.exif_transpose(img)

        # Composite transparent images (RGBA, LA, P with transparency) onto white
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            rgb_img = Image.alpha_composite(white_bg, rgba).convert("RGB")
        else:
            rgb_img = img.convert("RGB")

    page_w, page_h = page_size
    if page_w == 0 or page_h == 0:
        return rgb_img

    # Match page orientation (landscape vs portrait) to image orientation
    if rgb_img.width > rgb_img.height and page_w < page_h:
        page_w, page_h = page_h, page_w

    avail_w = max(50, page_w - 2 * margin_px)
    avail_h = max(50, page_h - 2 * margin_px)

    # Scale image proportionally to fit inside available page area without distortion
    contained = ImageOps.contain(rgb_img, (avail_w, avail_h), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    offset_x = (page_w - contained.width) // 2
    offset_y = (page_h - contained.height) // 2
    canvas.paste(contained, (offset_x, offset_y))
    return canvas


def build_pdf_bytes(
    uploaded_files: List,
    page_size: Tuple[int, int],
    margin_px: int,
) -> bytes:
    """Convert one or multiple uploaded images into a single PDF byte stream."""
    processed_pages: List[Image.Image] = []
    for f in uploaded_files:
        f.seek(0)
        raw = f.read()
        page_img = prepare_image_for_pdf(raw, page_size=page_size, margin_px=margin_px)
        processed_pages.append(page_img)

    if not processed_pages:
        raise ValueError("No valid images provided.")

    pdf_buffer = io.BytesIO()
    first_page, *additional_pages = processed_pages
    first_page.save(
        pdf_buffer,
        format="PDF",
        resolution=150.0,
        save_all=True,
        append_images=additional_pages,
    )
    for page in processed_pages:
        page.close()

    return pdf_buffer.getvalue()


def render_image_to_pdf() -> None:
    """Render the Image to PDF Converter page."""
    st.header("📄 Image to PDF Converter")
    st.markdown(
        "Upload **one or multiple images** (`JPG`, `JPEG`, `PNG`, `WEBP`) and combine them "
        "into a single crisp **PDF document** while preserving original image proportions."
    )

    uploaded_images = st.file_uploader(
        "Upload Image(s) (JPG, JPEG, PNG, WEBP)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    if uploaded_images:
        st.subheader(f"🖼️ Uploaded Images ({len(uploaded_images)} page{'s' if len(uploaded_images) > 1 else ''})")

        cols = st.columns(min(4, len(uploaded_images)))
        for idx, up_file in enumerate(uploaded_images):
            col = cols[idx % len(cols)]
            with col:
                try:
                    up_file.seek(0)
                    with Image.open(up_file) as preview_img:
                        w, h = preview_img.size
                        st.image(
                            preview_img,
                            caption=f"Page {idx + 1}: {up_file.name} ({w}×{h})",
                            use_container_width=True,
                        )
                except Exception as img_err:
                    st.error(f"Invalid image `{up_file.name}`: {img_err}")

        st.divider()
        opt_col1, opt_col2 = st.columns([2, 1])
        with opt_col1:
            layout_label = st.selectbox(
                "PDF Page Layout",
                options=list(PAGE_SIZES_PX_AT_150_DPI.keys()),
                index=0,
            )
            page_size = PAGE_SIZES_PX_AT_150_DPI[layout_label]
        with opt_col2:
            default_name = (
                sanitize_filename(Path(uploaded_images[0].name).stem, default="images")
                if len(uploaded_images) == 1
                else "combined_images"
            )
            pdf_filename_stem = st.text_input("Output PDF Filename", value=default_name)
            margin_px = 40 if page_size != (0, 0) else 0

        if st.button("📄 Generate PDF Document", type="primary", use_container_width=True):
            with st.spinner("Converting images into PDF..."):
                try:
                    pdf_bytes = build_pdf_bytes(
                        uploaded_files=uploaded_images,
                        page_size=page_size,
                        margin_px=margin_px,
                    )
                    safe_out_name = f"{sanitize_filename(pdf_filename_stem, default='document')}.pdf"
                    st.session_state["pdf_output"] = {
                        "bytes": pdf_bytes,
                        "name": safe_out_name,
                        "pages": len(uploaded_images),
                        "size": len(pdf_bytes),
                    }
                except Exception as exc:
                    st.error(f"❌ Failed to generate PDF: {exc}")

        pdf_output = st.session_state.get("pdf_output")
        if pdf_output:
            st.success(
                f"✅ Created **{pdf_output['name']}** with **{pdf_output['pages']} page(s)** "
                f"({format_bytes(pdf_output['size'])})"
            )
            st.download_button(
                label=f"⬇️ Download PDF ({pdf_output['name']})",
                data=pdf_output["bytes"],
                file_name=pdf_output["name"],
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
    else:
        st.info("👆 Select one or more JPG, JPEG, PNG, or WEBP images above to convert them into a PDF.")
