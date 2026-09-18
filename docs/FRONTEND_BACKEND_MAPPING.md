# FRONTEND → BACKEND MAPPING
### AcuGrade AI — Adaptive Learning & Assessment Platform

This document is the output of Steps 1–5 of the build process: a full inspection
of the existing frontend (`772555_acugrade-rag-learning-assessment-platform.zip`),
before any backend code is written.

---

## 0. What the frontend actually is

- **Stack**: Vite + React 19 + TypeScript, built via **Google AI Studio**
  (`metadata.json` → `majorCapabilities: MAJOR_CAPABILITY_SERVER_SIDE_GEMINI_API`).
  A thin **Express** server (`server.ts`) serves Vite in dev and static files in
  prod, and hosts a handful of API routes.
- **AI provider in use today**: **Gemini** (`@google/genai`, model
  `gemini-3.7-flash`), *not* Mistral. The master prompt's Mistral requirement is
  a deliberate provider swap, not something the frontend already expects — the
  frontend has no knowledge of which model answers `/api/generate-exam`.
- **Auth**: **none**. There is no login/signup screen, no session, no token
  handling anywhere in the code. The app boots straight into one hardcoded
  demo account (`DEMO_PARENT_ACCOUNT` in `src/data/initialData.ts`) and lets
  you switch between a "parent" and a "child" persona via a menu. Children
  have a `pin` field (used as a display/reset value in the Admin panel and Add
  Child form) but it is never checked against anything — it is not a real
  authentication mechanism today.
- **Persistence**: **none on the client**. Everything except runbooks/exam
  generation/evaluation lives in `useState` in `App.tsx`, seeded from
  `src/data/initialData.ts`, `src/data/runbooks.ts`, `src/data/funData.ts`.
  Refreshing the page resets the entire app. The Express server itself only
  persists runbooks in an in-memory array (`runbooksStore`) that resets on
  restart — there is no database anywhere in the current system.
- **Only 6 endpoints currently exist**, all in `server.ts`:
  `GET /api/health`, `GET/POST/PUT/DELETE /api/runbooks[/:id]`,
  `POST /api/generate-exam`, `POST /api/evaluate-exam`, `GET /api/stats`.
  Every other "workflow" below (accounts, XP, badges, leaderboard, messaging,
  dossiers, subscriptions) is simulated entirely in frontend state and has
  **no existing API to preserve compatibility with** — these are net-new
  backend surfaces, free to design cleanly, as long as the request/response
  shapes match what the relevant component already expects to receive back.

Mapping legend used below:

`Frontend Component → Existing Mock/State → Required API → Request → Response → DB Tables`

---

## 1. Already-implemented contract (must be preserved or deliberately replaced)

These are real, working endpoints today. The Python backend must offer
functionally equivalent endpoints (same request/response shape) so the
frontend needs **zero changes**, even though the implementation moves from
Node/Gemini/in-memory to Python/Mistral/MySQL+RAG.

### 1.1 Exam generation
**Component**: `ExamArena.tsx` (`handleStartExam`)
**Mock data replaced**: none — already server-backed
**API**: `POST /api/v1/exams/generate` (was `POST /api/generate-exam`)
**Request** (exact fields sent today):
```json
{
  "board": "CBSE",
  "classGrade": "Class 10",
  "subject": "Mathematics",
  "difficulty": "medium",
  "studentName": "Ananya",
  "studentWeakTopics": ["Quadratic Equations"]
}
```
`studentWeakTopics` is derived client-side from `activeChild.topicMastery`
(topics scoring `< 75`) — the backend should derive this itself from stored
mastery once persistence exists, rather than trusting the client's list.
**Response**:
```json
{ "success": true, "source": "gemini-rag", "exam": { "...Exam object per types.ts...": null } }
```
`source` is either `"gemini-rag"` (AI path) or `"rag-engine-curated"`
(fallback path) — keep this field; the frontend doesn't currently render it
but it's useful telemetry.
**DB tables**: `exams`, `questions`, `students`, `runbooks` (for retrieval),
`mastery` (to compute weak topics server-side).

