"""Curriculum & Question Paper Ingestion Pipeline Engine.
Executes the 5-step automated processing pipeline for Textbooks and Old Question Papers:
1. Data Read (extract text from PDF/DOCX)
2. Short Contextual Analysis (AI overview & chapter/paper classification)
3. Question Detection & Extraction (High-yield textbook synthesis vs PYQ extraction)
4. JSON Schema Preparation (strict formatting for question_master)
5. Database Storage (Insertion into question_master, documents, document_chunks & ChromaDB)
"""
import ast
import concurrent.futures
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import vector_db
from helper import document_processor, embedding_engine
from model import mistral_client
from model.models import Document, DocumentChunk, Runbook
from utils.errors import ValidationError
from utils.logger import logger


# ANSI Color Codes for terminal prints
class TermColors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


VISUAL_SUBJECTS = {
    "science", "physics", "chemistry", "biology", "botany", "zoology",
    "mathematics", "math", "maths",
    "social science", "geography", "history", "economics",
    "computer science", "it", "computer applications",
    "physical education", "sports", "yoga", "environmental studies", "evs"
}


def is_diagram_subject(subject_name: str) -> bool:
    """Returns True only if the subject has legitimate exam diagram requirements."""
    sub = str(subject_name or "").lower().strip()
    return any(v in sub for v in VISUAL_SUBJECTS)


# Regex patterns that identify genuine question requirements for diagrams / figures / tables / charts
STRICT_FIGURE_PATTERNS = [
    r"\b(?:refer to|study|observe|look at|see)\s+(?:the\s+)?(?:figure|fig\.?|diagram|circuit|ray diagram|map|graph|chart|table|setup|apparatus)\b",
    r"\b(?:in|from|according to|based on)\s+(?:the\s+)?(?:adjoining|given|above|below|following|observations in)?\s*(?:figure|fig\.?|diagram|circuit|ray diagram|map|graph|chart|table|setup|apparatus|data table)\b",
    r"\b(?:figure|fig\.?)\s+\d+(?:\.\d+)?\b",
    r"\b(?:table|chart|grid)\s+\d+(?:\.\d+)?\b",
    r"\b(?:labeled|shaded|marked)\s+(?:part|region|area|component|zone)\b",
    r"\bidentify\s+(?:the\s+)?(?:part|structure|organ|circuit|apparatus)\s+(?:labeled|marked)\b",
    r"\b(?:circuit|ray)\s+diagram\s+(?:shows|illustrates|represents|given)\b",
    r"\b(?:pie\s*chart|bar\s*graph|flow\s*chart|observation\s*table)\s+(?:shows|indicates|given)\b",
    r"\b(?:experimental\s+setup|given\s+apparatus|experimental\s+arrangement)\b",
]

# False positive terms where 'figure' or 'diagram' is used metaphorically or non-visually
NON_VISUAL_FIGURE_EXCLUSIONS = [
    r"\bfigure\s+out\b",
    r"\b(?:historical|prominent|central|political|key|public|national|leading|literary)\s+figures?\b",
    r"\bfigure\s+of\s+speech\b",
]


def is_diagram_referenced_in_question(question_text: str, norm_dict: dict = None) -> bool:
    """Checks if a question strictly references an embedded figure, diagram, table, chart, or map."""
    if norm_dict and (norm_dict.get("figure_ref") or norm_dict.get("has_visual") or norm_dict.get("image_url")):
        return True
    if not question_text:
        return False
    q_low = question_text.lower()
    # Check exclusions first
    if any(re.search(excl, q_low) for excl in NON_VISUAL_FIGURE_EXCLUSIONS):
        return False
    return any(re.search(pat, q_low) for pat in STRICT_FIGURE_PATTERNS)


def print_extraction_quality_metrics(
    raw_text_chars: int,
    cleaned_text_chars: int,
    diag_metrics: dict,
    linked_diagrams_count: int,
    total_questions: int,
    filename: str = ""
):
    """Prints a clear, informative quality audit in the terminal for text and diagram extraction yield."""
    text_coverage_pct = round((cleaned_text_chars / max(raw_text_chars, 1)) * 100, 1) if raw_text_chars > 0 else 100.0
    total_raw_imgs = diag_metrics.get("total_raw_images", 0)
    valid_diags = diag_metrics.get("valid_diagrams", 0)
    page_scans_rej = diag_metrics.get("scanned_pages_rejected", 0)
    icons_filtered = diag_metrics.get("icons_filtered", 0)
    diag_yield_pct = diag_metrics.get("yield_pct", 0.0)

    print(f"\n{TermColors.BOLD}{TermColors.CYAN}══════════════════════════════════════════════════════════════════════════════{TermColors.END}")
    print(f"📊 {TermColors.BOLD}[EXTRACTION QUALITY & DIAGRAM YIELD AUDIT]{TermColors.END} {f'({filename})' if filename else ''}")
    print(f"   ▶ Extracted Text Coverage   : {TermColors.BOLD}{cleaned_text_chars:,}{TermColors.END} chars ({text_coverage_pct}% of raw text retained)")
    print(f"   ▶ Embedded Raw Images in Doc: {total_raw_imgs}")
    print(f"   ▶ Valid Academic Diagrams   : {TermColors.BOLD}{valid_diags}{TermColors.END} ({diag_yield_pct}% valid yield)")
    if total_raw_imgs > 0:
        print(f"      ↳ Filtered Full-Page Scans : {page_scans_rej} (Prevented scanned text pages from mislinking)")
        print(f"      ↳ Filtered Icons/Banners   : {icons_filtered} (Decorative icons/banners filtered out)")
    print(f"   ▶ Questions with Diagram    : {TermColors.BOLD}{linked_diagrams_count}{TermColors.END} / {total_questions} (Strict context-verified matching)")
    print(f"{TermColors.BOLD}{TermColors.CYAN}══════════════════════════════════════════════════════════════════════════════{TermColors.END}\n", flush=True)


def assign_diagrams_to_questions(
    questions: list[dict],
    diagram_pool: list[dict],
    subject: str = "",
    filename: str = "",
    file_bytes: bytes = b""
) -> int:
    """Strict Multi-Stage Diagram-to-Question Linker with Zero Blind Fallbacks & Direct Precision Cropping.
    1. Rejects non-visual subjects.
    2. Stage 1 (Direct Precision Crop): If question cites a specific figure (e.g. 'Fig. 4.16', '7.10'),
       finds the exact page in the PDF and renders a crisp, high-resolution crop of that figure.
    3. Stage 2 (Page & Caption Match): If crop not found, matches candidate diagram pool strictly on matching page.
    4. Stage 3 (Strict Safety): If confidence is not confirmed, leaves image_url = None (NO wrong images ever attached).
    Returns count of successfully linked diagrams.
    """
    if not questions:
        return 0

    if not is_diagram_subject(subject):
        # Clean redundant figure mentions if question is fully self-contained
        for norm in questions:
            if not norm.get("image_url"):
                q_text = norm.get("question", "")
                if re.match(r"^(?:in\s+the\s+given\s+figure|from\s+the\s+given\s+figure|referring\s+to\s+the\s+figure)[,\s]+", q_text, re.IGNORECASE):
                    if any(num_kw in q_text for num_kw in ["sides", "cm", "m", "angle", "radius", "=", "value of", "calculate"]):
                        norm["question"] = re.sub(r"^(?:in\s+the\s+given\s+figure|from\s+the\s+given\s+figure|referring\s+to\s+the\s+figure)[,\s]+", "For ", q_text, flags=re.IGNORECASE)
        return 0

    linked_count = 0
    available_diagrams = list(diagram_pool or [])

    print(f"\n{TermColors.BOLD}{TermColors.CYAN}--- [PRECISION DIAGRAM-TO-QUESTION MATCHING ENGINE] ---{TermColors.END}")
    print(f"  • Candidate Academic Diagrams in Pool: {len(available_diagrams)}")

    # Stopwords to ignore during caption keyword matching
    STOP_WORDS = {
        "the", "and", "for", "with", "this", "that", "from", "into", "shown", "what", "which",
        "how", "why", "given", "figure", "diagram", "below", "above", "image", "following",
        "observe", "refer", "study", "part", "table", "each", "both", "does", "have", "were"
    }

    # Pre-index PDF pages with type and sub-variant awareness
    visual_page_map = {}
    if file_bytes:
        try:
            import fitz
            doc_idx = fitz.open(stream=file_bytes, filetype="pdf")
            for pno in range(len(doc_idx)):
                p_text = doc_idx[pno].get_text()
                matches = re.finditer(r'\b(fig(?:ure)?\.?|table|chart)\s*(\d+(?:\.\d+)?(?:\s*\([a-zA-Z0-9]+\)|[a-zA-Z])?)(?![a-zA-Z0-9])', p_text, re.IGNORECASE)
                for m in matches:
                    v_type_raw = m.group(1).lower()
                    v_type = 'table' if 'table' in v_type_raw else ('chart' if 'chart' in v_type_raw else 'fig')
                    v_val = m.group(2).strip().lower().replace(" ", "")
                    if (v_type, v_val) not in visual_page_map:
                        visual_page_map[(v_type, v_val)] = pno + 1
                    norm_v_val = re.sub(r'[()]', '', v_val)
                    if (v_type, norm_v_val) not in visual_page_map:
                        visual_page_map[(v_type, norm_v_val)] = pno + 1
                    base_val = re.split(r'[\([a-zA-Z]', v_val)[0].strip()
                    if (v_type, base_val) not in visual_page_map:
                        visual_page_map[(v_type, base_val)] = pno + 1
            doc_idx.close()
        except Exception:
            pass

    for idx, norm in enumerate(questions, 1):
        if norm.get("image_url"):
            continue

        q_text = norm.get("question", "")
        if not is_diagram_referenced_in_question(q_text, norm):
            continue

        # Look for explicit figure/table identifier (e.g. 'Table 4.3', 'Fig. 4.16', 'Fig. 7.3b', 'Fig. 7.3(b)')
        table_match = re.search(r'\b(table\s*\d+(?:\.\d+)?(?:\s*\([a-zA-Z0-9]+\)|[a-zA-Z])?)(?![a-zA-Z0-9])', q_text, re.IGNORECASE)
        chart_match = re.search(r'\b(chart\s*\d+(?:\.\d+)?(?:\s*\([a-zA-Z0-9]+\)|[a-zA-Z])?)(?![a-zA-Z0-9])', q_text, re.IGNORECASE)
        fig_match = re.search(r'\b((?:fig(?:ure)?\.?)\s*\d+(?:\.\d+)?(?:\s*\([a-zA-Z0-9]+\)|[a-zA-Z])?)(?![a-zA-Z0-9])', q_text, re.IGNORECASE)

        target_fig_str = None
        if table_match:
            target_fig_str = table_match.group(1).strip()
        elif chart_match:
            target_fig_str = chart_match.group(1).strip()
        elif fig_match:
            target_fig_str = fig_match.group(1).strip()
        elif norm.get("figure_ref"):
            target_fig_str = str(norm.get("figure_ref")).strip()
        elif norm.get("has_visual") or is_diagram_referenced_in_question(q_text, norm):
            target_fig_str = "visual"

        saved_url = None

        # ---------------------------------------------------------------------
        # STAGE 1: DIRECT 3-LAYER PRECISION CROP FROM PDF (100% BULLETPROOF)
        # ---------------------------------------------------------------------
        if target_fig_str and file_bytes:
            clean_num_key = re.sub(r'^(?:table|chart|fig(?:ure)?\.?)\s*', '', target_fig_str, flags=re.IGNORECASE).strip().lower().replace(" ", "")
            clean_norm_key = re.sub(r'[()]', '', clean_num_key)
            base_key = re.split(r'[\([a-zA-Z]', clean_num_key)[0].strip()
            v_type = 'table' if 'table' in target_fig_str.lower() else ('chart' if 'chart' in target_fig_str.lower() else 'fig')

            hint_page = (
                norm.get("diagram_page")
                or visual_page_map.get((v_type, clean_num_key))
                or visual_page_map.get((v_type, clean_norm_key))
                or visual_page_map.get((v_type, base_key))
            )
            crop_bytes, actual_page = document_processor.crop_figure_from_pdf_page(
                file_bytes, 
                int(hint_page) if hint_page else None, 
                target_fig_str
            )
            if crop_bytes and actual_page:
                prefix_clean = re.sub(r'[^a-zA-Z0-9_]', '_', target_fig_str)
                saved_url = document_processor.save_diagram_to_disk(
                    image_bytes=crop_bytes,
                    ext="png",
                    prefix=f"crop_p{actual_page}_{prefix_clean}"
                )
                if saved_url:
                    norm["image_url"] = saved_url
                    linked_count += 1
                    q_snippet = (norm.get('question') or '')[:70].replace('\n', ' ')
                    print(f"  [PRECISION-CROP] Q#{idx} ({norm.get('type')}) '{q_snippet}...'")
                    print(f"     -> Visual URL  : {saved_url} (Direct Crisp 180 DPI Crop from PDF Page {actual_page})")
                    print(f"     -> Matched Ref : {target_fig_str}")
                    continue

        # ---------------------------------------------------------------------
        # STAGE 2: STRICT POOL MATCHING (PAGE-ISOLATED ONLY FOR FIGURES)
        # ---------------------------------------------------------------------
        # If the question explicitly requested a Table/Chart, NEVER attach arbitrary raster images from pool
        if table_match:
            continue

        selected_diag = None
        if target_fig_str and available_diagrams:
            for d in available_diagrams:
                direct_figs = d.get("direct_figures", [])
                cap = d.get("caption", "")
                if target_fig_str in direct_figs or re.search(rf'\b(?:fig(?:ure)?\.?|table|chart)\s*{re.escape(target_fig_str)}\b', cap, re.IGNORECASE):
                    selected_diag = d
                    break

        if not selected_diag and available_diagrams:
            q_words = set(re.findall(r'[a-zA-Z]{4,}', q_text.lower())) - STOP_WORDS
            best_diag = None
            best_overlap = 0

            for d in available_diagrams:
                cap = d.get("caption", "").lower()
                if not cap:
                    continue
                cap_words = set(re.findall(r'[a-zA-Z]{4,}', cap)) - STOP_WORDS
                overlap = len(q_words & cap_words)
                # Require at least 2 distinct academic keywords
                if overlap >= 2 and overlap > best_overlap:
                    best_overlap = overlap
                    best_diag = d

            if best_diag and best_overlap >= 2:
                selected_diag = best_diag

        if selected_diag:
            available_diagrams.remove(selected_diag)
            saved_url = document_processor.save_diagram_to_disk(
                image_bytes=selected_diag["image_bytes"],
                ext=selected_diag.get("ext", "png"),
                prefix=f"diag_p{selected_diag.get('page', 1)}"
            )
            if saved_url:
                norm["image_url"] = saved_url
                linked_count += 1
                q_snippet = (norm.get('question') or '')[:70].replace('\n', ' ')
                cap_snippet = (selected_diag.get('caption') or 'Direct Fig Match')[:50].replace('\n', ' ')
                print(f"  [LINKED] Q#{idx} ({norm.get('type')}) '{q_snippet}...'")
                print(f"     -> Diagram URL : {saved_url} (Page {selected_diag.get('page')})")
                print(f"     -> Matched By  : {cap_snippet}")
        else:
            # Clean self-contained questions if no verified diagram was matched
            if re.match(r"^(?:in\s+the\s+given\s+figure|from\s+the\s+given\s+figure)[,\s]+", q_text, re.IGNORECASE):
                if any(num_kw in q_text for num_kw in ["sides", "cm", "m", "angle", "radius", "=", "value of", "calculate"]):
                    norm["question"] = re.sub(r"^(?:in\s+the\s+given\s+figure|from\s+the\s+given\s+figure)[,\s]+", "For ", q_text, flags=re.IGNORECASE)

    if linked_count == 0:
        print(f"  [INFO] No questions in this batch required diagrams or matched verified captions.")
    print(f"----------------------------------------------------\n")

    return linked_count


