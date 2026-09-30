"""Child & Adolescent Mental Health Counselor AI Engine for EduJunction.
Conducts empathetic, age-appropriate, class-calibrated pre-exam wellbeing assessments.
Uses LLM with dynamic psychiatric counseling prompts, with a resilient fallback tree.
Supports continuous memory linking returning check-ins (#2, #3, etc.) to previous check-ins.
"""
import json
import re
from typing import Dict, Any, List

from model.mistral_client import call_llm_chat
from utils.logger import logger

# Class/Age Brackets for Developmental Psychology Calibration
def get_grade_bracket(class_grade: str) -> str:
    g = (class_grade or '').lower().strip()
    if any(c in g for c in ['class 1', 'class 2', 'class 3', 'class 4', 'grade 1', 'grade 2', 'grade 3', 'grade 4', '1st', '2nd', '3rd', '4th']):
        return 'primary'       # Age 6 - 9: Playful, gentle, story/games
    elif any(c in g for c in ['class 5', 'class 6', 'class 7', 'class 8', 'grade 5', 'grade 6', 'grade 7', 'grade 8', '5th', '6th', '7th', '8th']):
        return 'middle'        # Age 10 - 14: Relatable, peer & hobby, school stress
    elif any(c in g for c in ['class 9', 'class 10', 'grade 9', 'grade 10', '9th', '10th', 'madhyamik', 'matric']):
        return 'secondary'     # Age 14 - 16: Board exam anxiety, syllabus pressure
    else:
        return 'senior'        # Age 16 - 18+: Competitive (NEET/IIT), burnout, mastery


def _parse_previous_summary(previous_summary: Any) -> Dict[str, Any] | None:
    """Parses previous summary whether passed as dictionary, JSON string, or plain text."""
    if not previous_summary:
        return None
    if isinstance(previous_summary, dict):
        return previous_summary
    if isinstance(previous_summary, str):
        try:
            return json.loads(previous_summary)
        except Exception:
            # Extract common patterns if string
            text = previous_summary.lower()
            hobby = "your favorite hobbies"
            support = "your family"
            if "football" in text:
                hobby = "Football"
            elif "cricket" in text:
                hobby = "Cricket"
            elif "music" in text:
                hobby = "Music"
            elif "art" in text or "drawing" in text:
                hobby = "Art & Drawing"
            if "mom" in text or "mother" in text:
                support = "Mom"
            elif "dad" in text or "father" in text:
                support = "Dad"
            elif "teacher" in text:
                support = "Teacher"
            return {
                "mood": "Calm & Steady",
                "hobby": hobby,
                "support_person": support,
                "checkin_number": 2
            }
    return None


