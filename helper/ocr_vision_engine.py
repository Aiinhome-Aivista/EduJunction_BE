"""Universal Database-Driven Vision OCR Engine for scanned curriculum documents, textbooks, and question banks.
100% Database-Driven: Retrieves Provider, Base URL, API Key, Model Name, and Temperature
from Admin Scenario Routing configuration ('vision_ocr' scenario). Zero hardcoding.
"""
import base64
import concurrent.futures
import io
import warnings
import requests

try:
    import pymupdf as fitz  # PyMuPDF modern import
except ImportError:
    import fitz  # Legacy fallback

from model.mistral_client import get_scenario_llm_config
from utils.logger import logger


def _ocr_single_page_gemini(api_key: str, model_name: str, image_bytes: bytes, prompt: str, page_num: int, total_pages: int) -> tuple[int, str]:
    """Processes a single page image with Gemini Vision using Admin DB credentials."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=model_name)

        image_part = {
            "mime_type": "image/png",
            "data": image_bytes
        }
        response = model.generate_content([image_part, prompt])
        if response and response.text:
            text_clean = response.text.strip()
            print(f"      [Vision OCR] Page {page_num}/{total_pages} digitized ({len(text_clean):,} chars)", flush=True)
            logger.info(f"Vision OCR completed for Page {page_num}/{total_pages}")
            return (page_num, text_clean)
    except Exception as e:
        print(f"      [Vision OCR] Page {page_num} warning: {e}", flush=True)
        logger.warning(f"Vision OCR failed for Page {page_num}: {e}")
    return (page_num, "")


def _ocr_single_page_http(base_url: str, api_key: str, model_name: str, image_bytes: bytes, prompt: str, temperature: float, timeout: int, page_num: int, total_pages: int) -> tuple[int, str]:
    """Processes a single page image with any OpenAI/Mistral/Custom Vision endpoint using Admin DB credentials."""
    try:
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        target_url = base_url.strip()

        # Build standard multimodal message payload
        headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": f"data:image/png;base64,{b64_img}"}
                    ]
                }
            ],
            "temperature": temperature if temperature is not None else 0.2
        }

        resp = requests.post(target_url, headers=headers, json=payload, timeout=timeout or 90)
        if resp.status_code == 200:
            data = resp.json()
            text_out = data["choices"][0]["message"]["content"].strip()
            print(f"      [Vision OCR] Page {page_num}/{total_pages} digitized ({len(text_out):,} chars)", flush=True)
            logger.info(f"Vision OCR completed for Page {page_num}/{total_pages}")
            return (page_num, text_out)
        else:
            print(f"      [Vision OCR] Page {page_num} HTTP {resp.status_code}: {resp.text[:140]}", flush=True)
            logger.warning(f"Vision OCR failed for Page {page_num}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"      [Vision OCR] Page {page_num} error: {e}", flush=True)
        logger.warning(f"Vision OCR failed for Page {page_num}: {e}")
    return (page_num, "")


def extract_scanned_pdf_with_vision(
    file_bytes: bytes,
    board: str = "General",
    class_grade: str = "Standard",
    subject: str = "General",
    max_pages: int = 20,
) -> str:
    """Extracts pedagogical text from scanned/image PDF pages using the Admin-assigned Vision OCR provider from database."""
    # 1. Fetch dynamic config assigned by Admin for 'vision_ocr'
    db_cfg = get_scenario_llm_config("vision_ocr")
    if not db_cfg:
        logger.warning("No LLM configuration assigned for 'vision_ocr' in database; Vision OCR skipped.")
        return ""

    provider = (db_cfg.get("provider") or "").lower().strip()
    api_key = db_cfg.get("api_key")
    base_url = db_cfg.get("base_url")
    model_name = db_cfg.get("model_name")
    temperature = db_cfg.get("temperature", 0.2)
    timeout = db_cfg.get("timeout", 90)

    # Validate essential parameters based on provider type
    if "gemini" in provider:
        if not api_key or not model_name:
            logger.warning(f"Incomplete Gemini configuration for 'vision_ocr' in database (API Key: {'Set' if api_key else 'Missing'}, Model: {model_name}).")
            return ""
    else:
        if not base_url or not model_name:
            logger.warning(f"Incomplete configuration for 'vision_ocr' in database (Base URL: {base_url}, Model: {model_name}).")
            return ""

    extracted_pages = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages)

        print(f"  • [VISION OCR ENGINE] Processing {pages_to_process} page(s) using Admin Config: Provider=[{provider.upper()}] | Model=[{model_name}] | Endpoint=[{base_url or 'Google SDK'}]...", flush=True)
        logger.info(f"Starting Fast Parallel Vision OCR for {pages_to_process} pages (Provider: {provider}, Model: {model_name}, Endpoint: {base_url})")

        pages_needing_ocr = []

        for page_idx in range(pages_to_process):
            page = doc[page_idx]
            page_text = page.get_text().strip()

            # If page already has rich digital text, keep it directly (0.01 sec)
            if len(page_text) > 80:
                extracted_pages.append((page_idx + 1, f"--- Page {page_idx + 1} ---\n{page_text}"))
            else:
                # Render high-res image for OCR
                pix = page.get_pixmap(dpi=140)
                img_bytes = pix.tobytes("png")
                prompt = f"""You are an elite academic curriculum digitization specialist for {board} {class_grade} ({subject}).
Transcribe ALL text, section headers, questions (Q1, Q2...), options, marks, tables, and formulas from this scanned page with 100% fidelity.
Preserve exact wording and structure. Output clean Markdown text only."""
                pages_needing_ocr.append((page_idx + 1, img_bytes, prompt))

        # Run OCR concurrently with ThreadPoolExecutor (max 4 parallel workers)
        if pages_needing_ocr:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                if "gemini" in provider:
                    future_to_page = {
                        executor.submit(_ocr_single_page_gemini, api_key, model_name, img_b, p_prompt, p_num, pages_to_process): p_num
                        for p_num, img_b, p_prompt in pages_needing_ocr
                    }
                else:
                    future_to_page = {
                        executor.submit(_ocr_single_page_http, base_url, api_key, model_name, img_b, p_prompt, temperature, timeout, p_num, pages_to_process): p_num
                        for p_num, img_b, p_prompt in pages_needing_ocr
                    }

                for future in concurrent.futures.as_completed(future_to_page):
                    p_num, text_res = future.result()
                    if text_res:
                        extracted_pages.append((p_num, f"--- Page {p_num} (Vision OCR) ---\n{text_res}"))

        doc.close()

        # Sort pages back into correct book page order
        extracted_pages.sort(key=lambda x: x[0])
        full_result = "\n\n".join(text for _, text in extracted_pages)
        print(f"  • [VISION OCR COMPLETED] Digitized {len(extracted_pages)} page(s) -> Total {len(full_result):,} characters extracted.", flush=True)
        return full_result

    except Exception as e:
        logger.error(f"Failed during scanned PDF Vision extraction: {e}", exc_info=True)
        return ""