TEXTBOOK_QUESTION_PROMPT = """You are an expert curriculum designer and senior national board examiner (CBSE, ICSE, Cambridge, State Boards).
Your task is to analyze the provided textbook/chapter text and extract all direct questions AND synthesize rich, high-yield examination questions covering EVERY single concept in the text (MAX-TO-MAX YIELD).

YOU MUST GENERATE QUESTIONS SPANNING ALL 9 QUESTION TYPES:
1. 'MCQ' (1M): Multiple Choice Question with exactly 4 authentic options ('A) ', 'B) ', 'C) ', 'D) '). 'correct_answer' MUST be the exact matching text from the options list (NOT just 'A' or 'Option A').
2. 'Objective' (1M): Direct definition, one-word answer, or fill-in-the-blank. For every 'Fill in the blank' question, you MUST contextually and grammatically place '________' exactly where the missing word/concept belongs (e.g. 'Fill in the blank: The materials that are attracted towards a magnet are called ________.' or 'Fill in the blanks: Unlike poles of two magnets ________ each other, whereas like poles ________ each other.' or 'Fill in the blank: ________ is the process of converting water into water vapour.'). NEVER place the blank at the start if the sentence begins with a subject noun/phrase. 'options' MUST be []. 'correct_answer' is the direct word/phrase.
3. 'Numerical' (1M, 3M, or 5M): Quantitative calculation or formula application. Provide step-by-step formula derivation in 'explanation' and final value with units in 'correct_answer'. 'options' MUST be [].
4. 'Assertion Reason' (1M): Standard assertion (A) and reason (R) format with 4 standard board options.
5. 'SAQ' (2M): Short Answer Question (2-3 focused lines testing foundational concept or definition). 'options' MUST be [].
6. 'Short Answer (3M)' (3M): 3 distinct key points, differential table, or mechanism explanation. 'options' MUST be [].
7. 'Case Study' (4M): Real-world scenario/passage followed by numbered sub-questions with individual model answers. 'options' MUST be [].
8. 'Long Answer' (5M): Comprehensive 5-mark answer with introduction, key points, mechanism/diagram explanation, and conclusion. 'options' MUST be [].
9. 'Long Evaluative (8M)' (8M): Comprehensive essay-length question requiring high-order evaluation, critical analysis, and synthesis. 'options' MUST be [].

THE 4 GOLDEN RULES (CRITICAL CONSTRAINTS):
1. AUTHENTIC CONTENT ONLY: NEVER output placeholder phrases like 'Standard model solution...', 'Option A', 'Key Concept:', '• Conceptual principle for...' or empty values. Every explanation must provide actual step-by-step reasoning or formulas grounded strictly in the provided text.
2. ACADEMIC QUESTIONS ONLY: Skip publisher info, ISBN, copyright notices, headers, footers, and exam paper instructions ('Roll No', 'Check that paper contains').
3. STANDALONE QUESTIONS: Every question must be fully complete on its own. Never output bare prompts like 'Fill in the blank.' or 'the following questions:'. Combine the prompt with the target sentence.
4. PRESERVE MATH & SCIENCE: Keep LaTeX expressions (\\frac, \\sqrt, x^2, \\Omega, \\alpha, \\beta), chemical notations (H2O, CaCl2, CO2), and units intact.
5. STRICT MCQ & SAQ ACCURACY: If a question is open-ended or descriptive (e.g., 'What is the life cycle of...', 'Rewrite...', 'Explain...'), set type='SAQ' or 'Objective' with options=[]. NEVER create an MCQ with irrelevant or mismatched options. For any 'MCQ', all 4 options MUST be directly relevant to the question topic, and 'correct_answer' MUST be one of those exact 4 options.
6. STRICT CURRICULUM SUBJECT MATTER GROUNDING (NEVER ASK ABOUT TEXTBOOK STRUCTURE OR PEDAGOGY):
   - NEVER generate questions about the physical book, book design, textbook titles (e.g. 'Curiosity', 'Beehive'), layout, pedagogical sections (e.g. 'Learning further', 'role of Summary section', 'Teacher notes', 'activities section purpose', 'integrated approach in this book').
   - ONLY generate questions testing pure scientific, mathematical, or academic concept facts (e.g. Magnetic Poles, Electric Current, Plant Structure, Separation Methods, Ecosystems).
7. PRESERVE FIGURE, TABLE & DIAGRAM CITATIONS:
   - If an exercise or text question references a figure, table, chart, apparatus, or diagram (e.g., 'Fig. 4.16', 'Table 4.3', 'Chart 1.2', 'In the given diagram', 'observe the apparatus'), PRESERVE the figure/table identifier in the question text (e.g., 'According to the observations in Table 4.3...', 'Refer to Fig. 4.16: ...').
   - For ANY question that requires a diagram, table, chart, or apparatus to be understood/solved, include:
     "figure_ref": "Table 4.3" or "Fig. 4.16" (or null if unnumbered),
     "has_visual": true
8. ATOMIC SINGLE-QUESTION RULE (NO COMPOUND GLUED QUESTIONS FOR 1M, 2M, 3M):
   - Every MCQ (1M), Objective (1M), SAQ (2M), and Short Answer (3M) question MUST ask exactly ONE single, focused question.
   - NEVER glue or concatenate two questions together into a single 1-mark item (e.g. NEVER output: 'What is the temperature reading in Fig. 7.10? What is the smallest value it can measure?').
   - If a textbook question contains multi-part sub-questions (e.g. part a and part b), generate them as TWO separate, independent questions with their own options/answers.
   - Multi-part sub-questions are ONLY permitted in Case Study (4M) and Long Answer (5M).
9. STRICT OBJECTIVE VS SAQ SEGREGATION & NO ANSWER LEAKS:
   - 'Fill in the blanks', 'Complete the sentence', 'Choose the correct word', 'True or False', or questions requiring filling '________' MUST ALWAYS have type='Objective'. NEVER classify Fill in the blanks or True/False as 'SAQ'.
   - 'SAQ' (2M) MUST ALWAYS be an authentic conceptual or descriptive question (e.g. 'Explain why...', 'Define...', 'State two differences between...').
   - NEVER paste or append the answer key into the question text (e.g. NEVER output '(i) temperature (ii) clinical' at the end of the question sentence). All answers must go exclusively in 'correct_answer'.

JSON Schema & Example:
{
  "questions": [
    {
      "question": "Which of the following gases is released when Zinc granules react with dilute Sulphuric Acid?",
      "type": "MCQ",
      "difficulty": "simple",
      "marks": 1,
      "options": [
        "A) Oxygen gas",
        "B) Hydrogen gas",
        "C) Carbon Dioxide gas",
        "D) Nitrogen Dioxide gas"
      ],
      "correct_answer": "Hydrogen gas",
      "explanation": "When Zinc (Zn) reacts with dilute Sulphuric Acid (H2SO4), it forms Zinc Sulphate (ZnSO4) and releases Hydrogen gas (H2). Reaction: Zn + H2SO4 -> ZnSO4 + H2.",
      "topic_suggested": "Acids and Metals Reactions",
      "figure_ref": null,
      "has_visual": false,
      "image_url": null
    },
    {
      "question": "Complete the statement: The SI unit of electric potential difference is ________.",
      "type": "Objective",
      "difficulty": "simple",
      "marks": 1,
      "options": [],
      "correct_answer": "Volt (V)",
      "explanation": "Electric potential difference between two points is measured in Volts (V), named in honor of Alessandro Volta.",
      "topic_suggested": "Electric Potential and Potential Difference",
      "image_url": null
    },
    {
      "question": "Define Refractive Index of a medium and write its mathematical formula.",
      "type": "SAQ",
      "difficulty": "medium",
      "marks": 2,
      "options": [],
      "correct_answer": "Refractive index of a medium is the ratio of the speed of light in vacuum (c) to the speed of light in that medium (v). Formula: n = c / v.",
      "explanation": "It indicates how much light slows down and bends when entering the medium from vacuum or air.",
      "topic_suggested": "Refraction of Light",
      "image_url": null
    },
    {
      "question": "State three differences between Arteries and Veins in the human circulatory system.",
      "type": "Short Answer (3M)",
      "difficulty": "medium",
      "marks": 3,
      "options": [],
      "correct_answer": "1. Arteries carry oxygenated blood away from the heart (except pulmonary artery), while veins carry deoxygenated blood towards the heart.\\n2. Arteries have thick, elastic walls without valves, whereas veins have thin walls with valves to prevent backflow.\\n3. Blood flows under high pressure in arteries and under low pressure in veins.",
      "explanation": "These structural adaptations enable arteries to withstand high ventricle pumping pressure and veins to direct low-pressure blood steadily back to the heart.",
      "topic_suggested": "Human Circulatory System",
      "image_url": null
    },
    {
      "question": "Explain the process of Photosynthesis in green plants. Describe the light-dependent and light-independent reactions along with the balanced chemical equation.",
      "type": "Long Answer",
      "difficulty": "hard",
      "marks": 5,
      "options": [],
      "correct_answer": "Photosynthesis is the biochemical process by which green plants synthesize glucose from carbon dioxide and water in the presence of sunlight and chlorophyll.\\n\\n• Balanced Equation:\\n6CO2 + 6H2O + Light Energy -> C6H12O6 + 6O2\\n\\n• Main Stages:\\n1. Light Reaction (in Thylakoid): Absorption of solar energy by chlorophyll, splitting of water molecules (photolysis) into hydrogen and oxygen, and generation of ATP and NADPH.\\n2. Dark Reaction / Calvin Cycle (in Stroma): Fixation and reduction of CO2 into glucose utilizing ATP and NADPH generated in the light phase.",
      "explanation": "Photosynthesis sustains life on Earth by providing food and oxygen. It converts solar energy into chemical energy stored in glucose bonds.",
      "topic_suggested": "Photosynthesis & Plant Nutrition",
      "image_url": null
    },
    {
      "question": "Critically analyze the socio-economic impacts of the Industrial Revolution in 19th-century Europe. Evaluate both its transformative benefits and adverse consequences on the working class.",
      "type": "Long Evaluative (8M)",
      "difficulty": "hard",
      "marks": 8,
      "options": [],
      "correct_answer": "Introduction:\\nThe Industrial Revolution marked a structural transition from agrarian handcraft to mechanized factory production originating in Britain and expanding globally.\\n\\n1. Economic Transformation:\\n• Tremendous surge in industrial output, steam transportation (railways), and global trade networks.\\n• Emergence of corporate capitalism and commercial banking.\\n\\n2. Working Class Impact:\\n• Rapid, unplanned urbanization led to squalid tenements, lack of sanitation, and disease outbreaks.\\n• Unregulated 14-16 hour work shifts in hazardous factory environments with widespread child labor.\\n\\n3. Legislative Reforms:\\n• Spurred the rise of labor unions and Factory Acts regulating minimum working conditions and schooling.\\n\\nConclusion:\\nWhile establishing modern industrial wealth, the era underscored severe inequalities that shaped modern social welfare and labor laws.",
      "explanation": "Comprehensive evaluation weighing industrial technological advancements against severe social costs and legislative reforms.",
      "topic_suggested": "Industrialization and Social Changes",
      "image_url": null
    },
    {
      "question": "An electric iron consumes energy at a rate of 840 W when heating is at the maximum rate and 360 W at the minimum rate. The voltage is 220 V. Calculate the current and the resistance in each case.",
      "type": "Numerical",
      "difficulty": "medium",
      "marks": 3,
      "options": [],
      "correct_answer": "Case (a) Maximum Rate: Current I = 3.82 A, Resistance R = 57.60 Ω\\nCase (b) Minimum Rate: Current I = 1.64 A, Resistance R = 134.15 Ω",
      "explanation": "Given:\\nVoltage V = 220 V\\nPower P1 = 840 W, P2 = 360 W\\n\\nFormulas:\\n1. Power P = V * I  =>  I = P / V\\n2. Resistance R = V / I\\n\\nCalculations:\\n• Maximum Rate:\\n  I1 = 840 / 220 = 3.82 A\\n  R1 = 220 / 3.82 = 57.60 Ω\\n\\n• Minimum Rate:\\n  I2 = 360 / 220 = 1.64 A\\n  R2 = 220 / 1.64 = 134.15 Ω",
      "topic_suggested": "Heating Effect of Electric Current",
      "image_url": null
    },
    {
      "question": "Assertion (A): The inner lining of the small intestine has numerous finger-like projections called villi.\\nReason (R): Villi decrease the surface area for absorption of digested food.",
      "type": "Assertion Reason",
      "difficulty": "medium",
      "marks": 1,
      "options": [
        "A) Both Assertion (A) and Reason (R) are true and Reason (R) is the correct explanation of Assertion (A)",
        "B) Both Assertion (A) and Reason (R) are true but Reason (R) is not the correct explanation of Assertion (A)",
        "C) Assertion (A) is true but Reason (R) is false",
        "D) Assertion (A) is false but Reason (R) is true"
      ],
      "correct_answer": "Assertion (A) is true but Reason (R) is false",
      "explanation": "Assertion (A) is true because small intestine possesses millions of villi. Reason (R) is false because villi ENORMOUSLY INCREASE surface area for absorption, not decrease it.",
      "topic_suggested": "Nutrition and Digestion in Humans",
      "image_url": null
    },
    {
      "question": "Read the following passage and answer the questions that follow:\\n\\nA student tested four solutions A, B, C, and D with universal indicator paper and recorded the pH values: A (pH = 2), B (pH = 7), C (pH = 13), and D (pH = 5).\\n\\n(i) Which solution is strongly basic and which one is strongly acidic?\\n(ii) What will happen when solution A is mixed with solution C in equal stoichiometric proportions?",
      "type": "Case Study",
      "difficulty": "medium",
      "marks": 4,
      "options": [],
      "correct_answer": "(i) Solution C (pH = 13) is strongly basic, and Solution A (pH = 2) is strongly acidic.\\n(ii) Mixing strong acid A with strong base C results in a neutralization reaction, forming neutral salt and water with pH ~ 7.",
      "explanation": "On the pH scale: pH < 7 is acidic (lower pH = stronger acid), pH = 7 is neutral, and pH > 7 is basic (higher pH = stronger base). Neutralization yields neutral salt and water.",
      "topic_suggested": "pH Scale and Neutralization",
      "image_url": null
    }
  ]
}
"""

OLD_QUESTION_PAPER_PROMPT = """You are a senior national board paper evaluator, bilingual digitizer, and curriculum expert (CBSE, ICSE, ISC, State Boards).
Your task is to parse the provided Question Paper / Question Bank / PYQ text, faithfully extract and digitize EVERY single question present in the document with 100% fidelity, exact printed marks, options, and diagrams.

CRITICAL BILINGUAL & DIGITIZATION INSTRUCTIONS:
1. BILINGUAL PAPERS (Hindi/Bengali + English):
   - For general subjects (Science, Physics, Chemistry, Biology, Mathematics, Social Studies, Physical Education, Computer Science), extract the clean ENGLISH version of the question text and options.
   - Strip out parallel Hindi, Bengali, or regional duplicate sentences, headers (e.g. 'अथवा / OR', 'प्रश्न 1.'), and option translations (e.g. '(A) कोयला / Coal' -> 'A) Coal').
   - For Language subjects (e.g., Hindi Course A/B, Bengali Language, Sanskrit), preserve the respective native language of the subject.

2. MARKS-WISE & QUESTION TYPE MAPPING:
   - Assign exact official marks (1, 2, 3, 4, 5, or 8) and matching question type:
     • 1 Mark: 'MCQ', 'Assertion Reason', or 'Objective'
     • 2 Marks: 'SAQ' (Short Answer Question - 2M)
     • 3 Marks: 'Short Answer (3M)' or 'Numerical'
     • 4 Marks: 'Case Study' (Case-based / passage-based with sub-questions)
     • 5 Marks: 'Long Answer'
     • 8 Marks: 'Long Evaluative (8M)'

3. OPTIONS & AUTHENTIC MODEL ANSWERS:
   - For Multiple Choice Questions (MCQ), extract all 4 options labeled 'A) ', 'B) ', 'C) ', 'D) '.
   - 'correct_answer' MUST contain the exact authentic text of the correct choice (e.g. 'Hydrogen gas', NOT 'Option A' or 'A').
   - If a question does NOT have options, extract it strictly as SAQ, Objective, Numerical, or Long Answer. NEVER invent fake dummy options.
   - For descriptive questions, provide a genuine, comprehensive model answer in 'correct_answer' and detailed step-by-step explanation in 'explanation'.

4. 100% COMPLETE EXTRACTION:
   - Extract EVERY distinguishable question and sub-question (e.g., Q1(a), Q1(b), Q2(i), Q2(ii)) present in the text sequentially without skipping any question.

5. DIAGRAMS & MATHEMATICS:
   - Preserve references to figures, charts, maps, circuits, and geometry triangles.
   - Preserve clean mathematical formulas and scientific notation (LaTeX, Greek symbols, formulas).
"""