### 1.2 Exam evaluation
**Component**: `ExamArena.tsx` (`handleSubmitExam`)
**API**: `POST /api/v1/exams/{exam_id}/submit` (was `POST /api/evaluate-exam`)
**Request**:
```json
{
  "exam": { "...full Exam object, echoed back by client...": null },
  "answers": { "questionId1": "B", "questionId2": "42" },
  "timeTakenSeconds": 340,
  "studentId": "child-01",
  "studentName": "Ananya"
}
```
Note: the client currently sends the **entire exam object back**, including
`correctAnswer` per question — i.e. today the correct answers round-trip
through the browser in plaintext between generation and submission. Master
prompt §14 explicitly forbids exposing `correct_answer` before submission.
**This is a required frontend-breaking security fix**: the new backend should
store the generated exam server-side keyed by `exam_id` and have the client
send only `{ exam_id, answers, time_taken_seconds }`. Flag in
`FRONTEND_CHANGES_REQUIRED.md`.
**Response**: `{ "success": true, "submission": { "...ExamSubmission per types.ts...": null } }`
**DB tables**: `exam_submissions`, `question_evaluations`, `diagnostic_analyses`,
`mastery` (upserted from `kGraphInsights`), `misconceptions`.

### 1.3 Runbook / K-Graph CRUD
**Component**: `SuperAdminPanel.tsx`
**API**: `GET/POST/PUT/DELETE /api/v1/runbooks[/{id}]` (was `/api/runbooks[/:id]`)
**List request**: query params `?board=&classGrade=&subject=` (all optional,
case-insensitive match).
**Create request**:
```json
{
  "board": "CBSE", "classGrade": "Class 10", "subject": "Mathematics",
  "chapterName": "string",
  "coreConcepts": ["line 1", "line 2"],
  "keyFormulasOrRules": ["..."],
  "commonTraps": ["..."],
  "sampleQuestionArchetypes": ["..."],
  "curatedReferenceUrls": [{ "title": "", "source": "", "url": "", "description": "", "type": "official_syllabus" }]
}
```
(Textareas are split on newline client-side into these arrays — backend
should accept arrays, not raw text.)
**Response** (all CRUD ops): `{ "success": true, "data": RunbookKGraphNode, "message"?: string }`
**DB tables**: `runbooks` (+ optionally mirrored into the ArangoDB knowledge
graph per master prompt §30 — the frontend has no opinion on this, it only
consumes the flat JSON shape).

### 1.4 Stats
**Component**: `SuperAdminPanel.tsx` (analytics tab)
**API**: `GET /api/v1/admin/statistics` (was `GET /api/stats`)
**Response**:
```json
{
  "success": true, "totalExamsGenerated": 432, "totalExamsCompleted": 389,
  "totalRunbooks": 12,
  "supportedBoards": ["CBSE","ICSE","ISC","UK-Cambridge","NCERT","NEET","IIT"],
  "supportedGrades": ["Class 5", "...", "Class 12"],
  "averagePlatformScore": 7.8
}
```
**DB tables**: aggregate queries over `exams`, `exam_submissions`, `runbooks`.

### 1.5 Health
`GET /api/v1/health` → `{ "status": "ok", "time": "<iso>" }`. Trivial;
extend to check DB/vector-store/Mistral connectivity per master prompt §5/§37.

---

## 2. Net-new backend surfaces (currently frontend-only state)

None of these have an existing API contract to preserve — design them
following the `ChildAccount`/`ParentAccount`/etc. shapes in `types.ts`, since
that's what every component already expects to receive.

