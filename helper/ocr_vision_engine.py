"""Gemini Vision OCR Engine for scanned curriculum documents, textbooks, and question banks.
Uses PyMuPDF (fitz) to render PDF pages into images and Gemini Vision to extract
text, chemical equations, mathematical formulas, tables, and diagrams.
"""
import io
try:
    import pymupdf as fitz  # PyMuPDF modern import
except ImportError:
    import fitz  # Legacy fallback
import concurrent.futures
from utils.config import config
from utils.logger import logger


def _ocr_single_page(model, image_part, prompt, page_num, total_pages):
    try:
        response = model.generate_content([image_part, prompt])
        if response and response.text:
            print(f"      [Vision OCR] Page {page_num}/{total_pages} extracted ({len(response.text.strip())} chars)", flush=True)
            logger.info(f"Vision OCR completed for Page {page_num}/{total_pages}")
            return (page_num, response.text.strip())
    except Exception as e:
        print(f"      [Vision OCR] Page {page_num} warning: {e}", flush=True)
        logger.warning(f"Vision OCR failed for Page {page_num}: {e}")
    return (page_num, "")


def extract_scanned_pdf_with_vision(
    file_bytes: bytes,
    board: str = "General",
    class_grade: str = "Standard",
    subject: str = "General",
    max_pages: int = 20,
) -> str:
    """Extracts rich pedagogical text from scanned/image PDF pages using parallel Gemini Vision AI.
    Preserves chemical equations, mathematical formulas, activities, and questions.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai package not installed; cannot perform Vision OCR.")
        return ""

    from model.mistral_client import _get_active_db_llm_config
    
    db_cfg = _get_active_db_llm_config()
    if not db_cfg or not db_cfg.get("api_key") or "gemini" not in db_cfg["provider"]:
        logger.warning("Active Gemini configuration not found in Admin Panel; Vision OCR skipped.")
        return ""
    
    api_key = db_cfg["api_key"]
    genai.configure(api_key=api_key)
    model_name = db_cfg.get("model_name") or "gemini-2.0-flash"
    model = genai.GenerativeModel(model_name=model_name)

    extracted_pages = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages)

        logger.info(f"Starting Fast Parallel Vision OCR for {pages_to_process} pages (Board: {board}, Class: {class_grade}, Subject: {subject})")

        pages_needing_ocr = []

        for page_idx in range(pages_to_process):
            page = doc[page_idx]
            page_text = page.get_text().strip()
            
            # If page already has rich digital text, keep it directly (0.01 sec)
            if len(page_text) > 80:
                extracted_pages.append((page_idx + 1, f"--- Page {page_idx + 1} ---\n{page_text}"))
            else:
                # Prepare image for OCR
                pix = page.get_pixmap(dpi=130)
                img_bytes = pix.tobytes("png")
                image_part = {
                    "mime_type": "image/png",
                    "data": img_bytes
                }
                prompt = f"""You are an elite academic textbook digitization specialist for {board} {class_grade} ({subject}).
Transcribe ALL text, headings, activities (e.g. Activity 1.1), formulas, and questions from this scanned page accurately.
Chemical Equations: Preserve symbols and reactions (e.g. 2Mg + O2 -> 2MgO).
Output clean, structured Markdown text only."""
                pages_needing_ocr.append((page_idx + 1, image_part, prompt))

        # Run OCR concurrently with ThreadPoolExecutor (max 5 parallel workers)
        if pages_needing_ocr:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_page = {
                    executor.submit(_ocr_single_page, model, img_part, prompt, p_num, pages_to_process): p_num
                    for p_num, img_part, prompt in pages_needing_ocr
                }
                for future in concurrent.futures.as_completed(future_to_page):
                    p_num, text_res = future.result()
                    if text_res:
                        extracted_pages.append((p_num, f"--- Page {p_num} (Vision OCR) ---\n{text_res}"))

        doc.close()

        # Sort pages back into correct book page order
        extracted_pages.sort(key=lambda x: x[0])
        return "\n\n".join(text for _, text in extracted_pages)

    except Exception as e:
        logger.error(f"Failed during scanned PDF Vision extraction: {e}", exc_info=True)
        return ""