def _build_system_prompt(student_name: str, class_grade: str, board: str, subject: str, bracket: str, turn_count: int, previous_summary: Any = None) -> str:
    first_name = student_name.split()[0] if student_name else "Student"
    prev_info = _parse_previous_summary(previous_summary)

    bracket_instructions = {
        'primary': f"""
DEVELOPMENTAL STAGE: Primary School Child (Class 1 - 4, Age 6-9 years).
COUNSELOR PERSONA: Warm, cheerful, gentle Child Buddy & Play Counselor.
TONE & LANGUAGE: Very simple, short sentences (10-18 words max), comforting, playful emojis (🎈, 🌟, 🧸, 🎨).
PSYCHOLOGICAL GOAL: Assess if the child is scared of test questions or having fun. Normalize butterflies. Ask about fun play/cartoons/singing that makes them smile, and who hugs them at home (Mom/Dad/Grandma).
DO NOT use complex academic or medical words. Treat test as a fun quiz game with stars.
""",
        'middle': f"""
DEVELOPMENTAL STAGE: Middle School Student (Class 5 - 8, Age 10-14 years, e.g. Class 7).
COUNSELOR PERSONA: Relatable, empathetic School Life & Mindset Mentor.
TONE & LANGUAGE: Friendly, peer-relatable, engaging, encouraging (🎧, ⚡, ⚽, 💡).
PSYCHOLOGICAL GOAL: Assess current mental battery (calm vs anxious vs high energy vs fatigued). Identify the exact trigger (tricky questions, timer pressure, fear of low marks, or eager excitement).
CRITICAL TOPIC CONSISTENCY: Directly explore what the student actually talks about! If {first_name} mentions Football or Sports, talk about Football, stamina, and team spirit. If they mention Music, explore music. DO NOT arbitrarily change topics!
Keep responses under 35 words. Every turn must directly link to what {first_name} said.
""",
        'secondary': f"""
DEVELOPMENTAL STAGE: Secondary Board Student (Class 9 - 10, Age 14-16 years).
COUNSELOR PERSONA: Insightful Adolescent Academic Counselor & Confidence Coach.
TONE & LANGUAGE: Empathetic, mature, reassuring, validating (🎯, 🌿, 📖, 🛡️).
PSYCHOLOGICAL GOAL: Screen for Board exam performance anxiety, fear of failure, or overload. Guide them to cognitive reframing (diagnostic tests are learning compasses, not judgments). Ask about their mental decompression rituals (music, fitness, drawing) and their emotional safety net.
Keep responses concise, warm, and natural.
""",
        'senior': f"""
DEVELOPMENTAL STAGE: High School & Competitive Aspirant (Class 11 - 12 / NEET / IIT, Age 16-18+).
COUNSELOR PERSONA: High-Performance Student Psychologist & Wellbeing Guide.
TONE & LANGUAGE: Grounded, intellectual, deeply supportive, stress-reducing.
PSYCHOLOGICAL GOAL: Screen for cognitive fatigue, competitive pressure, burnout, and imposter syndrome. Provide grounding breath guidance, anchor connection, and clarity.
"""
    }

    instructions = bracket_instructions.get(bracket, bracket_instructions['middle'])

    memory_instruction = ""
    if prev_info:
        mood = prev_info.get("mood", "steady")
        hobby = prev_info.get("hobby") or prev_info.get("hobby_detail") or "their favorite passion"
        support = prev_info.get("support_person", "their loved ones")
        checkin_num = prev_info.get("checkin_number", 2)
        memory_instruction = f"""
RETURNING STUDENT CHECK-IN #{checkin_num} CONTINUITY:
{first_name} is on Check-in #{checkin_num}. You have full memory of their previous check-in:
- Previous Mood: {mood}
- Favorite Passion / Coping Outlet: {hobby}
- Emotional Support Anchor: {support}

MANDATORY CONTINUITY INSTRUCTIONS:
- You must continuously link this conversation with their previous check-in.
- On Turn 1: Explicitly welcome {first_name} back! Reference that last time they shared their love for '{hobby}' and how '{support}' is their greatest cheerleader. Ask how their energy and mood are today compared to last time!
- On Turn 2: Follow up directly on their response. If they are feeling nervous or stressed, recall how '{hobby}' helps reset their mind, or how '{support}' gives them courage. If they feel energized, celebrate that growth!
- On Turn 3 & 4: Highlight their emotional resilience and growth over time!
"""

    wrap_up_instruction = ""
    if turn_count >= 3:
        wrap_up_instruction = f"""
IMPORTANT: This is Turn {turn_count}. It is time to conclude the assessment with empowering reassurance!
Set "is_complete": true in your JSON output.
Provide a personalized "mental_health_summary" object and an uplifting pre-exam reassurance message in "reply_text".
"""

    return f"""You are a licensed, compassionate Child & Adolescent Mental Health Counselor at EduJunction.
You are having a brief 1-on-1 pre-exam wellbeing dialogue with {first_name} ({class_grade}, {board} Curriculum, taking a {subject} diagnostic exam).

{instructions}
{memory_instruction}
{wrap_up_instruction}

CORE COUNSELING RULES:
1. Speak DIRECTLY to {first_name} in 2nd-person ("you").
2. Validate what they just said before asking the next question.
3. FOLLOW THE STUDENT'S TOPIC: Never introduce unrelated topics (e.g. if they say Football, discuss Football/sports; do not randomly ask about singers or music).
4. SUGGESTED CHIPS QUALITY: In "suggested_chips", generate 3 to 4 varied, highly relevant options that DIRECTLY answer your question. Each chip must have an expressive emoji in "label" and clean text in "value".
5. Output MUST be strictly valid JSON without any markdown formatting or preambles, matching this exact schema:
{{
  "reply_text": "Counselor's empathetic message and follow-up question (max 40 words)",
  "suggested_chips": [
    {{"label": "Detailed option with emoji", "value": "clean value"}},
    {{"label": "Detailed option with emoji", "value": "clean value"}},
    {{"label": "Detailed option with emoji", "value": "clean value"}},
    {{"label": "Detailed option with emoji", "value": "clean value"}}
  ],
  "is_complete": false,
  "mental_health_summary": null
}}

When is_complete is true:
{{
  "reply_text": "Empowering final message for {first_name} to take 3 deep breaths and start the exam with calm confidence.",
  "suggested_chips": [],
  "is_complete": true,
  "mental_health_summary": {{
    "mood": "Identified mood (e.g. High energy & confident / Anxious about tricky questions / Calm & Ready)",
    "anxiety_level": "Low | Mild | Moderate | High",
    "stress_trigger": "Identified stress trigger or 'None / Eager & Ready'",
    "coping_outlet": "Student's passion/hobby (e.g. Playing Football / Listening to Music / Art)",
    "support_anchor": "Person student named (e.g. Mom / Dad / Teacher / Best Friend)",
    "guidance_tip": "Specific parenting/counseling tip for parents"
  }}
}}
"""


