"""Pydantic validation for AI-generated content (master prompt §35 — AI
output is untrusted). Anything that fails validation here is treated as an
AI failure and triggers the deterministic fallback path, never a partially
trusted response."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ReferenceLinkSchema(BaseModel):
    title: str
    source: str
    url: str
    description: str
    type: str = "article"


class GeneratedQuestionSchema(BaseModel):
    questionNumber: int
    type: Literal["mcq", "numerical", "objective", "logical"]
    questionText: str
    options: Optional[list[str]] = None
    correctAnswer: str
    explanation: str
    topic: str
    difficulty: Optional[str] = None
    marks: int = 1

    @field_validator("options")
    @classmethod
    def mcq_needs_four_options(cls, v, info):
        question_type = info.data.get("type")
        if question_type in ("mcq", "logical"):
            if not v or len(v) != 4:
                raise ValueError("mcq/logical questions must have exactly 4 options")
        return v


class GeneratedExamSchema(BaseModel):
    title: str
    questions: list[GeneratedQuestionSchema] = Field(min_length=1)


class KGraphInsightSchema(BaseModel):
    topic: str
    masteryPercentage: float
    status: Literal["mastered", "reinforce", "critical_gap"]
    recommendedAction: str


class RecommendedNextExamSchema(BaseModel):
    board: str
    classGrade: str
    subject: str
    difficulty: Literal["simple", "medium", "hard"]
    reason: str


class DiagnosticAnalysisSchema(BaseModel):
    overallBand: Literal[
        "Needs Foundation", "Developing", "Proficient", "Advanced Mastery", "Competitive Ready"
    ]
    strengths: list[str]
    areasToImprove: list[str]
    kGraphInsights: list[KGraphInsightSchema]
    evolutionaryRoadmap: str
    encouragementNote: str
    recommendedNextExam: RecommendedNextExamSchema
    curatedStudyLinks: list[ReferenceLinkSchema]
