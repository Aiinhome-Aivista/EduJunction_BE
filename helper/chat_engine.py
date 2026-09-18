import re
from model.mistral_client import call_llm_chat
from helper.rag_engine import retrieve_document_context


def _clean_chat_response(text: str) -> str:
    """Strip formal letter templates like 'Dear Parent,', 'Best,', etc. to keep chat modern and conversational."""
    if not text:
        return ""
    # Remove leading greetings like 'Dear Parent,', 'Dear Student,'
    cleaned = re.sub(r'^(Dear\s+(Parent|Student|Aarav|Sanjay)[,\s]*\n*|\bHello\s+[A-Za-z]+!\s+Great job on your last exam score\.\s*)', '', text, flags=re.IGNORECASE)
    # Remove trailing sign-offs like 'Best,', 'Best regards,', 'Sincerely,'
    cleaned = re.sub(r'\n*(Best|Best regards|Warm regards|Sincerely|Thanks)[,\s]*\s*$', '', cleaned.strip(), flags=re.IGNORECASE)
    return cleaned.strip()


def generate_chat_response(messages: list, student_context: dict = None, user_role: str = "PARENT") -> str:
    """
    Generate a chat response focusing on pedagogical and academic support for parents/students.
    Uses ChromaDB RAG for curriculum grounding and student mastery metrics when available.
    """
    last_user_query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_query = msg.get("content", "").strip()
            break

    query_lower = last_user_query.lower()
    is_student = str(user_role).upper() == "STUDENT"

    # 1. Intent Detection
    progress_keywords = ["progress", "score", "performance", "result", "weak", "attention", "practice", "improve", "marks", "test", "exam", "report", "how is", "doing"]
    academic_keywords = ["which", "what is", "why", "how to", "how do", "solve", "explain", "define", "calculate", "latitude", "longitude", "equator", "prime meridian", "formula", "option a", "option b", "options", "meaning", "photosynthesis", "geometry"]

    is_progress_intent = any(k in query_lower for k in progress_keywords)
    is_academic_intent = any(k in query_lower for k in academic_keywords) or "?" in last_user_query

    # Extract context safely
    name = student_context.get("name", "Student") if student_context else ("You" if is_student else "your child")
    grade = student_context.get("classGrade", "Class 7") if student_context else "their class"
    board = student_context.get("targetBoard", "CBSE") if student_context else "CBSE"
    weak_topics = student_context.get("weakTopics", []) if student_context else []
    avg_score = student_context.get("averageScore", None) if student_context else None
    recent_scores = student_context.get("recentScores", []) if student_context else []

    # Semantic RAG retrieval over ChromaDB for academic questions
    rag_snippets = []
    if last_user_query and (is_academic_intent or not is_progress_intent):
        try:
            rag_snippets = retrieve_document_context(
                board=board,
                class_grade=grade,
                subject="Mathematics",
                query_text=last_user_query,
                top_k=2
            )
        except Exception:
            rag_snippets = []

    rag_text = ""
    if rag_snippets:
        rag_text = f"\nVERIFIED CURRICULUM CONTEXT (ground your answers on this):\n" + "\n---\n".join(rag_snippets) + "\n"

    # Build Dynamic System Prompt based on User Persona & Intent
    if is_student:
        if is_academic_intent and not is_progress_intent:
            system_prompt = f"""You are an expert, friendly AI Study Buddy and Tutor for a student in {grade} ({board}).
The student asked this specific academic question: "{last_user_query}".
{rag_text}
CORE RULES:
1. Answer the question DIRECTLY, accurately, and clearly in 2 to 3 concise sentences.
2. Use simple, age-appropriate language suitable for a {grade} student.
3. DO NOT recite past exam scores, test averages, or weak subjects (like Algebra/History) on direct academic questions.
4. DO NOT write formal greetings or sign-offs ('Hello Aarav! Great job...', 'Dear Student', 'Best,'). Start directly with the clear conceptual answer.
5. Maximum 60 words."""
        elif is_progress_intent:
            system_prompt = f"""You are an encouraging AI Study Buddy helping student '{name}' in {grade} ({board}).
Student's Performance Metrics:
- Average Score: {avg_score}%
- Needs Attention on: {', '.join(weak_topics[:3]) if weak_topics else 'core topics'}
- Recent Test Marks: {', '.join(map(str, recent_scores[:3])) if recent_scores else 'N/A'}

CORE RULES:
1. Speak directly in friendly 2nd-person ('you' / 'your'). Give actionable tips to master {', '.join(weak_topics[:2]) if weak_topics else 'upcoming tests'}.
2. Keep the response motivating, specific, and concise (2-3 sentences, under 60 words).
3. No robotic letter greetings."""
        else:
            system_prompt = f"""You are an AI Study Buddy for a {grade} ({board}) student.
Provide cheerful, motivating study guidance in 2-3 concise sentences (under 60 words). No robotic letter templates."""
    else:
        # Parent Persona
        if is_progress_intent:
            system_prompt = f"""You are SahajPath Teacher Support assisting the parent regarding their child '{name}' in {grade} ({board}).
Child's Real Performance Profile:
- Name: {name}
- Class & Board: {grade} ({board})
- Average Score: {avg_score}%
- Needs Attention on: {', '.join(weak_topics[:3]) if weak_topics else 'consistent practice'}
- Recent Exam Marks: {', '.join(map(str, recent_scores[:3])) if recent_scores else 'N/A'}

CORE RULES:
1. Address the parent specifically regarding '{name}' and their actual performance in {grade}.
2. Provide 2-3 clear, actionable pedagogical insights for the parent to help '{name}' at home.
3. DO NOT write formal letter templates (DO NOT write 'Dear Parent,' or 'Best regards,'). Reply in natural chat style.
4. Maximum 70 words."""
        elif is_academic_intent:
            system_prompt = f"""You are SahajPath Teacher Support assisting a parent with a curriculum question for {grade} ({board}).
{rag_text}
CORE RULES:
1. Answer the parent's academic question directly, clearly, and concisely in 2-3 sentences.
2. Maintain a professional, supportive pedagogical tone without letter templates."""
        else:
            system_prompt = f"""You are SahajPath Teacher Support assisting the parent of '{name}' ({grade}).
Provide practical, positive home-study and routine guidance for a {grade} student in 2-3 sentences. No letter templates."""

    formatted_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        if msg.get("role") in ["user", "assistant"]:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})

    raw_response = call_llm_chat(formatted_messages, json_mode=False, temperature=0.4)
    return _clean_chat_response(raw_response)