def _generate_fallback_response(
    student_name: str,
    class_grade: str,
    bracket: str,
    messages: List[Dict[str, str]],
    previous_summary: Any = None
) -> Dict[str, Any]:
    """Resilient, class-calibrated psychiatric dialog tree if LLM is unavailable."""
    first_name = student_name.split()[0] if student_name else "Student"
    user_turns = [m for m in messages if m.get("role") == "user"]
    last_user_input = user_turns[-1].get("content", "").lower() if user_turns else ""
    turn_idx = len(user_turns)

    prev_info = _parse_previous_summary(previous_summary)

    # ──────────────────────────────────────────────────
    # CONTINUOUS MEMORY LINKING (RETURNING STUDENT CHECK-IN)
    # ──────────────────────────────────────────────────
    if prev_info:
        hobby = prev_info.get("hobby") or prev_info.get("hobby_detail") or "your favorite passion"
        support = prev_info.get("support_person") or "your family"
        checkin_num = prev_info.get("checkin_number") or 2

        if turn_idx == 0:
            return {
                "reply_text": f"Welcome back, {first_name}! 🌟 Great to see you again for another diagnostic practice test!\n\nLast time we talked, you told me your favorite way to unwind is {hobby} and {support} is your greatest support cheerleader! ❤️\n\nHow is your energy and mood today compared to last time?",
                "suggested_chips": [
                    {"label": "Even more energized & confident today! ⚡", "value": "Even more energized & confident today!"},
                    {"label": "Calm, focused & steady 😌", "value": "Calm, focused & steady"},
                    {"label": "A little anxious about today's questions 😰", "value": "A little anxious about today's questions"},
                    {"label": "Feeling a bit tired, but ready to do my best 🥱", "value": "Feeling a bit tired, but ready to do my best"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 1:
            if any(w in last_user_input for w in ['anxious', 'nervous', 'tired', 'worry']):
                return {
                    "reply_text": f"I hear you, {first_name}. It's completely normal to feel butterflies! Remember how {hobby} helps clear your head? What specific part of today's exam is causing worry?",
                    "suggested_chips": [
                        {"label": "Fear of tricky or difficult problems 🧩", "value": "Fear of tricky problems"},
                        {"label": "Worry about the countdown timer ⏱️", "value": "Timer anxiety"},
                        {"label": "Fear of making silly mistakes 📉", "value": "Fear of silly mistakes"},
                        {"label": "Just general test nervousness 💭", "value": "General nervousness"},
                    ],
                    "is_complete": False,
                    "mental_health_summary": None
                }
            else:
                return {
                    "reply_text": f"That is wonderful growth, {first_name}! 🚀 Channeling that positive energy makes solving questions so much smoother. Did you get time to enjoy {hobby} or did {support} give you an encouraging cheer before today?",
                    "suggested_chips": [
                        {"label": f"Yes, spent time on {hobby} and feel refreshed! ✨", "value": f"Spent time on {hobby}"},
                        {"label": f"Yes, got lovely encouragement from {support}! ❤️", "value": f"Encouraged by {support}"},
                        {"label": "I revised well and feel ready to test myself 📖", "value": "Revised well"},
                        {"label": "Took good rest and have fresh focus 😌", "value": "Good rest"},
                    ],
                    "is_complete": False,
                    "mental_health_summary": None
                }
        elif turn_idx == 2:
            return {
                "reply_text": f"Wonderful! As you prepare to start, remember that {support} and all of us believe in your curiosity and perseverance. Are you ready to approach each question with a calm, curious mind?",
                "suggested_chips": [
                    {"label": "Yes! I will take it one question at a time 🎯", "value": "Take it one question at a time"},
                    {"label": "Ready to do my absolute best with no fear 🚀", "value": "Do my absolute best with no fear"},
                    {"label": "Will take a deep breath if a question gets tricky 😌", "value": "Deep breath if tricky"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        else:
            return {
                "reply_text": f"You're showing remarkable emotional resilience and self-awareness across your check-ins, {first_name}! Take 3 slow, deep belly breaths right now. Trust your preparation, stay curious, and enjoy the test!",
                "suggested_chips": [],
                "is_complete": True,
                "mental_health_summary": {
                    "mood": "Continuous Growth & Calmer Confidence",
                    "anxiety_level": "Low",
                    "stress_trigger": "Managed pre-exam butterflies through positive memory recall",
                    "coping_outlet": hobby,
                    "support_anchor": support,
                    "guidance_tip": f"Celebrated progress from Check-in #{checkin_num - 1} to #{checkin_num}. Continue praising {first_name}'s emotional regulation and effort!"
                }
            }

    # ──────────────────────────────────────────────────
    # FIRST-TIME CHECK-IN (BRACKET 1: PRIMARY KIDS Class 1 to 4)
    # ──────────────────────────────────────────────────
    if bracket == 'primary':
        if turn_idx == 0:
            return {
                "reply_text": f"Hi {first_name}! 🎈 Welcome! Before we start our fun question game, how are you feeling inside today?",
                "suggested_chips": [
                    {"label": "Happy and smiling 😊", "value": "Happy and smiling"},
                    {"label": "Super excited to play 🚀", "value": "Excited to play"},
                    {"label": "A little bit scared or nervous 🥺", "value": "A little nervous"},
                    {"label": "Feeling sleepy or tired 🥱", "value": "Sleepy and tired"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 1:
            if "nervous" in last_user_input or "scared" in last_user_input:
                ack = "It's totally okay! Even little tigers get butterflies. What makes you happiest when playing — drawing colorful pictures, playing with toys, or listening to fun nursery songs?"
            else:
                ack = "That makes me smile! What is your favorite game to play when you are having fun at home?"
            return {
                "reply_text": ack,
                "suggested_chips": [
                    {"label": "Drawing & coloring pictures 🎨", "value": "Drawing & coloring"},
                    {"label": "Listening to cheerful songs 🎵", "value": "Music & songs"},
                    {"label": "Playing with toys & running ⚽", "value": "Toys & running"},
                    {"label": "Watching cartoons 📺", "value": "Watching cartoons"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 2:
            return {
                "reply_text": f"That sounds like so much fun! 🌟 Who gives you the biggest, warmest hug at home when you need comfort?",
                "suggested_chips": [
                    {"label": "Mommy — she loves me so much ❤️", "value": "Mommy"},
                    {"label": "Daddy — he plays with me 👨‍👧", "value": "Daddy"},
                    {"label": "Grandma & Grandpa 👵", "value": "Grandparents"},
                    {"label": "My Teacher 👩‍🏫", "value": "Teacher"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        else:
            return {
                "reply_text": f"You are a brave superstar, {first_name}! 🌟 Remember, this test is just a fun little puzzle game. Take a deep breath, smile, and have fun!",
                "suggested_chips": [],
                "is_complete": True,
                "mental_health_summary": {
                    "mood": "Playful & Reassured",
                    "anxiety_level": "Low",
                    "stress_trigger": "Mild pre-quiz butterflies",
                    "coping_outlet": "Drawing & Fun play",
                    "support_anchor": "Mommy & Family",
                    "guidance_tip": f"Give {first_name} a warm hug after the quiz and praise their effort regardless of marks!"
                }
            }

    # ──────────────────────────────────────────────────
    # FIRST-TIME CHECK-IN (BRACKET 2: MIDDLE SCHOOL Class 5 to 8)
    # ──────────────────────────────────────────────────
    elif bracket == 'middle':
        if turn_idx == 0:
            return {
                "reply_text": f"Hey {first_name}! 👋 Quick pre-exam check-in before today's diagnostic mock test. How is your mental battery and mood right now?",
                "suggested_chips": [
                    {"label": "Calm, focused & steady 😌", "value": "Calm and focused"},
                    {"label": "Full of energy & ready to conquer ⚡", "value": "High energy"},
                    {"label": "Feeling anxious about tough questions 😰", "value": "Anxious about questions"},
                    {"label": "Feeling a bit tired and low energy 🥱", "value": "Tired"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 1:
            if any(w in last_user_input for w in ['anxious', 'nervous', 'questions', 'stress']):
                reply = f"I hear you, {first_name}. Fear of tricky questions is the #1 thing students feel. Remember, this test is just practice, zero judgment! What helps you disconnect and reset when school stress builds up?"
            elif 'tired' in last_user_input:
                reply = f"Studying hard definitely drains energy, {first_name}. When your mind feels heavy, what is your favorite passion that refreshes your brain cells?"
            else:
                reply = f"Love that energetic confidence, {first_name}! What activity or passion usually gets you into this great positive headspace?"

            return {
                "reply_text": reply,
                "suggested_chips": [
                    {"label": "Playing outdoor sports (Football/Cricket) ⚽", "value": "Football & Sports"},
                    {"label": "Listening to music / Singing 🎵", "value": "Music & Songs"},
                    {"label": "Drawing, sketching & crafts 🎨", "value": "Art & Drawing"},
                    {"label": "Gaming & tech fun 🎮", "value": "Gaming"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 2:
            if any(w in last_user_input for w in ['football', 'sport', 'cricket', 'badminton', 'running', 'athlete']):
                if 'football' in last_user_input:
                    reply = f"Football is fantastic for channeling adrenaline and building laser focus! ⚽ How does playing football help your mindset the most?"
                    chips = [
                        {"label": "Running & scoring relieves all my tension ⚽", "value": "Running and scoring relieves tension"},
                        {"label": "Playing with teammates makes me happy & confident 🤝", "value": "Playing with teammates"},
                        {"label": "Watching matches of Messi / Ronaldo inspires me 🏆", "value": "Watching idol matches"},
                        {"label": "Keeps my brain energized & sharp ⚡", "value": "Keeps brain sharp"},
                    ]
                elif 'cricket' in last_user_input:
                    reply = f"Cricket builds tremendous patience and mental composure under pressure! 🏏 What part of cricket helps you stay grounded?"
                    chips = [
                        {"label": "Focusing like Virat Kohli under pressure 🏏", "value": "Focus under pressure"},
                        {"label": "Enjoying matches with friends & family 🌟", "value": "Matches with friends"},
                        {"label": "Bowling fast and letting off steam ⚡", "value": "Bowling fast"},
                        {"label": "Celebrating big team wins together 🏆", "value": "Team wins"},
                    ]
                else:
                    reply = f"Physical movement pumps oxygen straight to the brain! 🏃‍♂️ Which sport or athlete inspires you to stay strong under pressure?"
                    chips = [
                        {"label": "Cricket — Virat Kohli / MS Dhoni 🏏", "value": "Cricket (Virat / Dhoni)"},
                        {"label": "Football — Messi / Ronaldo ⚽", "value": "Football (Messi / Ronaldo)"},
                        {"label": "Badminton / Tennis 🏸", "value": "Badminton"},
                        {"label": "Running & Athletics 🏃", "value": "Running & Athletics"},
                    ]
            elif any(w in last_user_input for w in ['music', 'song', 'sing']):
                reply = f"Music is scientifically proven to regulate heart rate and relax brainwaves! 🎶 What kind of music calms your mind the best?"
                chips = [
                    {"label": "Soulful & acoustic melodies 🎤", "value": "Soulful melodies"},
                    {"label": "Upbeat energetic beats that motivate me ⚡", "value": "Upbeat motivational beats"},
                    {"label": "Calm Lo-Fi and instrumental music 🎼", "value": "Lo-Fi instrumental"},
                    {"label": "Singing along to my favorite songs 🌟", "value": "Singing along"},
                ]
            elif any(w in last_user_input for w in ['art', 'draw', 'sketch', 'craft']):
                reply = f"Creative art taps into your right brain and brings deep peace! 🎨 When you draw or create, how do your thoughts feel?"
                chips = [
                    {"label": "All exam stress fades away peacefully 😌", "value": "Stress fades away"},
                    {"label": "I feel deeply focused in the flow 🎨", "value": "Deep focus in the flow"},
                    {"label": "Gives me fresh inspiration and pride ✨", "value": "Fresh inspiration"},
                ]
            else:
                reply = f"That is a wonderful passion, {first_name}! Engaging in what you love resets your mental battery. When you do that, does it recharge your focus?"
                chips = [
                    {"label": "Yes, totally resets my focus 😌", "value": "Totally resets focus"},
                    {"label": "Gives me fresh energy to solve problems ⚡", "value": "Fresh problem solving energy"},
                    {"label": "Helps me forget all worries and smile 😊", "value": "Forgets worries"},
                ]

            return {
                "reply_text": reply,
                "suggested_chips": chips,
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 3:
            return {
                "reply_text": f"Awesome! Now tell me, when things get challenging or stressful, who is your core champion at home or school who always believes in you and has your back?",
                "suggested_chips": [
                    {"label": "My Mom — unconditional love, care & hugs ❤️", "value": "Mom"},
                    {"label": "My Dad — strength, courage and guidance 🤝", "value": "Dad"},
                    {"label": "My Grandparents — warm blessings & comfort 👵", "value": "Grandparents"},
                    {"label": "My Best Friend — who cheers me up & makes me laugh 🌟", "value": "Best Friend"},
                    {"label": "My Teacher — who guides and believes in me 👩‍🏫", "value": "Teacher"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        else:
            return {
                "reply_text": f"Thank you for sharing, {first_name}. Take 3 slow, deep breaths right now. When you face any tricky question today, don't rush. Trust yourself, and remember you have your family's love behind you!",
                "suggested_chips": [],
                "is_complete": True,
                "mental_health_summary": {
                    "mood": "Calm, Centered & Encouraged",
                    "anxiety_level": "Low",
                    "stress_trigger": "Challenging questions or timer pressure",
                    "coping_outlet": "Sports (Football) / Creative passions",
                    "support_anchor": "Mom & Family",
                    "guidance_tip": f"Encourage {first_name} to celebrate effort and remind them that tricky problems are just learning puzzles."
                }
            }

    # ──────────────────────────────────────────────────
    # FIRST-TIME CHECK-IN (BRACKET 3: SECONDARY / SENIOR Class 9 to 12)
    # ──────────────────────────────────────────────────
    else:
        if turn_idx == 0:
            return {
                "reply_text": f"Hello {first_name}. Exam preparation can be intense. Take a deep breath. How are you feeling mentally and emotionally right now?",
                "suggested_chips": [
                    {"label": "Focused, calm and ready 😌", "value": "Focused and calm"},
                    {"label": "Experiencing anxiety about marks / syllabus 😰", "value": "Syllabus anxiety"},
                    {"label": "Mentally exhausted from long study hours 🥱", "value": "Mental burnout"},
                    {"label": "Optimistic and determined to do my best ⚡", "value": "Optimistic"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 1:
            if any(w in last_user_input for w in ['anxiety', 'exhausted', 'burnout', 'stress']):
                reply = f"I hear you. High-volume academic pressure is heavy. What is currently weighing on your mind the most?"
                chips = [
                    {"label": "Fear of tricky problems and losing marks 📉", "value": "Fear of tricky problems"},
                    {"label": "Time management bottlenecks ⏱️", "value": "Time management"},
                    {"label": "Feeling behind on syllabus revision 📚", "value": "Syllabus revision"},
                ]
            else:
                reply = f"Maintaining that composure is a great competitive skill. What decompression ritual keeps you so well centered?"
                chips = [
                    {"label": "Music and focus beats 🎧", "value": "Music"},
                    {"label": "Physical workouts & fitness 🏃", "value": "Workouts"},
                    {"label": "Structured sleep and planned breaks 😌", "value": "Structured sleep"},
                ]
            return {
                "reply_text": reply,
                "suggested_chips": chips,
                "is_complete": False,
                "mental_health_summary": None
            }
        elif turn_idx == 2:
            return {
                "reply_text": f"Insightful. When the pressure peaks, who is your core emotional safety anchor who grounds you without judgment?",
                "suggested_chips": [
                    {"label": "My Mother — unconditional comfort and care ❤️", "value": "Mother"},
                    {"label": "My Father — practical wisdom and strength 🤝", "value": "Father"},
                    {"label": "A trusted mentor or teacher 👩‍🏫", "value": "Mentor/Teacher"},
                    {"label": "My close friend 🌟", "value": "Close friend"},
                ],
                "is_complete": False,
                "mental_health_summary": None
            }
        else:
            return {
                "reply_text": f"Remember {first_name}, diagnostic exams are purely cognitive diagnostics to locate opportunities for growth. Trust your hard work, breathe calmly, and approach each question with intellectual curiosity.",
                "suggested_chips": [],
                "is_complete": True,
                "mental_health_summary": {
                    "mood": "Re-centered & Intellectually Ready",
                    "anxiety_level": "Low",
                    "stress_trigger": "Board/Competitive preparation pressure",
                    "coping_outlet": "Focus rituals & Music",
                    "support_anchor": "Family / Mentor",
                    "guidance_tip": f"Support {first_name}'s emotional wellbeing by celebrating effort and discipline rather than numerical rank."
                }
            }


def conduct_counselor_turn(
    student_name: str,
    class_grade: str,
    board: str,
    subject: str,
    conversation_history: List[Dict[str, str]],
    previous_summary: Any = None
) -> Dict[str, Any]:
    """Generates the next counselor dialogue turn using LLM, with deterministic fallback."""
    bracket = get_grade_bracket(class_grade)
    user_turns = [m for m in conversation_history if m.get("role") == "user"]
    turn_count = len(user_turns)

    # If first turn and no messages
    if not conversation_history:
        return _generate_fallback_response(student_name, class_grade, bracket, [], previous_summary)

    # Try LLM generation with prompt
    system_prompt = _build_system_prompt(student_name, class_grade, board, subject, bracket, turn_count, previous_summary)

    llm_messages = [{"role": "system", "content": system_prompt}] + conversation_history

    try:
        raw_response = call_llm_chat(llm_messages, json_mode=True, scenario="doubt_chat", temperature=0.3, timeout=12)
        if raw_response and raw_response.strip():
            # Clean JSON
            text = raw_response.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            parsed = json.loads(text)
            if "reply_text" in parsed:
                chips = parsed.get("suggested_chips", [])
                cleaned_chips = []
                if isinstance(chips, list):
                    for c in chips:
                        if isinstance(c, dict) and "label" in c:
                            cleaned_chips.append({"label": c["label"], "value": c.get("value", c["label"])})
                        elif isinstance(c, str):
                            cleaned_chips.append({"label": c, "value": c})

                return {
                    "reply_text": parsed.get("reply_text", ""),
                    "suggested_chips": cleaned_chips,
                    "is_complete": bool(parsed.get("is_complete", False) or turn_count >= 4),
                    "mental_health_summary": parsed.get("mental_health_summary")
                }
    except Exception as e:
        logger.warning(f"[COUNSELOR AI] LLM call fallback triggered ({e})")

    # High-quality fallback with previous memory integration
    return _generate_fallback_response(student_name, class_grade, bracket, conversation_history, previous_summary)