def _print_separator(title: str, color: str = TermColors.CYAN):
    print(f"\n{color}{TermColors.BOLD}{'=' * 80}")
    print(f" {title.center(78)} ")
    print(f"{'=' * 80}{TermColors.END}")


def _print_step_header(step_num: int, step_name: str, color: str = TermColors.YELLOW):
    print(f"\n{color}{TermColors.BOLD}>>> [STEP {step_num}: {step_name.upper()}]{TermColors.END}")


def perform_contextual_analysis(
    text_content: str = "",
    filename: str = "",
    board: str = "",
    class_grade: str = "",
    subject: str = "",
    document_type: str = "textbook",
    session: Optional[Session] = None,
    cleaned_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates a fast, high-quality contextual analysis of the document and identifies subject & chapter accurately without hallucination."""
    raw_text = cleaned_text if cleaned_text is not None else text_content
    if len(raw_text) > 15000:
        # Sample beginning + core chapter content to skip preface/copyright
        excerpt = raw_text[:3500] + "\n\n...[Core Chapter Discussion]...\n\n" + raw_text[5000:10500]
    else:
        excerpt = raw_text[:8000]

    # Pre-fetch existing official chapters from MySQL for this (Board, Class, Subject)
    official_chapters: List[str] = []
    if session:
        try:
            sql = text("""
                SELECT ch.chapter_name
                FROM chapter_master ch
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                WHERE LOWER(TRIM(b.board_name)) = LOWER(TRIM(:b))
                  AND (LOWER(TRIM(c.class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(:c)))
                  AND (
                      LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:s)) 
                      OR (LOWER(TRIM(:s)) = 'science' AND LOWER(TRIM(s.subject_name)) IN ('physics', 'chemistry', 'biology', 'science'))
                      OR (LOWER(TRIM(:s)) IN ('social science', 'social studies') AND LOWER(TRIM(s.subject_name)) IN ('history', 'geography', 'political science', 'civics', 'economics', 'social science', 'social studies'))
                  )
                  AND ch.is_active = 1
                ORDER BY ch.id ASC
            """)
            official_chapters = [r[0] for r in session.execute(sql, {"b": board, "c": class_grade, "s": subject}).fetchall()]
        except Exception:
            pass

    chapters_ref_prompt = ""
    if official_chapters:
        chapters_ref_prompt = f"""
Official Curriculum Chapters for this Subject ({subject}):
{json.dumps(official_chapters, indent=2)}

ANTI-HALLUCINATION REQUIREMENT:
- If the uploaded text matches one of the official curriculum chapters above, you MUST set "title" to the EXACT matching official chapter title from this list (do NOT invent new names or add Chapter numbers).
"""

    system_prompt = f"""You are an expert curriculum auditor and senior board paper reviewer for {board} {class_grade}.
The user is uploading a textbook or exam document for the primary subject: "{subject}".
Analyze the provided educational document excerpt and accurately determine:
1. The exact subject discipline. Note that sub-topics of {subject} (e.g. mechanics/optics for Physics/Science; organic/periodic for Chemistry/Science; botany/genetics for Biology/Science; history/civics/geography/economics for Social Science) are valid parts of {subject}.
2. The core chapter or paper title.
3. Summary of concepts covered.
4. Specific key concept topics (3-6 topics).{chapters_ref_prompt}"""

    user_prompt = f"""Document Metadata:
- File Name: {filename}
- Target Board: {board}
- Target Class: {class_grade}
- Selected Target Subject: {subject}
- Document Type: {document_type} (textbook or old_question_paper)

--- DOCUMENT EXCERPT ---
{excerpt}
--- END EXCERPT ---

