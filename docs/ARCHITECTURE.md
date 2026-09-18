# Architecture

```
React (Vite)  →  Flask app.py  →  controller/*  →  helper/*  →  model/ + database/
     │                                                  │
     │ (dev: Vite proxy /api → :8000)                   ├─ model/mistral_client.py → Mistral API
     │                                                  ├─ database/vector_db.py   → ChromaDB (optional)
     └─ src/lib/api.ts (typed client, JWT storage)       └─ database/graph_db.py    → ArangoDB (optional)
```

`app.py` stays thin: it builds the Flask app, wires CORS/middleware, and
registers every blueprint from `controller/__init__.py`. No business logic
lives there.

## Request flow (example: exam generation)
```
POST /api/v1/exams/generate
  → controller/exam_controller.py: auth, validation, quota check
  → helper/exam_generator.py:
        helper/rag_engine.py           (retrieve matching runbooks)
        model/mistral_client.py        (generate, JSON mode)
        utils/ai_schemas.py            (Pydantic-validate the AI output)
        helper/fallback_exam_bank.py   (deterministic fallback if AI fails/invalid)
  → model/models.py (Exam, Question rows persisted)
  → utils/serializers / exam_to_public_dict (correctAnswer stripped)
  → utils/response.py (success envelope)
```

## Authentication
JWT access (short-lived) + refresh (long-lived, rotated on use, hashed at
rest in `refresh_tokens`). `middleware/authMiddleware.py` decodes and
attaches `g.current_user_id`/`g.current_user_role`; `middleware/
roleMiddleware.py` layers role checks and object-level ownership checks
(`assert_owns_student`) on top. Child accounts authenticate via a PIN
(`POST /auth/child-login`) rather than email/password, matching the
frontend's original persona-switch UX — but now the PIN is actually
verified against a bcrypt hash instead of being decorative.

## RAG
Two retrieval layers (`helper/rag_engine.py`):
1. **Structured** — `runbooks` filtered by board/grade/subject, sent to
   Mistral in full (small, curated). This is the primary grounding source
   and is what the original frontend's server.ts already did.
2. **Semantic** — optional, for freeform uploaded documents
   (`helper/rag_ingestion.py`: extract → chunk → embed via
   `model/mistral_client.py` → store in `database/vector_db.py`). Silently
   contributes nothing if no documents have been ingested or Chroma is
   unavailable — never blocks exam generation.

## Knowledge Graph
`database/graph_db.py` mirrors mastery/misconception edges into ArangoDB
for future graph-traversal queries (e.g. prerequisite-chain lookups). Runs
in a fully disabled no-op mode if `ARANGO_URL` isn't set or the connection
fails — MySQL remains the single source of truth for every API response.

## AI reliability
`model/mistral_client.py` is the only module allowed to call Mistral
directly. Every AI call is wrapped: retried with backoff, and on failure
(or on a response that fails Pydantic validation in `utils/ai_schemas.py`)
the caller falls back to a deterministic path —
`helper/fallback_exam_bank.py` for generation,
`helper/diagnostic_engine.py`'s `_synthesize_fallback_analysis` for
evaluation — both ported from the frontend's original Gemini-era
`server.ts` fallback logic. The exam response's `source` field
(`mistral-rag` vs `rag-engine-curated`) tells you which path was taken.

## Adaptive learning / gamification
- `helper/mastery_engine.py` — upserts per-topic mastery with configurable
  band thresholds (`MASTERY_THRESHOLD_*` env vars), never destroys history.
- `helper/misconception_engine.py` — opens/escalates/resolves
  misconception records based on evaluation results across submissions.
- `helper/adaptive_learning_engine.py` — updates learning-path node
  status/mastery, ported from the frontend's original client-side
  `handleExamComplete` logic (topic-substring matching against nodes).
- `helper/gamification_engine.py` — XP formula, badge unlock rules, and
  leaderboard ranking, all now computed server-side so the client can't
  submit its own XP total (see docs/FRONTEND_BACKEND_MAPPING.md §2.5).

All four run inside the same `POST /exams/{id}/submit` transaction, so a
submission's XP/mastery/badges/learning-path effects are atomic with the
submission itself.