### 2.1 Authentication & session
**Component**: none exists yet (`App.tsx` just hardcodes `DEMO_PARENT_ACCOUNT`)
**Required for**: every other endpoint below (all need a real user identity
instead of the hardcoded demo parent + free-text `activeChildId`)
**API**: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`,
`POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`
**Request/Response**: standard email+password → JWT access/refresh pair, per
master prompt §7. Child "login" should map to PIN verification against
`children.pin_hash`, scoped to the parent's account, matching the existing
`pin` field's intent in `AddChildModal.tsx`.
**DB tables**: `users`, `refresh_tokens` (or a revocation list).
**Frontend change required**: replace `DEMO_PARENT_ACCOUNT` bootstrapping
with a login screen and token storage. Document in
`FRONTEND_CHANGES_REQUIRED.md`.

### 2.2 Parent account & children
**Component**: `ParentDashboard.tsx`, `AddChildModal.tsx`, `Header.tsx`
**Mock data replaced**: `INITIAL_PARENT` (`initialData.ts`)
**APIs**:
- `GET /api/v1/parents/me` → `ParentAccount` minus `children` array inline
- `GET /api/v1/parents/me/children` → `ChildAccount[]`
- `POST /api/v1/parents/me/children` — **request body** (from
  `AddChildModal.onAddChild`, i.e. `ChildAccount` minus server-computed
  fields):
  ```json
  { "name": "", "avatar": "👦", "classGrade": "Class 8", "targetBoard": "CBSE", "schoolName": "", "pin": "1234" }
  ```
  Server sets: `id`, `totalExamsTaken: 0`, `averageScore: 0`, `streakDays: 1`,
  `dailyExamsTakenToday: 0`, `xp: 250`, `level: 1`,
  `earnedBadgeIds: ["badge-pioneer"]`, `topicMastery: {}`.
- `PUT /api/v1/parents/me/children/{id}` — full `ChildAccount` (from
  `onUpdateChild`)
- `DELETE /api/v1/parents/me/children/{id}` (prop exists on
  `ParentDashboardProps` as optional `onDeleteChild` but is not wired up
  anywhere yet — implement the endpoint, frontend wiring is a small future
  addition, not a blocker)
**Response shape**: exactly `ChildAccount` per `types.ts`.
**DB tables**: `users` (role=PARENT), `students` (role=STUDENT, FK
`parent_id`), enforcing the maxChildren quota from the parent's subscription
tier (§27) server-side — the frontend's `AddChildModal` does not currently
enforce this itself.
**Authorization**: parent must own the student — see master prompt §8; the
frontend has no ownership-check UI, so this is purely a backend contract to
add safely.

### 2.3 Dashboard aggregation
**Component**: `ParentDashboard.tsx`
**Mock data replaced**: `examHistory` prop (currently `[SAMPLE_SUBMISSION]`
in `App.tsx`)
**API**: `GET /api/v1/parents/me/children/{student_id}/overview` — one
aggregated call per master prompt §24/§33, returning what the dashboard
currently assembles client-side from separate state arrays:
```json
{
  "child": { "...ChildAccount...": null },
  "recentExams": [ "...ExamSubmission[] (trimmed, most recent N)...": null ],
  "topicMastery": { "Quadratic Equations": 82 }
}
```
**DB tables**: `students`, `exam_submissions`, `mastery`.

### 2.4 Adaptive learning path
**Component**: `AdaptiveLearningPath.tsx`
**Mock data replaced**: `INITIAL_LEARNING_PATHS` (`initialData.ts`),
mutated client-side in `App.tsx`'s `handleExamComplete` after every exam.
**API**:
- `GET /api/v1/parents/me/children/{student_id}/learning-path` →
  `LearningPathNode[]` (exact shape per `types.ts`: `status`
  `locked|available|in_progress|mastered|remedial_needed`, `level`
  `foundational|intermediate|advanced_hots`, plus `attemptsCount`,
  `lastScore` — note these last two fields are referenced in `App.tsx` but
  **missing from `LearningPathNode` in `types.ts`**; add them when porting
  the type server-side, see §5 below.)
- Path nodes update automatically as a side effect of exam submission
  (§1.2) — no separate "update path" endpoint is called by the frontend
  today, so the recompute should happen inside the submit-exam transaction
  server-side, mirroring `App.tsx`'s node-matching-by-topic-substring logic
  (replace with a real `topic_id` join once curriculum/topic tables exist).
**DB tables**: `learning_path_nodes` (per student), `topics`,
`topic_prerequisites`.

### 2.5 Gamification
**Component**: `GamificationHub.tsx`
**Mock data replaced**: `BADGES_LIST`, `INITIAL_LEADERBOARD` (`initialData.ts`)
**APIs**:
- `GET /api/v1/gamification/badges` → `Badge[]` (catalog; tiers
  bronze/silver/gold/diamond, categories mastery/streak/score/speed/explorer)
- `GET /api/v1/leaderboard?period=daily|weekly|monthly|all_time` →
  `LeaderboardEntry[]`
- XP/level/badge/leaderboard updates are **not** a separate frontend call —
  in `App.tsx` they're computed inline inside `handleExamComplete` (exam XP:
  `marks*10 + 50 perfect bonus + 25 speed bonus + 30 streak bonus`) and
  inside `handleAwardXP` (Fun Zone games). Both should become
  server-side effects of `POST /exams/{id}/submit` and a new
  `POST /api/v1/gamification/award-xp` endpoint for Fun Zone, rather than
  client-computed values sent to the server — the client must not be trusted
  to compute its own XP.
- ⚠️ **Bug found in current frontend**: `App.tsx`'s leaderboard-update
  callbacks (`handleExamComplete`, `handleAwardXP`) read/write
  `entry.points` and `entry.id`, but `LeaderboardEntry` in `types.ts` only
  defines `xp` and `studentId` — `points`/`id` don't exist on the type. This
  looks like a leftover from a refactor. **Build the backend against the
  canonical `types.ts` field names (`xp`, `studentId`)** and flag the
  mismatch in `FRONTEND_CHANGES_REQUIRED.md` so the frontend state logic
  gets corrected to match once wired to a real API.
**DB tables**: `badges` (catalog), `student_badges`, `leaderboard` (or a
view computed from `students`/`exam_submissions`), `xp_events` (audit trail
of XP awards, so nothing is only in a mutable counter).

### 2.6 Parent–teacher communication
**Component**: `ParentTeacherCommunication.tsx`
**Mock data replaced**: `TEACHER_CONTACTS`, `INITIAL_PT_MESSAGES`,
`INITIAL_SHARED_DOSSIERS` (`initialData.ts`)
**APIs**:
- `GET /api/v1/teachers` (or scoped to the child's school) →
  `TeacherContact[]`
- `GET /api/v1/conversations` / `GET /api/v1/conversations/{id}` →
  `ParentTeacherMessage[]` grouped by `(parentId, teacherId, childId)`
- `POST /api/v1/conversations/{id}/messages` — **request** (from
  `onSendMessage` in `App.tsx`):
  ```json
  {
    "teacherId": "", "teacherName": "", "childId": "", "childName": "",
    "message": "", "attachedSubmissionId": "opt", "attachedSubmissionTitle": "opt",
    "actionItems": ["opt"]
  }
  ```
  Server sets `id`, `senderRole` (from auth context, not client), `timestamp`,
  `status: "sent"`.
- `PUT /api/v1/messages/{id}/read` — defined in the master prompt (§26) but
  **no frontend UI currently triggers a read-status change**; the `status`
  field (`sent|delivered|read|action_taken`) exists on the type but is never
  mutated in the current code. Implement the endpoint per spec; frontend
  wiring is a small future addition.
- `POST /api/v1/dossiers` — **request** (from `onCreateDossier`):
  ```json
  { "childId": "", "childName": "", "parentName": "", "notes": "", "recipients": ["email"], "includedSubmissionsCount": 3 }
  ```
  Server generates `id`, `shareToken` (currently a client-side
  `Math.random()` string like `ACU-SHARE-XXXXXX` — **move token generation
  server-side using a cryptographically secure generator**, flag as a
  security fix), `createdAt`, `expiresAt` (30 days), `status: "active"`.
**DB tables**: `teachers`, `conversations`, `messages`, `shared_dossiers`.

### 2.7 Subscription & quota
**Component**: `SubscriptionPlans.tsx`, `SuperAdminPanel.tsx` (subscriptions
tab), gating logic in `ExamArena.tsx` (`hasReachedDailyLimit`)
**Mock data replaced**: `SUBSCRIPTION_PLANS` (`initialData.ts`)
**APIs**:
- `GET /api/v1/subscriptions/plans` → `SubscriptionPlan[]` (static catalog:
  `free` / `scholar_pro` $9-89 / `genius_competitive` $19-189, with
  `dailyExamLimit` and `maxChildren`, one of which is `'unlimited'`)
- `POST /api/v1/subscriptions/upgrade` — request `{ "tier": "scholar_pro" }`
  → updates `parentAccount.subscriptionTier`. **Today this just flips client
  state instantly with no payment step** — master prompt doesn't specify a
  payment processor either, so treat this as an admin/self-service tier
  change for now and flag real billing integration as a known limitation.
- Daily quota check must move server-side: `ExamArena.tsx` currently reads
  `activeChild.dailyExamsTakenToday >= 1` purely from client state to decide
  whether to allow exam generation. Per master prompt §27 ("never trust
  subscription information from the frontend"), `POST /exams/generate` must
  itself re-check quota against the DB and reject with a structured error
  if exceeded, rather than relying on the client's pre-check.
- `POST /api/v1/admin/children/{id}/reset-quota` — from
  `SuperAdminPanel`'s `onResetChildQuota` / `handleResetDailyQuota`.
**DB tables**: `subscriptions` (per parent: tier, status, start/end,
quota_used), `subscription_plans` (or a static config table).

### 2.8 Admin dashboard
**Component**: `SuperAdminPanel.tsx`
**Already covered**: runbook CRUD (§1.3), stats (§1.4), quota reset (§2.7).
**Additional (implied by role, not yet in frontend)**: `GET
/api/v1/admin/users`, `GET /api/v1/admin/students` — master prompt §28 lists
these; the current frontend has no user/student management table beyond
runbooks and subscriptions, so these are speculative additions to support
later, not required to match an existing UI element today.

### 2.9 Fun Zone
**Component**: `FunZone.tsx`
**Mock data replaced**: `src/data/funData.ts` (jokes/anecdotes/facts +
mini-game logic — all games run entirely client-side, e.g. speed-math,
memory-match, word-scramble)
**API**: only the XP payout needs a backend call —
`POST /api/v1/gamification/award-xp` with `{ "amount": 25, "reason":
"speed-math-win" }` (from `onAwardXP`). The joke/anecdote content and game
logic itself can stay static/client-side; there's no indication in the
frontend that this needs to be dynamic or AI-generated.
**DB tables**: none required beyond the `xp_events` table from §2.5, unless
you want to persist joke "like" counts (`ScienceJokeOrAnecdote.likesCount`)
server-side — currently that's client-only too.

### 2.10 Static content
**Components**: `BlogSection.tsx`, `AboutSection.tsx`, `LegalSection.tsx`
**Mock data**: `BLOG_POSTS` (`initialData.ts`), inline JSX for About/Legal
**Backend**: **none required.** Nothing in these components makes a fetch
call or expects dynamic data. Leave as static frontend content unless the
client specifically wants blog posts to become CMS-driven later — that would
be a scope addition, not something the current frontend expects.

---

## 3. Frontend issues to fix (→ `docs/FRONTEND_CHANGES_REQUIRED.md`)

1. **Exam answer key leakage**: `evaluate-exam` request re-sends the full
   exam object (including `correctAnswer` per question) from client to
   server. Must switch to `{ exam_id, answers }` once exams are persisted
   server-side (§1.2).
2. **No auth at all**: hardcoded `DEMO_PARENT_ACCOUNT`, no login screen
   (§2.1).
3. **Client-trusted quota check**: daily exam limit is only checked in
   `ExamArena.tsx` state, not enforced server-side (§2.7).
4. **Client-computed XP/leaderboard**: XP math and leaderboard sort/rank
   happen entirely in `App.tsx`, trivially spoofable once a real API exists
   (§2.5).
5. **`LeaderboardEntry` field mismatch**: `App.tsx` reads/writes
   `entry.points`/`entry.id`, which don't exist on the `LeaderboardEntry`
   type (`xp`/`studentId` do). A latent bug independent of the backend
   rewrite.
6. **`LearningPathNode` missing fields**: `App.tsx` reads/writes
   `node.attemptsCount` and `node.lastScore`, neither declared in
   `LearningPathNode` (`types.ts`). Add them to the type when the backend
   model is defined.
7. **Client-side share-token generation**: dossier `shareToken` is generated
   with `Math.random()` in the browser; move to a secure server-side
   generator (§2.6).
8. **Unwired props**: `ParentDashboardProps.onDeleteChild` and the
   message-read endpoint have no caller in the UI yet — safe to implement
   server-side ahead of frontend wiring, but not something you'll see
   exercised end-to-end without adding the missing buttons.

---

## 4. Consolidated `/api/v1` endpoint list

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

GET    /api/v1/parents/me
GET    /api/v1/parents/me/children
POST   /api/v1/parents/me/children
PUT    /api/v1/parents/me/children/{id}
DELETE /api/v1/parents/me/children/{id}
GET    /api/v1/parents/me/children/{id}/overview
GET    /api/v1/parents/me/children/{id}/learning-path

GET    /api/v1/runbooks
GET    /api/v1/runbooks/{id}
POST   /api/v1/runbooks
PUT    /api/v1/runbooks/{id}
DELETE /api/v1/runbooks/{id}

POST   /api/v1/exams/generate
POST   /api/v1/exams/{exam_id}/submit

GET    /api/v1/gamification/badges
POST   /api/v1/gamification/award-xp
GET    /api/v1/leaderboard

GET    /api/v1/teachers
GET    /api/v1/conversations
GET    /api/v1/conversations/{id}
POST   /api/v1/conversations/{id}/messages
PUT    /api/v1/messages/{id}/read
POST   /api/v1/dossiers

GET    /api/v1/subscriptions/plans
POST   /api/v1/subscriptions/upgrade

GET    /api/v1/admin/dashboard
GET    /api/v1/admin/statistics
GET    /api/v1/admin/users
GET    /api/v1/admin/students
POST   /api/v1/admin/children/{id}/reset-quota

GET    /api/v1/health
```

---

## 5. Notes for schema design (Section 6 of the build process)

- Curriculum taxonomy (`Board → Grade → Subject → Chapter/Runbook → Topic →
  Concept`, master prompt §9) has **no dedicated tables implied by the
  frontend** — the frontend treats board/grade/subject as flat string enums
  (`types.ts` `Board`, `ClassGrade`, `Subject`) and topics as free-text
  strings inside `Question.topic` / `ChildAccount.topicMastery` /
  `RunbookKGraphNode.chapterName`. Normalizing these into real
  `topics`/`concepts` tables is a backend-side improvement the frontend
  doesn't require but will benefit from (enables real `topic_id` joins
  instead of substring matching, as seen in `App.tsx`'s learning-path
  update logic).
- `RunbookKGraphNode` is today the *only* structured curriculum content —
  it should map directly to master prompt §10's Runbook model, with the
  metadata fields from §11 (board/grade/subject/chapter/difficulty) attached
  for RAG retrieval filtering.