Return strictly a JSON object with this exact structure:
{{
  "title": "Clear Title of Chapter or Question Paper",
  "summary": "2-3 concise sentences summarizing the core content, concepts covered, and educational scope.",
  "detected_subject": "{subject}",
  "detected_topics": ["Topic 1", "Topic 2", "Topic 3", "Topic 4"],
  "estimated_difficulty": "easy | medium | hard",
  "recommended_question_count": 25
}}
Note: recommended_question_count should be between 20 (minimum) and 30 (maximum) for comprehensive chapter question bank generation.
"""
    try:
        res = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.2, scenario="pdf_generation")
        if isinstance(res, dict) and "title" in res:
            rec_q = res.get("recommended_question_count")
            if isinstance(rec_q, (int, float)):
                res["recommended_question_count"] = max(15, min(35, int(rec_q)))
            else:
                res["recommended_question_count"] = 25
            return res
    except Exception as e:
        logger.warning(f"Contextual analysis LLM fallback: {e}")

    # Fallback contextual analysis with regex
    meta = document_processor.detect_curriculum_metadata(raw_text[:4000])
    detected_sub = meta.get("subject") or subject
    first_lines = [line.strip() for line in raw_text.splitlines() if line.strip()][:5]
    guessed_title = first_lines[0] if first_lines else filename.rsplit(".", 1)[0]
    return {
        "title": guessed_title[:120],
        "summary": f"Curriculum document for {board} {class_grade} {subject} containing {len(raw_text)} characters.",
        "detected_subject": subject,
        "detected_topics": [subject, "Core Concepts", "Applications"],
        "estimated_difficulty": "medium",
        "recommended_question_count": 25,
    }


def clean_human_readable_text(val: Any) -> str:
    """Cleans markdown symbols, brackets, raw json arrays, python lists, escaped quotes, and noise into clean human-readable text with line breaks."""
    if val is None:
        return ""

    # If list or array
    if isinstance(val, list):
        if not val:
            return ""
        if len(val) == 1:
            return clean_human_readable_text(val[0])

        items = []
        for item in val:
            cleaned_item = clean_human_readable_text(item)
            if cleaned_item:
                # If item has internal newlines, preserve each line
                for sub_line in cleaned_item.splitlines():
                    sub_l = sub_line.strip()
                    if not sub_l:
                        continue
                    # If item is a heading (ends with ':') or a short title, don't force a bullet dot
                    if sub_l.endswith(":") or (len(sub_l) < 35 and not any(sub_l.startswith(b) for b in ["•", "-", "*"])):
                        items.append(sub_l)
                    else:
                        stripped = re.sub(r'^[•\-\*\d\.\)\s]+', '', sub_l).strip()
                        items.append(f"• {stripped}")
        return "\n".join(items)

    # If dict
    if isinstance(val, dict):
        items = []
        for k, v in val.items():
            if v:
                v_clean = clean_human_readable_text(v)
                if "\n" in v_clean:
                    items.append(f"{k}:\n{v_clean}")
                else:
                    items.append(f"{k}: {v_clean}")
        return "\n\n".join(items)

    text = str(val).strip()
    if not text:
        return ""

    # 1. Check if text is a JSON or Python literal encoded array/dict string e.g. "['Step 1: ...', 'Step 2: ...']"
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, dict)):
                return clean_human_readable_text(parsed)
        except Exception:
            pass
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, dict)):
                return clean_human_readable_text(parsed)
        except Exception:
            pass

    # 2. Check for intermediate list artifacts like "', '" or "', \"• " or '", "' in text
    if re.search(r"['\"]\s*,\s*['\"]", text):
        trimmed = text.strip("[](){}\"' ")
        parts = re.split(r"['\"]\s*,\s*['\"]", trimmed)
        if len(parts) > 1:
            return clean_human_readable_text(parts)

    # Unescape escaped quotes and backslashes
    text = text.replace('\\"', '"').replace("\\'", "'").replace('\\n', '\n').replace('\\t', ' ')

    # Strip markdown bold/italics: **bold** or *italic* or __bold__ or _italic_
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)

    # Convert HTML line breaks <br>, <br/>, <br />, <p>, </p>, <div> to clean plain text newlines
    text = re.sub(r'<\s*br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/?p\s*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/?div\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/?span[^>]*>', '', text, flags=re.IGNORECASE)

    # Normalize weird dashes / separators (e.g. '---', '--')
    text = re.sub(r'-{3,}', '-', text)
    text = re.sub(r'\s+--\s+', ' - ', text)

    # Standardize bullet points and remove raw bracket fragments
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        # Remove leftover array quotes or brackets e.g. [" or "]
        l = re.sub(r'^[\[\]"\'\s]+', '', l)
        l = re.sub(r'[\[\]"\'\s]+$', '', l)
        if not l:
            continue
        # If line starts with markdown bullet like '- ' or '* ' -> convert to '• '
        if re.match(r'^[\-\*]\s+', l):
            l = '• ' + re.sub(r'^[\-\*]\s+', '', l).strip()
        cleaned_lines.append(l)

    text = "\n".join(cleaned_lines).strip()
    return text


def _normalize_title(text_val: str) -> str:
    """Helper to clean chapter and topic strings for robust matching."""
    if not text_val:
        return ""
    # Strip common prefixes like 'Chapter 1: ', 'Unit 2 - ', 'Ch. 3 '
    cleaned = re.sub(r'^(?:Chapter|Unit|Ch\.?|Lesson|Section)\s*\d+[\s\:\-\.]*', '', text_val, flags=re.IGNORECASE).strip()
    # Remove special characters and lowercase
    return re.sub(r'[^a-zA-Z0-9]', '', cleaned).lower()


def _find_best_canonical_topic(raw_topic: str, canonical_topics: List[str], threshold: float = 0.40) -> Optional[str]:
    """Finds the best matching canonical topic based on word token overlap or containment."""
    if not raw_topic or not canonical_topics:
        return None
    raw_norm = _normalize_title(raw_topic)
    raw_words = set(re.findall(r'\b\w{3,}\b', raw_topic.lower()))
    if not raw_words:
        return None

    best_match = None
    best_score = 0.0
    for can in canonical_topics:
        if not can or not str(can).strip():
            continue
        can_str = str(can).strip()
        can_norm = _normalize_title(can_str)
        if raw_norm == can_norm or (len(raw_norm) >= 5 and (raw_norm in can_norm or can_norm in raw_norm)):
            return can_str
        can_words = set(re.findall(r'\b\w{3,}\b', can_str.lower()))
        if not can_words:
            continue
        intersection = raw_words.intersection(can_words)
        union = raw_words.union(can_words)
        score = len(intersection) / len(union) if union else 0.0
        # If one is subset of another
        if intersection == raw_words or intersection == can_words:
            score = max(score, 0.75)
        if score > best_score:
            best_score = score
            best_match = can_str

    if best_score >= threshold:
        return best_match
    return None


def heal_fill_in_the_blank_question(q_text: str, correct_answer: str) -> str:
    """Auto-heals Objective/Fill in the Blank questions to ensure a clean, grammatical, and contextually placed '________' marker."""
    if not q_text:
        return q_text

    # Normalize arbitrary blanks/dots like [blank], (blank), ..., ___ to standard '________'
    normalized = re.sub(r'\[\s*(?:blank|\.\.\.|_)\s*\]|\(\s*(?:blank|\.\.\.|_)\s*\)', '________', q_text, flags=re.IGNORECASE)
    normalized = re.sub(r'\.{3,}|_{2,}', '________', normalized)

    # Check if question is a Fill-in-the-blank / Complete prompt
    is_blank_prompt = bool(re.search(r'\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\b', normalized, re.IGNORECASE))

    # Clean up accidental leading blank placed before a capitalized subject noun
    # e.g. 'Fill in the blank: ________ The materials...' -> 'Fill in the blank: The materials...'
    if re.search(r'^(.*?\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\s*[:\-–—]\s*)________\s+([A-Z][a-z]+)', normalized, re.IGNORECASE):
        lead_match = re.search(r'^(.*?\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\s*[:\-–—]\s*)________\s+([A-Z][a-z]+)', normalized, re.IGNORECASE)
        next_word = lead_match.group(2).lower() if lead_match else ""
        if next_word not in ['is', 'are', 'was', 'were', 'refers', 'means', 'denotes', 'represents', 'can', 'could', 'will', 'has', 'have']:
            normalized = re.sub(r'^(.*?\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\s*[:\-–—]\s*)________\s+', r'\1', normalized, flags=re.IGNORECASE)

    # Fix awkward tail blank placed after a noun following a verb e.g. 'has poles ________.' -> 'has ________ poles.'
    awkward_tail_blank = r'\b(has|have|had|contains|possesses|with)\s+([a-zA-Z]+)\s+________\s*[\.\:\s]*$'
    if re.search(awkward_tail_blank, normalized, re.IGNORECASE):
        normalized = re.sub(awkward_tail_blank, r'\1 ________ \2.', normalized, flags=re.IGNORECASE)

    # Fix omitted verb before 'each other' e.g. 'magnets each other' -> 'magnets ________ each other'
    normalized = re.sub(r'(\b(?:magnets|poles|charges|bodies|particles|objects|surfaces|materials|species)\s+)each\s+other\b', r'\1________ each other', normalized, flags=re.IGNORECASE)

    # Process multi-line sub-parts (e.g. (i), (ii), (a), (b), 1., 2.)
    lines = normalized.splitlines()
    if len(lines) > 1 and any(re.match(r'^\s*\(?[iIvVxXa-d\d]+\)?[\.\:\s]', l) for l in lines):
        healed_lines = []
        for line in lines:
            l = line.strip()
            if not l:
                continue
            if re.match(r'^\(?[iIvVxXa-d\d]+\)?[\.\:\s]', l) and "________" not in l:
                if re.search(r'\b(?:its|a|an|the|is|are|was|were|by|in|of|to|called|as)\s*[\.\:\s]*$', l, re.IGNORECASE):
                    l = re.sub(r'(\b(?:its|a|an|the|is|are|was|were|by|in|of|to|called|as))\s*[\.\:\s]*$', r'\1 ________.', l, flags=re.IGNORECASE)
                elif re.search(r'\b(?:a|an|the)\s+[a-zA-Z]+(?:\s+[a-zA-Z]+)?\s*[\.\:\s]*$', l, re.IGNORECASE):
                    l = re.sub(r'\b(a|an|the)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s*[\.\:\s]*$', r'\1 ________ \2.', l, flags=re.IGNORECASE)
                elif not l.endswith("________."):
                    l = l.rstrip('. :') + " ________."
            healed_lines.append(l)
        normalized = "\n".join(healed_lines)
    elif is_blank_prompt and "________" not in normalized:
        # Dynamic Step A: If correct_answer or its components are in the sentence, replace them with ________
        if correct_answer and len(correct_answer.strip()) > 1:
            raw_parts = [p.strip() for p in re.split(r'[,;/]|\band\b', correct_answer) if p.strip()]
            for p in raw_parts:
                if len(p) >= 2 and re.search(r'\b' + re.escape(p) + r'\b', normalized, re.IGNORECASE):
                    header_m = re.search(r'^(.*?\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\s*[:\-–—]\s*)', normalized, re.IGNORECASE)
                    hdr_len = len(header_m.group(1)) if header_m else 0
                    body = normalized[hdr_len:]
                    body = re.sub(r'\b' + re.escape(p) + r'\b', '________', body, count=1, flags=re.IGNORECASE)
                    normalized = normalized[:hdr_len] + body

        # Dynamic Step B: If sentence ends with definition/preposition e.g. 'are called', 'is known as', 'called .'
        if "________" not in normalized:
            def_tail_pat = r'\b(is\s+called|are\s+called|was\s+called|were\s+called|is\s+known\s+as|are\s+known\s+as|is\s+termed\s+as|is\s+termed|are\s+termed|is\s+defined\s+as|are\s+defined\s+as|called|termed|known\s+as|refers\s+to|means|consists\s+of|equals\s+to|forms|produces|generates)\s*[\.\:\s]*$'
            if re.search(def_tail_pat, normalized, re.IGNORECASE):
                normalized = re.sub(def_tail_pat, r'\1 ________.', normalized, flags=re.IGNORECASE)

        # Dynamic Step C: Sentence ends with 'has/have/contains/possesses [noun]' e.g. 'A magnet always has poles.' -> 'has ________ poles.'
        if "________" not in normalized:
            verb_noun_tail = r'\b(has|have|had|contains|possesses|with)\s+([a-zA-Z]+)\s*[\.\:\s]*$'
            if re.search(verb_noun_tail, normalized, re.IGNORECASE):
                normalized = re.sub(verb_noun_tail, r'\1 ________ \2.', normalized, flags=re.IGNORECASE)

        # Dynamic Step D: Sentence ends with article + noun e.g. 'points towards the direction.' -> 'the ________ direction.'
        if "________" not in normalized:
            art_noun_tail = r'\b(a|an|the)\s+([a-zA-Z]+)\s*[\.\:\s]*$'
            if re.search(art_noun_tail, normalized, re.IGNORECASE):
                normalized = re.sub(art_noun_tail, r'\1 ________ \2.', normalized, flags=re.IGNORECASE)

        # Dynamic Step E: Missing subject at start e.g. 'Fill in the blank: is a natural resource'
        if "________" not in normalized:
            verb_start_pattern = r'^(.*?\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank))\s*[:\-–—]\s*)(is|are|was|were|refers|means|denotes|represents|can|could|will|would|should|has|have|had|helps|occurs|consists|contains|describes|states|involves)\b'
            if re.search(verb_start_pattern, normalized, re.IGNORECASE):
                normalized = re.sub(verb_start_pattern, r'\1________ \2', normalized, flags=re.IGNORECASE)

        # Dynamic Step F: Fallback - append blank at the end of the sentence
        if "________" not in normalized:
            normalized = normalized.rstrip('. :') + " ________."

    return normalized


def sanitize_question_item(
    q: dict,
    default_type: str,
    target_diff: str,
    meta: dict,
    index: int
) -> Optional[Dict[str, Any]]:
    """Sanitizes and strictly formats a question item for question_master schema with bilingual filtering and human-readable text."""
    raw_q_text = str(q.get("question") or "").strip()
    if not raw_q_text:
        return None

    # Check if subject is language (Hindi, Bengali, Sanskrit, English)
    sub_lower = str(meta.get("subject") or "").lower()
    is_lang_subject = any(lang in sub_lower for lang in ["hindi", "bengali", "bangla", "sanskrit", "arabic", "urdu"])

    # 0. Anti-Garbage, Meta-Textbook, & Copyright Guardrail
    q_lower = raw_q_text.lower()
    from helper.document_processor import DISCLAIMER_PATTERNS
    if any(re.search(pat, q_lower) for pat in DISCLAIMER_PATTERNS):
        return None

    # Reject questions testing textbook design / physical book structure / pedagogical meta-text
    META_BOOK_PATTERNS = [
        r"\blearning\s+further\b",
        r"\brole\s+of\s+(?:the\s+)?['\"]?summary['\"]?\s+section\b",
        r"\bstructure\s+and\s+purpose\s+of\s+the\b",
        r"\btextbook\s+['\"]?curiosity['\"]?\b",
        r"\babout\s+(?:the\s+)?book\b",
        r"\bin\s+this\s+textbook\b",
        r"\bsection\s+in\s+(?:the|each)\s+chapter\b",
        r"\bintegrated\s+approach\s+in\s+science\s+teaching\b",
        r"\bpedagogical\s+(?:approach|intent|framework)\b",
        r"\bwhy\s+is\s+this\s+textbook\s+designed\b",
        r"\bpurpose\s+of\s+the\s+['\"]?curiosity['\"]?\s+textbook\b",
    ]
    if any(re.search(pat, q_lower) for pat in META_BOOK_PATTERNS):
        return None

    # Reject incomplete dangling header prompts e.g. "Observe the part of thermometer shown in Fig. 7.8 and answer the following questions:"
    if re.search(r'\b(?:and\s+answer\s+the\s+following\s+questions?|the\s+following\s+questions?|given\s+below|answer\s+the\s+questions?\s+below)\s*[:\.\s]*$', raw_q_text, re.IGNORECASE):
        if not any(marker in raw_q_text for marker in ["(a)", "(i)", "1.", "?"]) or len(raw_q_text.split()) < 10:
            return None

    if "alternative concept" in q_lower or "null condition" in q_lower or "secondary effect" in q_lower:
        return None

    dummy_titles = [
        "long", "long answer", "long answer question", "long answer questions", "laq",
        "short", "short answer", "saq", "vsaq", "mcq", "multiple choice", "objective",
        "case study", "numerical", "assertion reason", "true or false", "fill in the blank",
        "section a", "section b", "section c", "section d", "section e",
        "question", "questions", "answer the following", "solve", "evaluate", "explain"
    ]
    clean_q_low = raw_q_text.lower().strip('. :-\t\n')
    if clean_q_low in dummy_titles or len(raw_q_text) < 15 or len(raw_q_text.split()) < 3:
        topic_sug = str(q.get("topic_suggested") or meta.get("subject") or "").strip()
        if topic_sug and topic_sug.lower() not in ["general", "none", "null", "curriculum"]:
            if "long" in default_type.lower() or "8m" in default_type.lower() or "5m" in default_type.lower():
                raw_q_text = f"Explain the fundamental concepts, experimental observations, and core principles of {topic_sug} in detail."
            elif "saq" in default_type.lower() or "2m" in default_type.lower() or "3m" in default_type.lower():
                raw_q_text = f"State the key principles and importance of {topic_sug}."
            else:
                raw_q_text = f"Explain the key characteristics of {topic_sug}."
        else:
            return None

    # Ensure question ends with a clean terminal punctuation mark if ending with number/formula
    if not any(raw_q_text.rstrip().endswith(ch) for ch in ['?', '.', ':', '"', "'", ')', ']', '_', '}']):
        if len(raw_q_text.split()) >= 4:
            raw_q_text = raw_q_text.rstrip() + "."
        else:
            return None

    # Clean question text
    q_text = clean_human_readable_text(raw_q_text)

    # 1. Bilingual cleanup for CBSE / ICSE / ISC and STEM / General subjects
    if not is_lang_subject:
        # If question contains non-Latin text (e.g. Hindi/Bengali), extract the English part
        if "/" in q_text:
            has_indic_script = bool(re.search(r'[\u0900-\u0D7F\u0E00-\u0E7F]', q_text))
            has_math_slash = bool(re.search(r'\b\d+\s*/\s*\d+\b|\b[a-zA-Z]{1,4}\s*/\s*[a-zA-Z0-9]{1,4}\b', q_text))

            if has_indic_script and not has_math_slash:
                parts = [p.strip() for p in q_text.split("/") if p.strip()]
                for p in parts:
                    ascii_chars = sum(1 for c in p if ord(c) < 128)
                    if ascii_chars / max(len(p), 1) > 0.80 and len(p.split()) >= 2:
                        q_text = p
                        break

        # Remove leading Question markers like 'Q1. ', '1. ', 'Question 1: '
        q_text = re.sub(r'^(?:Q(?:uestion)?\.?\s*\d+[\.\:\)]|\d+[\.\)])\s*', '', q_text).strip()

    # Strip artificial prompt bleed prefixes (e.g., 'Explain the principle: ')
    q_text = re.sub(r'^(?:explain\s+the\s+principle\s*[:\-–—]\s*|state\s+the\s+concept\s+of\s*[:\-–—]\s*|explain\s+the\s+concept\s+of\s*[:\-–—]\s*)', '', q_text, flags=re.IGNORECASE).strip()

    # 2. Extract embedded marks tag in question text e.g. [1 Mark], [2 Marks], [3M], (4), [5]
    mark_match = re.search(r'[\(\[]\s*(\d+)\s*(?:Marks?|M)?\s*[\)\]]$', q_text, re.IGNORECASE)
    extracted_marks = None
    if mark_match:
        try:
            extracted_marks = int(mark_match.group(1))
            q_text = q_text[:mark_match.start()].strip()
        except Exception:
            extracted_marks = None

    # Handle unparsed JSON string inside correct_answer
    raw_corr = str(q.get("correct_answer") or "").strip()
    if raw_corr and (raw_corr.startswith("{") or '{"' in raw_corr or '"explanation":' in raw_corr):
        try:
            parsed_corr = json.loads(raw_corr)
            if isinstance(parsed_corr, dict):
                raw_corr = str(parsed_corr.get("answer") or parsed_corr.get("correct_answer") or raw_corr)
                if not q.get("explanation") and parsed_corr.get("explanation"):
                    q["explanation"] = str(parsed_corr.get("explanation"))
        except Exception:
            json_ans_m = re.search(r'"(?:answer|correct_answer)"\s*:\s*"([^"]+)"', raw_corr)
            if json_ans_m:
                raw_corr = json_ans_m.group(1)

    corr = clean_human_readable_text(raw_corr)

    # Smart Sentence Merger: If question text is just an instruction and correct_answer has the sentence/blank
    if re.search(r"^(?:(?:A|B|C|D|Q\d+)?\.?\s*)?(?:complete\s+the\s+sentence|fill\s+in\s+the\s+blank|choose\s+the\s+correct\s+word|state\s+whether|give\s+one\s+word|change\s+the\s+tense)", q_text, re.IGNORECASE):
        if "_" in corr or ("(" in corr and ")" in corr and len(corr.split()) >= 3):
            q_text = f"{q_text.rstrip('. :')}: {corr}"
            bracket_match = re.search(r'\(([^)]+)\)', corr)
            if bracket_match:
                corr = bracket_match.group(1).strip()
            else:
                corr = "Refer to the completed sentence."

    # Strip leaked trailing answer blocks per line (e.g. '...measured by a thermometer (i) temperature (ii) clinical' or 'Ans: ...')
    lines = q_text.splitlines()
    cleaned_lines = []
    extracted_leaks = []
    for line in lines:
        l = line.strip()
        m = re.search(r'^(.*?)(\s*\(i\)\s*[a-zA-Z0-9_\-\s]+\s*\(ii\)\s*[a-zA-Z0-9_\-\s]+[\.\?\s]*|\s+Ans(?:wer)?\s*[:\-–—].*)$', l, re.IGNORECASE)
        if m:
            cleaned_body = m.group(1).strip()
            leak = m.group(2).strip()
            cleaned_lines.append(cleaned_body)
            extracted_leaks.append(leak)
        else:
            cleaned_lines.append(l)

    q_text = "\n".join(cleaned_lines)
    extracted_leak = " ".join(extracted_leaks).strip()
    if extracted_leak and (not corr or corr.strip().lower() in ["i", "ii", "iii", "iv", "a", "b", "c", "d", "none", "n/a", "null"]):
        corr = clean_human_readable_text(extracted_leak)

    # Auto-heal Fill in the Blank questions to guarantee a clean '________' placeholder
    q_text = heal_fill_in_the_blank_question(q_text, corr)

    is_fill_in_the_blank = bool(re.search(r'\b(?:fill\s+in\s+the\s+blanks?|complete\s+the\s+(?:sentence|statement|blank)|choose\s+the\s+correct\s+word|state\s+whether|true\s+or\s+false)\b', q_text, re.IGNORECASE)) or "________" in q_text

    raw_type = str(q.get("type") or default_type or "MCQ").strip().upper()
    if is_fill_in_the_blank:
        resolved_type = "OBJECTIVE"
        default_m = 1
    elif "CASE" in raw_type:
        resolved_type = "CASE STUDY"
        default_m = 4
    elif "ASSERT" in raw_type:
        resolved_type = "ASSERTION REASON"
        default_m = 1
    elif "LONG EVALUATIVE" in raw_type or "8M" in raw_type:
        resolved_type = "LONG EVALUATIVE"
        default_m = 8
    elif "LONG" in raw_type or "LAQ" in raw_type:
        resolved_type = "LONG ANSWER"
        default_m = 5
    elif "SHORT ANSWER (3M)" in raw_type or "3M" in raw_type or int(q.get("marks") or 0) == 3:
        resolved_type = "SHORT ANSWER (3M)"
        default_m = 3
    elif "NUM" in raw_type:
        resolved_type = "NUMERICAL"
        default_m = int(q.get("marks") or 3)
    elif "SAQ" in raw_type or "SHORT" in raw_type:
        resolved_type = "SAQ"
        default_m = 2
    elif raw_type in ["TRUE_FALSE", "TRUE/FALSE", "TF", "OBJECTIVE", "ONE_WORD", "FILL_IN"]:
        resolved_type = "OBJECTIVE"
        default_m = 1
    else:
        resolved_type = "MCQ"
        default_m = 1

    # Assigned marks
    raw_m = q.get("marks")
    try:
        marks = int(raw_m if raw_m and str(raw_m).isdigit() else (extracted_marks or default_m))
    except (ValueError, TypeError):
        marks = extracted_marks or default_m

    # Clean options
    q_opts = q.get("options")
    clean_opts: List[str] = []
    if resolved_type in ["MCQ", "ASSERTION REASON"]:
        if isinstance(q_opts, list):
            for opt in q_opts:
                opt_str = clean_human_readable_text(opt)
                if opt_str:
                    clean_opts.append(opt_str)
        elif isinstance(q_opts, dict):
            clean_opts = [f"{k}) {clean_human_readable_text(v)}" for k, v in q_opts.items()]

        # Clean bilingual slash in options (e.g. "कोयला / Coal" -> "Coal")
        if not is_lang_subject:
            clean_opt_list = []
            for opt_val in clean_opts:
                if "/" in opt_val:
                    opt_parts = [p.strip() for p in opt_val.split("/") if p.strip()]
                    eng_opt = None
                    for op in opt_parts:
                        ascii_chars = sum(1 for c in op if ord(c) < 128)
                        if ascii_chars / max(len(op), 1) > 0.70:
                            eng_opt = op
                            break
                    clean_opt_list.append(eng_opt or opt_val)
                else:
                    clean_opt_list.append(opt_val)
            clean_opts = clean_opt_list

        # Clean compound glued questions in MCQs e.g. "What is X? What is Y?" with options "A) x_val, y_val"
        q_parts = [p.strip() for p in re.findall(r'[^?]+\?', q_text) if p.strip()]
        if len(q_parts) >= 2 and clean_opts and all(',' in opt for opt in clean_opts):
            q_text = q_parts[0]
            atomic_opts = []
            for opt in clean_opts:
                m = re.match(r'^([A-D]\)\s*)([^,]+),\s*(.+)$', opt)
                if m:
                    atomic_opts.append(f"{m.group(1)}{m.group(2).strip()}")
                else:
                    atomic_opts.append(opt.split(',')[0].strip())
            clean_opts = atomic_opts
            if ',' in corr:
                corr = corr.split(',')[0].strip()

        # Decontaminate concatenated 'explanation:' / 'reason:' in options
        if clean_opts:
            decontaminated_opts = []
            for opt_val in clean_opts:
                cleaned_opt = re.sub(r'\s*(?:explanation|reason|justification)\s*[:\-–—].*$', '', opt_val, flags=re.IGNORECASE).strip()
                if cleaned_opt:
                    decontaminated_opts.append(cleaned_opt)
            clean_opts = decontaminated_opts

        # If question ends with 'Explain.' or 'Give reasons.' and was made an MCQ with synthetic choices:
        if resolved_type in ["MCQ", "OBJECTIVE"] and re.search(r'\b(?:explain|give\s+reasons?|state\s+why|why\s+or\s+why\s+not)\s*[\?\.\:]*$', q_text, re.IGNORECASE):
            resolved_type = "SAQ"
            marks = 2
            clean_opts = []

        # Check for dummy options
        is_dummy = any(re.match(r"^(?:[A-D]\s*[\)\.\:\-]\s*)?option\s*[A-D]?$", opt, re.IGNORECASE) for opt in clean_opts)
        if len(clean_opts) < 2 or is_dummy:
            if resolved_type not in ["SAQ", "SHORT ANSWER (3M)", "LONG ANSWER"]:
                resolved_type = "OBJECTIVE"
            clean_opts = []
        else:
            # Ensure standard prefix A), B), C), D)
            formatted_opts = []
            for opt_idx, opt_val in enumerate(clean_opts[:4]):
                prefix = chr(65 + opt_idx)  # A, B, C, D
                if not re.match(r"^[A-D][\)\.\:\s]", opt_val, re.IGNORECASE):
                    formatted_opts.append(f"{prefix}) {opt_val}")
                else:
                    formatted_opts.append(opt_val)
            clean_opts = formatted_opts
    else:
        clean_opts = []

    # Clean correct_answer
    if resolved_type in ["MCQ", "ASSERTION REASON"] and clean_opts:
        if corr:
            # Check if corr is a letter like 'A' or 'B' or '(A)'
            match_letter = re.match(r"^[\(]?([A-D])[\)\.\:\s]?$", corr.strip(), re.IGNORECASE)
            if match_letter:
                target_letter = match_letter.group(1).upper()
                target_idx = ord(target_letter) - 65
                if 0 <= target_idx < len(clean_opts):
                    opt_raw = clean_opts[target_idx]
                    corr = opt_raw.split(")", 1)[-1].strip() if ")" in opt_raw else opt_raw
                else:
                    corr = clean_opts[0].split(")", 1)[-1].strip()
            else:
                # corr contains text: match it against options
                matched_text = None
                corr_clean = corr.lower().strip()
                for opt_str in clean_opts:
                    opt_body = opt_str.split(")", 1)[-1].strip()
                    if corr_clean == opt_body.lower() or (len(corr_clean) > 3 and corr_clean in opt_body.lower()) or (len(opt_body) > 3 and opt_body.lower() in corr_clean):
                        matched_text = opt_body
                        break
                if matched_text:
                    corr = matched_text
                else:
                    # If corr does not match ANY of the options:
                    # Check if this question is actually a descriptive/passage question that AI wrongly formatted as MCQ
                    is_descriptive_q = bool(re.search(r'\b(?:rewrite|explain|describe|what is the life cycle|state the|why do|how does|give reason|summarize|list the)\b', q_text.lower()))
                    is_long_corr = len(corr.split()) >= 4 or len(corr) > 30
                    if is_descriptive_q or is_long_corr:
                        # Auto-convert to SAQ or Objective with authentic descriptive answer preserved and unrelated options cleared
                        resolved_type = "SAQ" if marks >= 2 else "OBJECTIVE"
                        clean_opts = []
                    else:
                        # If authentic short MCQ, lock corr to the first option
                        corr = clean_opts[0].split(")", 1)[-1].strip() if clean_opts else corr
        else:
            corr = clean_opts[0].split(")", 1)[-1].strip() if clean_opts else ""

        # Smart Balanced MCQ Option Shuffling (randomizes correct option across A, B, C, D without altering answer fidelity)
        if resolved_type == "MCQ" and len(clean_opts) >= 2 and corr:
            raw_bodies = [re.sub(r'^[A-D]\s*[\)\.\:\-]\s*', '', opt).strip() for opt in clean_opts[:4]]
            corr_clean = corr.lower().strip()
            target_body = None
            for body in raw_bodies:
                if corr_clean == body.lower() or (len(corr_clean) > 2 and corr_clean in body.lower()) or (len(body) > 2 and body.lower() in corr_clean):
                    target_body = body
                    break
            if not target_body:
                target_body = raw_bodies[0]

            has_both_ab = any(re.search(r'\bboth\s+(?:\(?[a-d]\)?\s+and\s+\(?[a-d]\)?|[a-d]\s*,\s*[a-d])\b', b, re.IGNORECASE) for b in raw_bodies)
            has_all_none = any(re.search(r'^(?:all|none)\s+of\s+(?:the\s+above|these)$', b.strip(), re.IGNORECASE) for b in raw_bodies)

            import random
            if has_both_ab:
                # Positional references like 'Both A and B' must not be shuffled
                pass
            elif has_all_none:
                # Keep 'All/None of the above' fixed at the last option D, shuffle the remaining options
                all_none_idx = next(i for i, b in enumerate(raw_bodies) if re.search(r'^(?:all|none)\s+of\s+(?:the\s+above|these)$', b.strip(), re.IGNORECASE))
                all_none_item = raw_bodies.pop(all_none_idx)
                random.shuffle(raw_bodies)
                raw_bodies.append(all_none_item)
            else:
                random.shuffle(raw_bodies)

            clean_opts = [f"{chr(65 + i)}) {body}" for i, body in enumerate(raw_bodies)]
            corr = target_body

    # Determine calibrated difficulty (Supports 'easy', 'simple', 'medium', 'hard')
    raw_diff = str(q.get("difficulty") or target_diff or "easy").strip().lower()
    if raw_diff in ["easy", "simple"]:
        final_difficulty = "easy"
    elif raw_diff == "hard":
        final_difficulty = "hard"
    else:
        final_difficulty = "medium"

    # Clean explanation
    raw_expl = q.get("explanation")
    clean_expl = clean_human_readable_text(raw_expl)
    # Filter out synthetic boilerplate/dummy phrases
    dummy_expl_triggers = [
        "derived directly from curriculum document",
        "key concept regarding",
        "standard model solution",
        "conceptual principle for",
        "comprehensive curriculum solution covering",
        "core pedagogical solution",
        "concept verification for"
    ]
    if not clean_expl or any(trig in clean_expl.lower() for trig in dummy_expl_triggers) or clean_expl.strip() in [".", "-", "none", "null"]:
        if resolved_type in ["MCQ", "ASSERTION REASON"] and clean_opts and corr:
            clean_expl = f"The correct answer is '{corr}' based on the curriculum concepts in {meta.get('title', 'the topic')}."
        elif corr and len(corr) > 15 and not any(trig in corr.lower() for trig in dummy_expl_triggers):
            clean_expl = f"Explanation:\n{corr}"
        else:
            clean_expl = f"Based on {meta.get('title', meta.get('subject', 'the curriculum'))}, this concept is established in {meta.get('subject', 'the topic')}."

    # Assigned marks
    raw_m = q.get("marks")
    try:
        marks = int(raw_m if raw_m and str(raw_m).isdigit() else (extracted_marks or default_m))
    except (ValueError, TypeError):
        marks = extracted_marks or default_m

    # Subject-aware validation for NUMERICAL:
    sub_lower = str(meta.get("subject") or "").lower()
    non_num_subjects = ["biology", "history", "geography", "civics", "political science", "english", "hindi", "bengali", "sanskrit", "social science", "social studies", "botany", "zoology", "physical education", "sports", "yoga"]
    is_calculation = bool(re.search(r'\d+\s*[\+\-\*\/=]\s*\d+|\bcalculate\b|\bfind the value\b|\bsolve\b|\bhow many\b|\bmass of\b', q_text.lower()))
    if resolved_type == "NUMERICAL" and (any(ns in sub_lower for ns in non_num_subjects) or not is_calculation):
        if marks >= 5:
            resolved_type = "LONG ANSWER"
        elif marks == 4:
            resolved_type = "CASE STUDY"
        elif marks == 3:
            resolved_type = "SHORT ANSWER (3M)"
        elif marks == 2:
            resolved_type = "SAQ"
        else:
            resolved_type = "OBJECTIVE"

    # Re-calibrate question type by marks if generic
    is_expl_q = bool(re.search(r'\b(?:explain|give\s+reasons?|state\s+why|why\s+or\s+why\s+not)\s*[\?\.\:]*$', q_text, re.IGNORECASE))
    if is_fill_in_the_blank:
        resolved_type = "OBJECTIVE"
    elif is_expl_q or resolved_type == "SAQ":
        resolved_type = "SAQ"
        if marks < 2:
            marks = 2
    elif marks == 1 and resolved_type not in ["MCQ", "ASSERTION REASON"]:
        resolved_type = "OBJECTIVE"
    elif marks == 2 and resolved_type not in ["MCQ", "ASSERTION REASON", "OBJECTIVE"]:
        resolved_type = "SAQ"
    elif marks == 3 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "SHORT ANSWER (3M)"
    elif marks == 4 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "CASE STUDY"
    elif marks == 5 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "LONG ANSWER"
    elif marks >= 8:
        resolved_type = "LONG EVALUATIVE"

    # Fallback for empty, broken, or single-character placeholder correct_answer in descriptive / objective questions
    if not corr or corr.strip().lower() in ["model solution", "n/a", "none", "null", "standard model solution", "i", "ii", "iii", "iv", "a", "b", "c", "d"]:
        if extracted_leak:
            corr = clean_human_readable_text(extracted_leak)
        elif clean_expl and len(clean_expl) > 5 and not clean_expl.startswith("Core pedagogical solution"):
            corr = clean_expl
        elif clean_opts:
            corr = clean_opts[0].split(")", 1)[-1].strip()
        else:
            corr = f"Model solution: {clean_expl if clean_expl else q_text}"

    # For 5-mark long answers, ensure answer is enriched with explanation points if too brief
    if marks >= 5 and resolved_type in ["LONG ANSWER", "LONG EVALUATIVE"]:
        if len(corr.split()) < 25 and clean_expl and not clean_expl.startswith("Core pedagogical solution"):
            corr = f"{corr}\n\nDetailed Breakdown & Key Points:\n{clean_expl}"

    raw_topic = clean_human_readable_text(str(q.get("topic_suggested") or "").strip())
    sub_name = str(meta.get("subject") or "").strip()
    title_name = str(meta.get("title") or "").strip()
    det_topics = meta.get("detected_topics") or []

    generic_terms = {sub_name.lower(), "general", "science", "biology", "mathematics", "math", "maths", "physics", "chemistry", "social science", "social studies", "english", "hindi"}
    if not raw_topic or raw_topic.lower() in generic_terms:
        if det_topics and len(det_topics) > 0:
            resolved_topic = det_topics[index % len(det_topics)]
        elif title_name and title_name.lower() not in generic_terms:
            resolved_topic = title_name
        else:
            resolved_topic = "Core Concepts"
    else:
        # Canonical Topic Clustering: map to closest Pass 1 canonical topic if overlap exists
        canonical_match = _find_best_canonical_topic(raw_topic, det_topics, threshold=0.40) if det_topics else None
        resolved_topic = canonical_match if canonical_match else raw_topic

    raw_chapter = str(q.get("chapter_title") or q.get("chapter_name") or "").strip()
    if raw_chapter:
        clean_chap = re.sub(r'^(?:Chapter|Unit|Lesson)\s*\d+[\s\:\.\-–—]*', '', raw_chapter, flags=re.IGNORECASE).strip()
    else:
        clean_chap = title_name

    return {
        "id": f"gen_{index + 1}",
        "question": q_text,
        "type": resolved_type,
        "difficulty": final_difficulty,
        "marks": marks,
        "options": clean_opts,
        "correct_answer": corr,
        "explanation": clean_expl,
        "topic_suggested": resolved_topic,
        "chapter_name": clean_chap or title_name,
        "image_url": q.get("image_url") or q.get("imageUrl") or None,
    }


def extract_questions_from_document_text(
    cleaned_text: str,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    title: str,
    document_type: str = "textbook",
    target_q_count: Optional[int] = None,
    detected_topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Extracts all questions from curriculum document or question bank across all chunks without truncation."""
    meta = {
        "board": board,
        "classGrade": class_grade,
        "subject": subject,
        "title": title,
        "detected_topics": detected_topics or []
    }
    raw_questions: List[Dict[str, Any]] = []

    topics_guide = ""
    if detected_topics and isinstance(detected_topics, list):
        clean_dt = [t.strip() for t in detected_topics if t and t.strip() and t.strip().lower() != subject.lower()]
        if clean_dt:
            topics_guide = f"\n- Specific Sub-Topics for this Chapter (assign each question to one of these): {json.dumps(clean_dt)}"

    if document_type in ["old_question_paper", "question_bank"]:
        # QUESTION BANK / PYQ MODE: Extract 100% of all questions across chunks
        chunk_window = 12000
        overlap = 1000
        text_len = len(cleaned_text)

        chunks = []
        if text_len <= chunk_window:
            chunks = [cleaned_text]
        else:
            start = 0
            while start < text_len:
                end = min(start + chunk_window, text_len)
                chunks.append(cleaned_text[start:end])
                if end == text_len:
                    break
                start = end - overlap

        print(f"  [+] Extraction Strategy: Parsing {len(chunks)} text section(s) for complete Question Bank digitization...")

        system_prompt = OLD_QUESTION_PAPER_PROMPT
        def _process_qb_chunk(item):
            c_idx, c_text = item
            section_label = f"Section {c_idx + 1} of {len(chunks)}"
            user_prompt = f"""Target Details:
- Board: {board}
- Class/Grade: {class_grade}
- Subject: {subject}
- Chapter/Paper Title: {title}{topics_guide}
- Document Mode: {document_type}
- Section: {section_label}

--- DOCUMENT CONTENT ({section_label}) ---
{c_text}
--- END DOCUMENT CONTENT ---

CRITICAL INSTRUCTIONS:
1. Extract and digitize EVERY single question present in this text section without skipping any.
2. If there are Multiple Choice Questions (MCQ), extract all options ('A) ', 'B) ', 'C) ', 'D) ') and identify the correct option letter.
3. For Short Answer (2M or 3M), Case Studies (4M), Long Answer (5M or 8M), Numerical, Assertion Reason, or Objective questions, extract full question text and write accurate model solutions in 'correct_answer' and 'explanation'.
4. Extract all distinguishable questions present in this section without an artificial limit."""
            try:
                response_json = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.25, scenario="pdf_generation")
                q_list = response_json.get("questions", []) if isinstance(response_json, dict) else []
                if isinstance(q_list, list) and q_list:
                    print(f"    -> [{section_label}] Extracted {len(q_list)} question(s)")
                    return (c_idx, q_list)
            except Exception as e:
                logger.error(f"Error extracting questions from chunk {c_idx + 1}: {e}")
            return (c_idx, [])

        max_qb_workers = min(int(os.getenv("AI_MAX_PARALLEL_WORKERS")), len(chunks)) if len(chunks) > 1 else 1
        if max_qb_workers > 1:
            print(f"  • [CONCURRENT PARALLEL SYNTHESIS] Dispatching {len(chunks)} chunks across {max_qb_workers} worker threads...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_qb_workers) as executor:
                results = list(executor.map(_process_qb_chunk, enumerate(chunks)))
                for _, q_list in sorted(results, key=lambda x: x[0]):
                    raw_questions.extend(q_list)
        else:
            for item in enumerate(chunks):
                _, q_list = _process_qb_chunk(item)
                raw_questions.extend(q_list)

        # Fallback question detection if LLM returned 0 questions
        if not raw_questions:
            q_pattern = re.compile(r'(?i)(?:^|\n)(?:Q(?:uestion)?\.?\s*\d+|^\d+[\.\)])\s+(.+?)(?=(?:\n(?:Q(?:uestion)?\.?\s*\d+|^\d+[\.\)])|\Z))', re.DOTALL)
            matches = q_pattern.findall(cleaned_text)
            for m_idx, m_text in enumerate(matches[:40]):
                m_clean = m_text.strip()
                if len(m_clean) > 15:
                    raw_questions.append({
                        "question": m_clean[:300],
                        "type": "SAQ",
                        "difficulty": "medium",
                        "marks": 2,
                        "options": [],
                        "correct_answer": f"Standard curriculum solution for {title}.",
                        "explanation": f"Extracted from {filename}",
                        "topic_suggested": title or "Core Concepts",
                    })

    else:
        # UNLIMITED / EXHAUSTIVE TEXTBOOK & CURRICULUM SYNTHESIS (100% Full Document Coverage)
        system_prompt = TEXTBOOK_QUESTION_PROMPT
        text_len = len(cleaned_text)

        # 1. Check for explicit multi-chapter structure (e.g. Chapter 1, Chapter 2, Unit 1, Lesson 1...)
        chapter_regex = re.compile(
            r'(?:\n|\A)(?:CHAPTER|Chapter|UNIT|Unit|LESSON|Lesson|MODULE|Module)\s*[\-:]?\s*(\d+|[IVXLCDM]+)[\s\:\.\-–—]+([^\n]{3,80})',
            re.MULTILINE
        )
        detected_chap_matches = list(chapter_regex.finditer(cleaned_text))

        sections_to_process = []

        if len(detected_chap_matches) >= 2 and text_len > 18000:
            # Multi-chapter document: partition cleanly chapter by chapter
            print(f"  • [MULTI-CHAPTER BOOK] Detected {len(detected_chap_matches)} chapters inside '{filename}'. Processing every chapter sequentially...")
            for c_idx, match in enumerate(detected_chap_matches):
                start_p = match.start()
                end_p = detected_chap_matches[c_idx + 1].start() if (c_idx + 1 < len(detected_chap_matches)) else text_len
                chap_num = match.group(1).strip()
                chap_raw_name = match.group(2).strip()
                curr_chap_title = f"Chapter {chap_num}: {chap_raw_name}"
                chap_chunk = cleaned_text[start_p:end_p].strip()
                if len(chap_chunk) >= 400:
                    sections_to_process.append((curr_chap_title, chap_chunk))
        else:
            # Single-chapter or un-partitioned book: sliding window across 100% of text without truncation
            window_size = 12000
            overlap = 1000
            if text_len <= window_size:
                sections_to_process.append((f"{title} - Full Content", cleaned_text))
            else:
                start = 0
                sec_idx = 1
                while start < text_len:
                    end = min(start + window_size, text_len)
                    chunk_text = cleaned_text[start:end]
                    sec_title = f"{title} (Section {sec_idx})"
                    sections_to_process.append((sec_title, chunk_text))
                    if end == text_len:
                        break
                    start = end - overlap
                    sec_idx += 1

        print(f"  • [EXHAUSTIVE EXTRACTION] Processing {len(sections_to_process)} text section(s) spanning 100% of document ({text_len:,} chars)...")

        def _process_textbook_section(item):
            s_idx, (sec_name, sec_excerpt) = item
            user_prompt = f"""Target Details:
- Board: {board}
- Class/Grade: {class_grade}
- Subject: {subject}
- Chapter/Paper Title: {sec_name}{topics_guide}
- Section: {sec_name}
- Document Mode: {document_type}

--- DOCUMENT CONTENT ({sec_name}) ---
{sec_excerpt}
--- END DOCUMENT CONTENT ---

CRITICAL INSTRUCTIONS:
1. Exhaustively extract and synthesize ALL unique, high-yield, and pedagogically important examination questions (MCQ, SAQ 2M/3M, Case Study 4M, Long Answer 5M/8M, Numerical) covering EVERY major concept, definition, theorem, formula, and problem in this text section.
2. DO NOT artificially limit question count. Extract all high-value distinct questions present in this section without skipping important topics.
3. Ensure every question is complete, self-contained, and has an informative 'explanation' and accurate 'correct_answer'.
4. Assign each question's 'topic_suggested' to its specific sub-topic / conceptual heading."""
            try:
                response_json = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.30, scenario="pdf_generation")
                sec_questions = response_json.get("questions", []) if isinstance(response_json, dict) else []
                if isinstance(sec_questions, list) and sec_questions:
                    chap_clean_label = sec_name.split(" (Section")[0] if " (Section" in sec_name else sec_name
                    if ":" in chap_clean_label:
                        chap_clean_label = chap_clean_label.split(":", 1)[1].strip()
                    chap_clean_label = re.sub(r'^(?:Chapter|Unit|Lesson)\s*\d+[\s\:\.\-–—]*', '', chap_clean_label, flags=re.IGNORECASE).strip()

                    for sq in sec_questions:
                        if isinstance(sq, dict):
                            sq["chapter_title"] = chap_clean_label or sec_name
                            sq["chapter_name"] = chap_clean_label or sec_name
                    print(f"    -> [{sec_name}] Synthesized {len(sec_questions)} unique question(s)")
                    return (s_idx, sec_questions)
            except Exception as e:
                logger.error(f"Error synthesizing questions for {sec_name}: {e}")
            return (s_idx, [])

        max_sec_workers = min(int(os.getenv("AI_MAX_PARALLEL_WORKERS")), len(sections_to_process)) if len(sections_to_process) > 1 else 1
        if max_sec_workers > 1:
            print(f"  • [CONCURRENT PARALLEL SYNTHESIS] Processing {len(sections_to_process)} sections simultaneously across {max_sec_workers} threads...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_sec_workers) as executor:
                results = list(executor.map(_process_textbook_section, enumerate(sections_to_process)))
                for _, sec_q in sorted(results, key=lambda x: x[0]):
                    raw_questions.extend(sec_q)
        else:
            for item in enumerate(sections_to_process):
                _, sec_q = _process_textbook_section(item)
                raw_questions.extend(sec_q)

        # Fallback if all sections returned empty (e.g. LLM timeout)
        if not raw_questions and len(cleaned_text) > 200:
            try:
                sub_prompt = f"""Target Details:
- Board: {board}
- Class/Grade: {class_grade}
- Subject: {subject}
- Chapter/Paper Title: {title}
- Document Mode: {document_type}

--- DOCUMENT CONTENT ---
{cleaned_text[:8000]}
--- END DOCUMENT CONTENT ---

Extract all essential examination questions covering the primary concepts and formulas."""
                res_retry = mistral_client.generate_json(system_prompt, sub_prompt, temperature=0.25, scenario="pdf_generation")
                raw_questions = res_retry.get("questions", []) if isinstance(res_retry, dict) else []
            except Exception as e_retry:
                logger.warning(f"Secondary question extraction retry: {e_retry}")

    # Sanitize and deduplicate within extracted batch
    sanitized: List[Dict[str, Any]] = []
    seen_texts = set()

    for idx, q in enumerate(raw_questions):
        norm = sanitize_question_item(q, "MCQ", "medium", meta, idx)
        if not norm:
            continue

        clean_key = re.sub(r'[^a-zA-Z0-9]', '', norm["question"].lower())[:80]
        if clean_key in seen_texts and len(clean_key) > 10:
            continue
        seen_texts.add(clean_key)
        sanitized.append(norm)

    return sanitized


def _ensure_curriculum_tables(session: Session):
    """Ensures taxonomy & question tables exist for standalone/test SQLite execution."""
    is_sqlite = session.bind and session.bind.dialect.name == "sqlite"
    if is_sqlite:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS board_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS class_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS subject_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER,
                class_id INTEGER,
                subject_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS chapter_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER,
                chapter_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topic_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER,
                topic_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS question_type_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_type_name TEXT NOT NULL
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS difficulty_level_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                difficulty_level_name TEXT NOT NULL
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS question_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                question_type_id INTEGER DEFAULT 1,
                difficulty_level_id INTEGER DEFAULT 2,
                question TEXT NOT NULL,
                image_url VARCHAR(500) NULL,
                options TEXT,
                correct_answer TEXT NOT NULL,
                explanation TEXT,
                marks INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # Ensure image_url column exists in existing tables
        try:
            session.execute(text("ALTER TABLE question_master ADD COLUMN image_url VARCHAR(500) NULL"))
            session.commit()
        except Exception:
            session.rollback()

        # Seed defaults if empty
        try:
            if not session.execute(text("SELECT id FROM question_type_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO question_type_master (id, question_type_name) VALUES (1, 'MCQ'), (2, 'SAQ'), (3, 'NUMERICAL'), (4, 'OBJECTIVE')"))
            if not session.execute(text("SELECT id FROM difficulty_level_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO difficulty_level_master (id, difficulty_level_name) VALUES (1, 'easy'), (2, 'medium'), (3, 'hard')"))
            if not session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO board_master (id, board_name) VALUES (1, 'CBSE')"))
                session.execute(text("INSERT INTO class_master (id, class_name) VALUES (1, 'Class 10')"))
                session.execute(text("INSERT INTO subject_master (id, board_id, class_id, subject_name) VALUES (1, 1, 1, 'Physics'), (2, 1, 1, 'Science')"))
                session.execute(text("INSERT INTO chapter_master (id, subject_id, chapter_name) VALUES (1, 1, 'Electricity'), (2, 2, 'Science General')"))
                session.execute(text("INSERT INTO topic_master (id, chapter_id, topic_name) VALUES (1, 1, 'Ohm Law & Circuits'), (2, 2, 'General Science')"))
            session.commit()
        except Exception:
            session.rollback()


def resolve_or_create_chapter_and_topics(
    session: Session,
    *,
    board: str,
    class_grade: str,
    subject: str,
    title: Optional[str] = None,
    detected_topics: Optional[List[str]] = None,
    questions: Optional[List[dict]] = None,
    target_topic_id: Optional[int] = None,
) -> tuple[int, dict[str, int], int]:
    """Dynamically resolves or inserts the Subject, Chapter, and Canonical Sub-Topics
    extracted by LLM from the document and questions without hyper-fragmentation.
    Returns (chapter_id, topic_map, default_topic_id).
    """
    # 1. Lookup subject_id in subject_master
    sub_id = None
    try:
        sub_id = session.execute(
            text("""
                SELECT s.id 
                FROM subject_master s
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                WHERE LOWER(TRIM(b.board_name)) = LOWER(TRIM(:b))
                  AND (LOWER(TRIM(c.class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(:c)))
                  AND (LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:s)) OR (LOWER(TRIM(:s)) = 'science' AND LOWER(TRIM(s.subject_name)) IN ('physics', 'chemistry', 'biology', 'science')))
                ORDER BY s.id ASC
                LIMIT 1
            """),
            {"b": board, "c": class_grade, "s": subject}
        ).scalar()
    except Exception:
        pass

    # If subject not found, create it under matching board & class
    if not sub_id:
        try:
            b_id = session.execute(text("SELECT id FROM board_master WHERE LOWER(TRIM(board_name)) = LOWER(TRIM(:b)) LIMIT 1"), {"b": board}).scalar()
            c_id = session.execute(text("SELECT id FROM class_master WHERE LOWER(TRIM(class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(class_name, 'Class ', ''))) = LOWER(TRIM(:c)) LIMIT 1"), {"c": class_grade}).scalar()
            if b_id and c_id:
                session.execute(text("INSERT INTO subject_master (board_id, class_id, subject_name, is_active) VALUES (:bid, :cid, :sn, 1)"), {"bid": b_id, "cid": c_id, "sn": subject})
                session.commit()
                sub_id = session.execute(text("SELECT id FROM subject_master WHERE board_id = :bid AND class_id = :cid AND subject_name = :sn ORDER BY id DESC LIMIT 1"), {"bid": b_id, "cid": c_id, "sn": subject}).scalar()
        except Exception:
            session.rollback()

    if not sub_id:
        first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
        fallback_tid = int(first_topic or 1)
        return (1, {"default": fallback_tid}, fallback_tid)

    # 2. Match or create Chapter under this subject
    norm_title = _normalize_title(title or "")
    matched_chapter_id = None

    try:
        existing_chapters = session.execute(
            text("SELECT id, chapter_name FROM chapter_master WHERE subject_id = :sid AND is_active = 1"),
            {"sid": sub_id}
        ).fetchall()

        for ch_id, ch_name in existing_chapters:
            norm_ch = _normalize_title(ch_name)
            if norm_title and (norm_title == norm_ch or norm_title in norm_ch or norm_ch in norm_title):
                matched_chapter_id = ch_id
                break
    except Exception:
        pass

    if not matched_chapter_id:
        try:
            ch_name_to_create = title.strip() if title and len(title.strip()) > 2 else f"General {subject}"
            session.execute(
                text("INSERT INTO chapter_master (subject_id, chapter_name, is_active) VALUES (:sid, :cn, 1)"),
                {"sid": sub_id, "cn": ch_name_to_create}
            )
            session.commit()
            matched_chapter_id = session.execute(
                text("SELECT id FROM chapter_master WHERE subject_id = :sid AND chapter_name = :cn ORDER BY id DESC LIMIT 1"),
                {"sid": sub_id, "cn": ch_name_to_create}
            ).scalar()
        except Exception:
            session.rollback()

    if not matched_chapter_id:
        first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
        fallback_tid = int(first_topic or 1)
        return (1, {"default": fallback_tid}, fallback_tid)

    # 3. Gather canonical topics first from detected_topics, then cluster question topics into them
    canonical_topics_list: List[str] = []
    seen_cand = set()

    if detected_topics:
        for dt in detected_topics:
            if dt and str(dt).strip() and str(dt).strip().lower() != subject.lower():
                cand_str = str(dt).strip()
                norm_c = _normalize_title(cand_str)
                if norm_c and norm_c not in seen_cand:
                    seen_cand.add(norm_c)
                    canonical_topics_list.append(cand_str)

    if questions:
        for q in questions:
            ts = q.get("topic_suggested") or q.get("topic") or q.get("topicName") or q.get("topic_name")
            if ts and str(ts).strip():
                ts_clean = str(ts).strip()
                # Check if this maps to an existing canonical topic
                matched_can = _find_best_canonical_topic(ts_clean, canonical_topics_list, threshold=0.45)
                if not matched_can:
                    norm_t = _normalize_title(ts_clean)
                    if norm_t and norm_t not in seen_cand and len(ts_clean) >= 3:
                        seen_cand.add(norm_t)
                        canonical_topics_list.append(ts_clean)

    if not canonical_topics_list:
        canonical_topics_list = [title or f"{subject} Core Concepts"]

    # 4. Fetch existing topics under this chapter
    topic_map: dict[str, int] = {}
    raw_topic_list = []
    try:
        existing_topic_rows = session.execute(
            text("SELECT id, topic_name FROM topic_master WHERE chapter_id = :chid AND is_active = 1"),
            {"chid": matched_chapter_id}
        ).fetchall()

        for tid, tname in existing_topic_rows:
            norm_k = _normalize_title(tname)
            if norm_k:
                topic_map[norm_k] = int(tid)
            raw_topic_list.append((int(tid), tname))
    except Exception:
        pass

    # 5. Insert missing canonical topics into topic_master (with fuzzy deduplication)
    for t_name in canonical_topics_list:
        norm_k = _normalize_title(t_name)
        matched_existing_tid = None
        for ex_norm, ex_tid in topic_map.items():
            if norm_k == ex_norm or (len(norm_k) > 4 and (norm_k in ex_norm or ex_norm in norm_k)):
                matched_existing_tid = ex_tid
                break

        # Also check against raw topic list via token overlap
        if not matched_existing_tid and raw_topic_list:
            existing_names = [t[1] for t in raw_topic_list]
            best_ex = _find_best_canonical_topic(t_name, existing_names, threshold=0.50)
            if best_ex:
                for tid, ex_name in raw_topic_list:
                    if ex_name == best_ex:
                        matched_existing_tid = tid
                        break

        if matched_existing_tid:
            topic_map[norm_k] = matched_existing_tid
        else:
            try:
                session.execute(
                    text("INSERT INTO topic_master (chapter_id, topic_name, is_active) VALUES (:chid, :tn, 1)"),
                    {"chid": matched_chapter_id, "tn": t_name.strip()[:150]}
                )
                session.commit()
                new_tid = session.execute(
                    text("SELECT id FROM topic_master WHERE chapter_id = :chid AND topic_name = :tn ORDER BY id DESC LIMIT 1"),
                    {"chid": matched_chapter_id, "tn": t_name.strip()[:150]}
                ).scalar()
                if new_tid:
                    topic_map[norm_k] = int(new_tid)
                    raw_topic_list.append((int(new_tid), t_name))
            except Exception:
                session.rollback()

    # Determine default topic_id
    default_topic_id = None
    if target_topic_id and target_topic_id in topic_map.values():
        default_topic_id = int(target_topic_id)
    elif raw_topic_list:
        default_topic_id = raw_topic_list[0][0]
    elif topic_map:
        default_topic_id = next(iter(topic_map.values()))
    else:
        first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
        default_topic_id = int(first_topic or 1)

    return (matched_chapter_id, topic_map, default_topic_id)


def match_question_to_topic_id(
    topic_map: dict[str, int],
    question_dict: dict,
    default_topic_id: int
) -> int:
    """Matches an individual question to its exact topic_id based on topic_suggested, topic, or question keywords."""
    if not topic_map:
        return default_topic_id

    # 1. Direct explicit topic_id if valid
    explicit_tid = question_dict.get("topic_id") or question_dict.get("topicId")
    if explicit_tid:
        try:
            tid_int = int(explicit_tid)
            if tid_int in topic_map.values():
                return tid_int
        except Exception:
            pass

    # 2. Match question's topic_suggested
    q_topic = (
        question_dict.get("topic_suggested")
        or question_dict.get("topic")
        or question_dict.get("topicName")
        or question_dict.get("topic_name")
        or ""
    )
    if q_topic:
        norm_qt = _normalize_title(str(q_topic))
        if norm_qt in topic_map:
            return topic_map[norm_qt]

        # Partial substring match
        for k, tid in topic_map.items():
            if k and (k in norm_qt or norm_qt in k):
                return tid

    # 3. Match against question text keywords
    q_text = _normalize_title(str(question_dict.get("question") or ""))
    if q_text:
        for k, tid in topic_map.items():
            if len(k) >= 5 and k in q_text:
                return tid

    return default_topic_id


def resolve_subject_topic_id(
    session: Session,
    board: str,
    class_grade: str,
    subject: str,
    target_topic_id: Optional[int] = None,
    title: Optional[str] = None,
    detected_topics: Optional[List[str]] = None,
) -> int:
    """Backward-compatible helper: resolves a default topic_id."""
    _, _, default_tid = resolve_or_create_chapter_and_topics(
        session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        detected_topics=detected_topics,
        target_topic_id=target_topic_id,
    )
    return default_tid


def process_curriculum_document_pipeline(
    session: Session,
    file_bytes: bytes,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    question_count: Optional[int] = None,
    target_topic_id: Optional[int] = None,
    uploaded_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Executes the complete 5-step processing pipeline with real-time terminal output."""
    _print_separator(f"PIPELINE START: {filename}", TermColors.MAGENTA)

    # -------------------------------------------------------------------------
    # STEP 1: DATA READ & TEXT EXTRACTION
    # -------------------------------------------------------------------------
    _print_step_header(1, "DATA READ & EXTRACTION", TermColors.CYAN)
    ext = document_processor.validate_upload(filename, len(file_bytes))
    raw_text = document_processor.extract_text(file_bytes, ext)
    cleaned_text = document_processor.clean_text(raw_text)

    char_count = len(cleaned_text)
    word_count = len(cleaned_text.split())
    line_count = len(cleaned_text.splitlines())

    print(f"  • File Name       : {TermColors.BOLD}{filename}{TermColors.END}")
    print(f"  • File Type       : .{ext.upper()} ({len(file_bytes) / 1024:.1f} KB)")
    print(f"  • Target Config   : Board=[{board}] | Class=[{class_grade}] | Subject=[{subject}]")
    print(f"  • Document Mode   : {TermColors.GREEN}{document_type.upper()}{TermColors.END}")
    print(f"  • Text Extracted  : {TermColors.BOLD}{char_count:,}{TermColors.END} chars | {word_count:,} words | {line_count:,} lines")

    if not cleaned_text.strip():
        raise ValueError("Failed to extract readable text from the uploaded document.")

    # -------------------------------------------------------------------------
    # STEP 2: SHORT CONTEXTUAL ANALYSIS
    # -------------------------------------------------------------------------
    _print_step_header(2, "SHORT CONTEXTUAL ANALYSIS", TermColors.YELLOW)
    analysis = perform_contextual_analysis(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        document_type=document_type,
        session=session,
    )
    title = analysis.get("title", filename)
    summary = analysis.get("summary", "")
    detected_topics = analysis.get("detected_topics", [subject])
    est_diff = analysis.get("estimated_difficulty", "medium")
    detected_subject = analysis.get("detected_subject")

    if not detected_subject or detected_subject == "Science":
        meta_detected = document_processor.detect_curriculum_metadata(cleaned_text[:6000])
        specific_sub = meta_detected.get("subject")
        if specific_sub and specific_sub != "Science":
            detected_subject = specific_sub
        elif not detected_subject:
            detected_subject = specific_sub or subject

    # -------------------------------------------------------------------------
    # VALIDATION GATE: Check Subject Content Compatibility with Dropdown Target
    # -------------------------------------------------------------------------
    if detected_subject and not document_processor.is_subject_compatible(subject, detected_subject, class_grade):
        print(f"  • [AUTO-RECONCILED] Cross-disciplinary content '{detected_subject}' aligned to Admin target subject '{subject}'.")
        detected_subject = subject

    # Determine calibrated question count (20-30 questions per document/chapter)
    rec_q = analysis.get("recommended_question_count")
    if question_count and 15 <= int(question_count) <= 35:
        target_q_count = int(question_count)
    elif rec_q and isinstance(rec_q, (int, float)) and 15 <= int(rec_q) <= 35:
        target_q_count = int(rec_q)
    else:
        # Dynamic calibration based on chapter text volume
        if char_count > 10000:
            target_q_count = 25
        elif char_count > 5000:
            target_q_count = 20
        else:
            target_q_count = 15

    print(f"  • Inferred Title  : {TermColors.BOLD}{title}{TermColors.END}")
    print(f"  • Inferred Subject: {TermColors.BOLD}{detected_subject or subject}{TermColors.END} (Target: {subject})")
    print(f"  • Detected Topics : {', '.join(detected_topics)}")
    print(f"  • Est. Difficulty : {est_diff.capitalize()}")
    print(f"  • Target Questions: {TermColors.BOLD}{target_q_count}{TermColors.END} (Comprehensive 20-30 per Chapter)")
    print(f"  • Overview Summary: {TermColors.CYAN}{summary}{TermColors.END}")

    # -------------------------------------------------------------------------
    # STEP 3: QUESTION DETECTION & EXTRACTION
    # -------------------------------------------------------------------------
    _print_step_header(3, f"QUESTION DETECTION & EXTRACTION ({document_type.upper()})", TermColors.BLUE)
    final_questions = extract_questions_from_document_text(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        document_type=document_type,
        target_q_count=target_q_count,
        detected_topics=detected_topics,
    )

    # 3.5 In-Memory Diagram Extraction & Smart Context-Verified Linking
    diag_metrics = {}
    linked_diagrams_count = 0
    if ext == "pdf":
        try:
            diagram_pool = document_processor.extract_pdf_diagrams(file_bytes, max_diagrams=150)
            diag_metrics = getattr(diagram_pool, "metrics", {})
            linked_diagrams_count = assign_diagrams_to_questions(
                questions=final_questions,
                diagram_pool=diagram_pool,
                subject=subject,
                filename=filename,
                file_bytes=file_bytes,
            )
        except Exception as diag_err:
            logger.warning(f"Diagram extraction notice: {diag_err}")

    # Print comprehensive quality & yield audit in terminal
    print_extraction_quality_metrics(
        raw_text_chars=len(raw_text),
        cleaned_text_chars=char_count,
        diag_metrics=diag_metrics,
        linked_diagrams_count=linked_diagrams_count,
        total_questions=len(final_questions),
        filename=filename,
    )

    # -------------------------------------------------------------------------
    # STEP 4: PREPARE JSON SCHEMA OBJECTS
    # -------------------------------------------------------------------------
    _print_step_header(4, "JSON SCHEMA PREPARATION & VALIDATION", TermColors.MAGENTA)
    # Type & Difficulty Breakdown
    type_counts: Dict[str, int] = {}
    diff_counts: Dict[str, int] = {}
    for q in final_questions:
        type_counts[q["type"]] = type_counts.get(q["type"], 0) + 1
        diff_counts[q["difficulty"]] = diff_counts.get(q["difficulty"], 0) + 1

    print(f"  • Total Validated : {TermColors.BOLD}{len(final_questions)}{TermColors.END} questions matching schema")
    print(f"  • Type Breakdown  : {json.dumps(type_counts)}")
    print(f"  • Diff Breakdown  : {json.dumps(diff_counts)}")
    if final_questions:
        sample_q = final_questions[0]
        print(f"  • Sample JSON Schema Sample:")
        print(f"    - Question : {sample_q['question'][:80]}...")
        print(f"    - Type     : {sample_q['type']} | Marks: {sample_q['marks']} | Diff: {sample_q['difficulty']}")
        print(f"    - Answer   : {sample_q['correct_answer']}")

    # -------------------------------------------------------------------------
    # STEP 5: DATABASE INSERTION (question_master + documents + ChromaDB)
    # -------------------------------------------------------------------------
    _print_step_header(5, "DATABASE INSERTION & VECTOR INDEXING", TermColors.GREEN)

    _ensure_curriculum_tables(session)

    # 5.1 Resolve or dynamically create Chapter & ALL Sub-Topics in topic_master
    matched_chapter_id, topic_map, default_topic_id = resolve_or_create_chapter_and_topics(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        detected_topics=detected_topics,
        questions=final_questions,
        target_topic_id=target_topic_id,
    )

    # Preload types and diff lookup dicts
    types_map = {
        r[0].upper(): r[1]
        for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
    }
    diffs_map = {
        r[0].lower(): r[1]
        for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
    }

    # 5.2 Insert Questions into question_master with per-question dynamic topic_id
    inserted_questions_count = 0
    updated_questions_count = 0

    for q in final_questions:
        q_topic_id = match_question_to_topic_id(topic_map, q, default_topic_id)

        q_type_upper = str(q.get("type", "MCQ")).upper()
        q_type_id = types_map.get(q_type_upper)
        if not q_type_id:
            if "CASE" in q_type_upper:
                q_type_id = types_map.get("CASE STUDY", types_map.get("SAQ", 2))
            elif "ASSERT" in q_type_upper:
                q_type_id = types_map.get("ASSERTION REASON", types_map.get("MCQ", 1))
            elif "LONG" in q_type_upper:
                q_type_id = types_map.get("LONG ANSWER", types_map.get("LONG EVALUATIVE (8M)", 3))
            elif "SHORT" in q_type_upper or "SAQ" in q_type_upper:
                if int(q.get("marks", 2)) == 3:
                    q_type_id = types_map.get("SHORT ANSWER (3M)", types_map.get("SAQ", 2))
                else:
                    q_type_id = types_map.get("SAQ", 2)
            elif "NUM" in q_type_upper:
                q_type_id = types_map.get("NUMERICAL", 5)
            else:
                q_type_id = types_map.get("MCQ", 1)

        q_diff = q["difficulty"].lower()
        if q_diff in ["simple", "easy"]:
            diff_id = diffs_map.get("easy", diffs_map.get("simple", 1))
        else:
            diff_id = diffs_map.get(q_diff, 2)

        options_json = json.dumps(q["options"]) if q["options"] else None

        # Check existing for deduplication within exact topic
        existing_id = session.execute(
            text("""
                SELECT id FROM question_master
                WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                LIMIT 1
            """),
            {"t_id": q_topic_id, "q_text": q["question"]}
        ).scalar()

        if existing_id:
            session.execute(
                text("""
                    UPDATE question_master
                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                        image_url = COALESCE(:image_url, image_url),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": existing_id,
                    "options": options_json,
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "marks": q["marks"],
                    "diff_id": diff_id,
                    "type_id": q_type_id,
                    "image_url": q.get("image_url") or None
                }
            )
            updated_questions_count += 1
        else:
            session.execute(
                text("""
                    INSERT INTO question_master 
                    (topic_id, question_type_id, difficulty_level_id, question, image_url, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                    VALUES 
                    (:topic_id, :type_id, :diff_id, :question, :image_url, :options, :correct_answer, :explanation, :marks, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "topic_id": q_topic_id,
                    "type_id": q_type_id,
                    "diff_id": diff_id,
                    "question": q["question"],
                    "image_url": q.get("image_url") or None,
                    "options": options_json,
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "marks": q["marks"]
                }
            )
            inserted_questions_count += 1

    # 5.3 Insert Document and Document Chunks
    doc_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        filename=filename,
        content_type=f"application/{ext}",
        board=board,
        class_grade=class_grade,
        subject=subject,
        uploaded_by=uploaded_by,
        status="PROCESSED",
    )
    session.add(doc_record)
    session.flush()

    chunks = document_processor.chunk_text(cleaned_text)
    chunk_ids = []
    chunk_texts = []
    chunk_metas = []
    for c_idx, c_text in enumerate(chunks):
        chunk_uuid = str(uuid.uuid4())
        chunk_record = DocumentChunk(
            id=chunk_uuid,
            document_id=doc_id,
            chunk_index=c_idx,
            content=c_text,
            vector_id=chunk_uuid,
        )
        session.add(chunk_record)
        chunk_ids.append(chunk_uuid)
        chunk_texts.append(c_text)
        chunk_metas.append({
            "document_id": doc_id,
            "filename": filename,
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "document_type": document_type,
            "chunk_index": c_idx,
        })

    session.commit()

    # 5.4 ChromaDB Vector Upsert
    if vector_db.is_enabled() and chunk_texts:
        try:
            embeddings = embedding_engine.embed(chunk_texts)
            vector_db.upsert_chunks(chunk_ids, chunk_texts, embeddings, chunk_metas)
            print(f"  • ChromaDB Synced : {len(chunk_texts)} chunks indexed with Mistral Embeddings")
        except Exception as vec_err:
            logger.warning(f"Vector store indexing notice: {vec_err}")

    # 5.5 ArangoDB Knowledge Graph Sync
    try:
        from database import graph_db
        if graph_db.is_enabled():
            chapter_name_clean = title or filename.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
            topics_to_push = detected_topics if (detected_topics and len(detected_topics) > 0) else [chapter_name_clean]
            graph_db.upsert_hierarchical_curriculum_branch(
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter=chapter_name_clean,
                topics_list=topics_to_push
            )
            print(f"  • ArangoDB Synced : Hierarchy & {len(topics_to_push)} topic node(s) linked to knowledge graph")
    except Exception as graph_err:
        logger.warning(f"ArangoDB sync notice in pipeline: {graph_err}")

    print(f"  • Questions Saved : {TermColors.BOLD}{inserted_questions_count} inserted{TermColors.END}, {updated_questions_count} updated in `question_master`")
    print(f"  • Document ID     : {doc_id} (`documents` table)")
    print(f"  • Chunks Created  : {len(chunks)} (`document_chunks` table)")
    print(f"  • Default Topic ID: {default_topic_id}")

    _print_separator(f"PIPELINE COMPLETED: {filename} [SUCCESS]", TermColors.GREEN)

    return {
        "success": True,
        "filename": filename,
        "document_id": doc_id,
        "document_type": document_type,
        "title": title,
        "summary": summary,
        "detected_topics": detected_topics,
        "total_extracted": len(final_questions),
        "questions_inserted": inserted_questions_count,
        "questions_updated": updated_questions_count,
        "topic_id": default_topic_id,
        "chunk_count": len(chunks),
        "questions": final_questions,
    }


def extract_curriculum_questions_preview(
    session: Session,
    file_bytes: bytes,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    question_count: Optional[int] = None,
    target_topic_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Executes Steps 1 to 4 (Extraction, Context Analysis, Question Generation, Duplicate Check)

    without persisting to the database. Returns questions with duplicate indicators for UI review.
    """
    _print_separator(f"EXTRACTION PREVIEW: {filename}", TermColors.MAGENTA)

    # 1. DATA READ
    _print_step_header(1, "DATA READ & EXTRACTION", TermColors.CYAN)
    ext = document_processor.validate_upload(filename, len(file_bytes))
    raw_text = document_processor.extract_text(file_bytes, ext, board=board, class_grade=class_grade, subject=subject)
    cleaned_text = document_processor.clean_text(raw_text)

    char_count = len(cleaned_text)
    word_count = len(cleaned_text.split())
    line_count = len(cleaned_text.splitlines())

    print(f"  • File Name       : {TermColors.BOLD}{filename}{TermColors.END}")
    print(f"  • Target Config   : Board=[{board}] | Class=[{class_grade}] | Subject=[{subject}]")
    print(f"  • Text Extracted  : {TermColors.BOLD}{char_count:,}{TermColors.END} chars | {word_count:,} words")

    if not cleaned_text.strip():
        raise ValueError("Failed to extract readable text from the uploaded document.")

    # 2. CONTEXTUAL ANALYSIS
    _print_step_header(2, "SHORT CONTEXTUAL ANALYSIS", TermColors.YELLOW)
    analysis = perform_contextual_analysis(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        document_type=document_type,
        session=session,
    )
    title = analysis.get("title", filename)
    summary = analysis.get("summary", "")
    detected_topics = analysis.get("detected_topics", [subject])
    est_diff = analysis.get("estimated_difficulty", "medium")
    detected_subject = analysis.get("detected_subject")

    if not detected_subject or detected_subject == "Science":
        meta_detected = document_processor.detect_curriculum_metadata(cleaned_text[:6000])
        specific_sub = meta_detected.get("subject")
        if specific_sub and specific_sub != "Science":
            detected_subject = specific_sub
        elif not detected_subject:
            detected_subject = specific_sub or subject

    if detected_subject and not document_processor.is_subject_compatible(subject, detected_subject, class_grade):
        print(f"  • [BATCH AUTO-RECONCILED] Cross-disciplinary content '{detected_subject}' aligned to target subject '{subject}'.")
        detected_subject = subject

    # Calibrate Question Count (20-30 questions per chapter)
    rec_q = analysis.get("recommended_question_count")
    if question_count and 15 <= int(question_count) <= 35:
        target_q_count = int(question_count)
    elif rec_q and isinstance(rec_q, (int, float)) and 15 <= int(rec_q) <= 35:
        target_q_count = int(rec_q)
    else:
        target_q_count = 25 if char_count > 10000 else (20 if char_count > 5000 else 15)

    # 3. QUESTION DETECTION & EXTRACTION
    _print_step_header(3, f"QUESTION DETECTION & EXTRACTION ({document_type.upper()})", TermColors.BLUE)
    extracted_questions = extract_questions_from_document_text(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        document_type=document_type,
        target_q_count=target_q_count,
        detected_topics=detected_topics,
    )

    # 3.5 In-Memory Diagram Extraction & Smart Context-Verified Linking
    diagram_pool = []
    diag_metrics = {}
    linked_diagrams_count = 0
    if ext == "pdf" and is_diagram_subject(subject):
        try:
            diagram_pool = document_processor.extract_pdf_diagrams(file_bytes, max_diagrams=150)
            diag_metrics = getattr(diagram_pool, "metrics", {})
            linked_diagrams_count = assign_diagrams_to_questions(
                questions=extracted_questions,
                diagram_pool=diagram_pool,
                subject=subject,
                filename=filename,
                file_bytes=file_bytes,
            )
        except Exception as diag_err:
            logger.warning(f"Diagram extraction notice: {diag_err}")

    # Print comprehensive quality & yield audit in terminal
    print_extraction_quality_metrics(
        raw_text_chars=len(raw_text),
        cleaned_text_chars=char_count,
        diag_metrics=diag_metrics,
        linked_diagrams_count=linked_diagrams_count,
        total_questions=len(extracted_questions),
        filename=filename,
    )

    # 4. JSON SCHEMA PREP & PRE-INSERTION DUPLICATE CHECKER
    _print_step_header(4, "SCHEMA PREPARATION & DUPLICATE CHECKER", TermColors.YELLOW)
    _ensure_curriculum_tables(session)

    # Resolve target topic_id
    resolved_topic_id = resolve_subject_topic_id(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        target_topic_id=target_topic_id,
        title=title,
        detected_topics=detected_topics,
    )

    final_questions = []
    duplicate_count = 0
    type_counts: Dict[str, int] = {}
    diff_counts: Dict[str, int] = {}
    topics_map_count: Dict[str, int] = {}
    meta = {"board": board, "classGrade": class_grade, "subject": subject, "title": title}

    for idx, norm in enumerate(extracted_questions):
        if not norm:
            continue
        q_text = norm["question"]

        # Check existing in question_master
        is_dup = False
        try:
            existing_id = session.execute(
                text("""
                    SELECT id FROM question_master
                    WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                    LIMIT 1
                """),
                {"t_id": resolved_topic_id, "q_text": q_text}
            ).scalar()
            if existing_id:
                is_dup = True
                duplicate_count += 1
        except Exception:
            is_dup = False

        norm["id"] = str(uuid.uuid4())
        norm["is_duplicate"] = is_dup
        norm["chapter_title"] = title
        final_questions.append(norm)

        q_t = norm.get("type", "MCQ")
        q_d = norm.get("difficulty", "medium")
        q_top = norm.get("topic_suggested") or subject
        type_counts[q_t] = type_counts.get(q_t, 0) + 1
        diff_counts[q_d] = diff_counts.get(q_d, 0) + 1
        topics_map_count[q_top] = topics_map_count.get(q_top, 0) + 1

    print(f"  • Total Extracted : {len(final_questions)} Questions ({duplicate_count} Existing / Duplicates Detected)")

    # Prepare rich pedagogical summary payload
    core_concepts = analysis.get("core_concepts", []) or [f"Core principles of {title}"]
    key_formulas = analysis.get("key_formulas_or_rules", []) or []
    common_traps = analysis.get("common_traps", []) or []
    topics_breakdown = [{"topic": t, "count": c} for t, c in topics_map_count.items()]

    return {
        "success": True,
        "filename": filename,
        "document_type": document_type,
        "board": board,
        "class_grade": class_grade,
        "subject": subject,
        "title": title,
        "summary": summary,
        "core_concepts": core_concepts,
        "key_formulas_or_rules": key_formulas,
        "common_traps": common_traps,
        "detected_topics": detected_topics,
        "topics_breakdown": topics_breakdown,
        "difficulty_distribution": {
            "easy": diff_counts.get("easy", 0),
            "medium": diff_counts.get("medium", 0),
            "hard": diff_counts.get("hard", 0),
        },
        "type_breakdown": type_counts,
        "estimated_difficulty": est_diff,
        "status": "PREVIEW_READY",
        "total_extracted": len(final_questions),
        "new_questions_count": len(final_questions) - duplicate_count,
        "duplicate_questions_count": duplicate_count,
        "duplicate_count": duplicate_count,
        "topic_id": resolved_topic_id,
        "cleaned_text": cleaned_text,
        "char_count": char_count,
        "questions": final_questions,
    }


def save_curriculum_extracted_questions_pipeline(
    session: Session,
    questions: List[Dict[str, Any]],
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    cleaned_text: str = "",
    target_topic_id: Optional[int] = None,
    uploaded_by: Optional[int] = None,
    detected_topics: List[str] = None,
    title: str = None,
    summary: str = None,
    core_concepts: List[str] = None,
    key_formulas_or_rules: List[str] = None,
    common_traps: List[str] = None,
) -> Dict[str, Any]:
    """Persists Admin-approved questions into question_master with Duplicate Protection,

    stores document chunks, updates ChromaDB Vector Store, and syncs ArangoDB K-Graph with insights.
    """
    _print_separator(f"PERSISTING APPROVED QUESTIONS: {filename}", TermColors.GREEN)
    _ensure_curriculum_tables(session)

    # 1. Resolve or dynamically create Chapter & ALL Sub-Topics in topic_master
    matched_chapter_id, topic_map, default_topic_id = resolve_or_create_chapter_and_topics(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        detected_topics=detected_topics,
        questions=questions,
        target_topic_id=target_topic_id,
    )

    # 2. Lookup Dicts for Question Types and Difficulties
    types_map = {
        r[0].upper(): r[1]
        for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
    }
    diffs_map = {
        r[0].lower(): r[1]
        for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
    }

    inserted_count = 0
    updated_count = 0
    duplicate_skipped = 0

    for q in questions:
        q_topic_id = match_question_to_topic_id(topic_map, q, default_topic_id)

        q_type_upper = str(q.get("type", "MCQ")).upper()
        q_type_id = types_map.get(q_type_upper)
        if not q_type_id:
            if "CASE" in q_type_upper:
                q_type_id = types_map.get("CASE STUDY", types_map.get("SAQ", 2))
            elif "ASSERT" in q_type_upper:
                q_type_id = types_map.get("ASSERTION REASON", types_map.get("MCQ", 1))
            elif "LONG" in q_type_upper:
                q_type_id = types_map.get("LONG ANSWER", types_map.get("LONG EVALUATIVE (8M)", 3))
            elif "SHORT" in q_type_upper or "SAQ" in q_type_upper:
                if int(q.get("marks", 2)) == 3:
                    q_type_id = types_map.get("SHORT ANSWER (3M)", types_map.get("SAQ", 2))
                else:
                    q_type_id = types_map.get("SAQ", 2)
            elif "NUM" in q_type_upper:
                q_type_id = types_map.get("NUMERICAL", 5)
            else:
                q_type_id = types_map.get("MCQ", 1)

        q_diff = str(q.get("difficulty", "medium")).lower()
        if q_diff in ["simple", "easy"]:
            diff_id = diffs_map.get("easy", diffs_map.get("simple", 1))
        else:
            diff_id = diffs_map.get(q_diff, 2)

        options_json = json.dumps(q.get("options", [])) if q.get("options") else None
        q_text = q.get("question", "").strip()

        # Check existing for deduplication within exact topic
        existing_id = session.execute(
            text("""
                SELECT id FROM question_master
                WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                LIMIT 1
            """),
            {"t_id": q_topic_id, "q_text": q_text}
        ).scalar()

        if existing_id:
            # Update existing with refined explanation and options
            session.execute(
                text("""
                    UPDATE question_master
                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                        image_url = COALESCE(:image_url, image_url),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": existing_id,
                    "options": options_json,
                    "correct_answer": q.get("correct_answer", "A"),
                    "explanation": q.get("explanation", ""),
                    "marks": int(q.get("marks", 1)),
                    "diff_id": diff_id,
                    "type_id": q_type_id,
                    "image_url": q.get("image_url") or q.get("imageUrl") or None
                }
            )
            updated_count += 1
            duplicate_skipped += 1
        else:
            session.execute(
                text("""
                    INSERT INTO question_master 
                    (topic_id, question_type_id, difficulty_level_id, question, image_url, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                    VALUES 
                    (:topic_id, :type_id, :diff_id, :question, :image_url, :options, :correct_answer, :explanation, :marks, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "topic_id": q_topic_id,
                    "type_id": q_type_id,
                    "diff_id": diff_id,
                    "question": q_text,
                    "image_url": q.get("image_url") or q.get("imageUrl") or None,
                    "options": options_json,
                    "correct_answer": q.get("correct_answer", "A"),
                    "explanation": q.get("explanation", ""),
                    "marks": int(q.get("marks", 1))
                }
            )
            inserted_count += 1

    # 2.5 Runbook Resolution / Creation & Linking
    ch_title = (title or filename or "Chapter").replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ").strip()
    rb_core_concepts = core_concepts or [f"{ch_title} Core Concepts"]
    rb_formulas = key_formulas_or_rules or [f"{ch_title} Essential Principles"]
    rb_traps = common_traps or ["Misapplication of fundamental definitions"]
    rb_archetypes = [q.get("question") for q in questions[:4] if isinstance(q, dict) and q.get("question")]

    resolved_runbook_id = None
    try:
        existing_rb = session.query(Runbook).filter(
            Runbook.board == board,
            Runbook.class_grade == class_grade,
            Runbook.subject == subject,
            Runbook.chapter_name == ch_title
        ).first()

        if not existing_rb:
            new_rb = Runbook(
                id=str(uuid.uuid4()),
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter_name=ch_title,
                core_concepts=rb_core_concepts,
                key_formulas_or_rules=rb_formulas,
                common_traps=rb_traps,
                curated_reference_urls=[],
                sample_question_archetypes=rb_archetypes,
                difficulty_calibration={"simple": 40, "medium": 40, "hard": 20},
                status="PUBLISHED",
                version=1,
                created_by=uploaded_by if uploaded_by and str(uploaded_by).isdigit() else None,
            )
            session.add(new_rb)
            session.flush()
            resolved_runbook_id = new_rb.id
        else:
            if rb_core_concepts:
                existing_rb.core_concepts = rb_core_concepts
            if rb_formulas:
                existing_rb.key_formulas_or_rules = rb_formulas
            if rb_traps:
                existing_rb.common_traps = rb_traps
            if rb_archetypes:
                existing_rb.sample_question_archetypes = rb_archetypes
            session.flush()
            resolved_runbook_id = existing_rb.id
    except Exception as rb_err:
        logger.warning(f"Runbook auto-sync notice: {rb_err}")

    # 3. Create Document and Document Chunks
    doc_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        runbook_id=resolved_runbook_id,
        filename=filename,
        content_type=document_type,
        board=board,
        class_grade=class_grade,
        subject=subject,
        uploaded_by=uploaded_by if uploaded_by and str(uploaded_by).isdigit() else None,
        status="PROCESSED",
    )
    session.add(doc_record)
    session.flush()

    # Create chunks from text if available
    chunks = []
    if cleaned_text:
        chunks = document_processor.chunk_text(cleaned_text, chunk_size=800, overlap=120)

    chunk_ids = []
    chunk_texts = []
    chunk_metas = []

    for c_idx, c_content in enumerate(chunks):
        c_id = str(uuid.uuid4())
        d_chunk = DocumentChunk(
            id=c_id,
            document_id=doc_id,
            chunk_index=c_idx,
            content=c_content,
            vector_id=f"{doc_id}_{c_idx}",
        )
        session.add(d_chunk)
        chunk_ids.append(f"{doc_id}_{c_idx}")
        chunk_texts.append(c_content)
        chunk_metas.append({
            "document_id": doc_id,
            "filename": filename,
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "document_type": document_type,
            "chunk_index": c_idx,
        })

    session.commit()

    # 4. ChromaDB Vector Store Sync
    if vector_db.is_enabled() and chunk_texts:
        try:
            embeddings = embedding_engine.embed(chunk_texts)
            vector_db.upsert_chunks(chunk_ids, chunk_texts, embeddings, chunk_metas)
            print(f"  • ChromaDB Synced : {len(chunk_texts)} chunks indexed with Mistral Embeddings")
        except Exception as vec_err:
            logger.warning(f"Vector store indexing notice: {vec_err}")

    # 5. ArangoDB Knowledge Graph Sync with Pedagogical Insights
    try:
        from database import graph_db
        if graph_db.is_enabled():
            chapter_name_clean = title or filename.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
            topics_to_push = detected_topics if (detected_topics and len(detected_topics) > 0) else [chapter_name_clean]

            # Aggregate per-topic question counts
            topic_q_dist = {}
            for q in questions:
                top_name = q.get("topic_suggested") or q.get("topic_name") or chapter_name_clean
                topic_q_dist[top_name] = topic_q_dist.get(top_name, 0) + 1

            graph_db.upsert_hierarchical_curriculum_branch(
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter=chapter_name_clean,
                topics_list=topics_to_push,
                chapter_summary=summary or f"Curriculum chapter for {subject}",
                core_concepts=core_concepts or [],
                key_formulas=key_formulas_or_rules or [],
                common_traps=common_traps or [],
                question_counts=topic_q_dist,
            )
            print(f"  • ArangoDB Synced : Hierarchy, Insights & {len(topics_to_push)} topic node(s) linked to knowledge graph")
    except Exception as graph_err:
        logger.warning(f"ArangoDB sync notice in pipeline: {graph_err}")

    print(f"  • Questions Saved : {inserted_count} inserted, {updated_count} updated ({duplicate_skipped} duplicates protected)")
    _print_separator(f"QUESTIONS PERSISTED SUCCESSFULLY: {filename}", TermColors.GREEN)

    return {
        "success": True,
        "filename": filename,
        "document_id": doc_id,
        "title": title or filename,
        "total_processed": len(questions),
        "total_saved": inserted_count + updated_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "duplicate_skipped_count": duplicate_skipped,
        "chunk_count": len(chunks),
        "topic_id": default_topic_id,
    }

