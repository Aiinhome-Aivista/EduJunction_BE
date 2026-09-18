# Frontend Changes Required (and Made)

Per the master prompt's instruction to only touch the frontend where
integration absolutely requires it, and to document every such change here.

## Files added

- `src/lib/api.ts` — the single API client. Token storage (localStorage),
  silent refresh-on-401, and one typed function per backend endpoint. No UI
  component talks to `fetch()` directly anymore except where noted below.
- `src/components/LoginPage.tsx` — replaces the hardcoded
  `DEMO_PARENT_ACCOUNT` bootstrap with real login/registration against
  `POST /api/v1/auth/login` and `/register`.

## Files edited

### `src/App.tsx` (extensive)
- Removed all mock-data imports (`DEMO_PARENT_ACCOUNT`, `SAMPLE_SUBMISSION`,
  `INITIAL_LEARNING_PATHS`, `BADGES_LIST`, `INITIAL_LEADERBOARD`,
  `TEACHER_CONTACTS`, `INITIAL_PT_MESSAGES`, `INITIAL_SHARED_DOSSIERS`).
- Added an auth gate: renders `LoginPage` when no valid token is stored,
  a loading screen while the account bootstraps, and a stripped-down admin
  shell for ADMIN/SUPER_ADMIN sessions (which aren't parents and have no
  family data to show).
- Every handler that used to mutate local state directly (`handleAddChild`,
  `handleUpdateChild`, `handleUpgradeTier`, `handleResetDailyQuota`,
  `handleSendMessage`, `handleCreateDossier`, `handleAwardXP`) now calls the
  corresponding backend endpoint first and syncs local state from the
  response — the client no longer computes XP, badges, leaderboard rank, or
  mastery client-side (see docs/FRONTEND_BACKEND_MAPPING.md §2.5 for why the
  original version was unsafe to trust).
- `handleExamComplete` no longer computes XP/badges/mastery/learning-path
  updates itself (all of that already happened server-side inside
  `POST /exams/{id}/submit`); it just displays the report and resyncs.
- Added a "Log out" action in the persona dropdown menu (there was no way to
  log out before, since there was no login).
- Removed the PIN display badge in the child-switcher dropdown
  (`PIN: {child.pin}`) — the backend never returns a child's PIN (only a
  bcrypt hash is stored, and it's never serialized into any API response),
  so there is nothing to display anymore. This is a deliberate security
  improvement, not a regression: the original mock data exposed a
  plaintext PIN via `ChildAccount.pin` for convenience.

### `src/components/ExamArena.tsx`
- Both `fetch('/api/generate-exam', ...)` and `fetch('/api/evaluate-exam',
  ...)` replaced with `examApi.generate()` / `examApi.submit()`.
- **Security fix**: the original submit call sent the *entire* exam object
  back to the server, including every `correctAnswer` — meaning the answer
  key round-tripped through the browser between generation and submission.
  The new flow only sends `{ answers, timeTakenSeconds }`; the backend
  already has the exam (with answers) stored server-side from the
  `/generate` call, keyed by `exam.id`.
- `studentWeakTopics` is no longer computed client-side and sent to the
  server — the backend now derives weak topics itself from the student's
  stored `mastery` table (`helper/exam_generator.py:get_weak_topics`),
  since a client-reported "weak topics" list isn't a safe personalization
  input.

### `src/components/SuperAdminPanel.tsx`
- All four `fetch('/api/runbooks...')` / `fetch('/api/stats')` calls
  replaced with `runbookApi.*()` / `adminApi.statistics()`, which route
  through the shared client and attach the admin's bearer token
  automatically for the create/update/delete calls (list and statistics
  remain public reads, matching the original unauthenticated behavior).

### `vite.config.ts`
- Added a dev-server proxy (`/api` → `http://localhost:8000` by default,
  overridable via `VITE_API_PROXY_TARGET`) so every component can keep
  using relative `fetch('/api/v1/...')` paths exactly as the original code
  did against the old Express server — no component needed to learn a new
  base URL.

### `package.json`
- Removed `express`, `dotenv`, `@google/genai`, and `esbuild` — none of
  these are used anymore now that the Python backend replaces both the
  Express dev/prod server and the direct Gemini integration.
- `dev`/`build`/`preview` scripts now call plain `vite` instead of
  `tsx server.ts` / bundling `server.ts` for production.

## Files removed

- `server.ts` — the original Express server (health check, runbook CRUD,
  exam generate/evaluate, stats) is now entirely superseded by the Python
  backend in `/backend`. Its logic wasn't deleted, it was ported: the exam
  generation prompt, the fallback question bank, the evaluation matching
  logic, and the fallback diagnostic synthesizer all live on in
  `helper/exam_generator.py`, `helper/fallback_exam_bank.py`,
  `helper/evaluation_engine.py`, and `helper/diagnostic_engine.py`
  respectively — just swapped from calling Gemini to calling Mistral.
- `.env.example` (the frontend's original one, which only declared
  `GEMINI_API_KEY`/`APP_URL` for the AI-Studio-hosted Gemini integration) —
  no longer applicable now that the frontend makes no direct AI calls.

## Deliberately left untouched

- `SubscriptionPlans.tsx` still renders its plan cards from the static
  `SUBSCRIPTION_PLANS` array in `src/data/initialData.ts` rather than
  fetching `GET /api/v1/subscriptions/plans`. This was a scope trade-off:
  the seeded backend data (`seed_db.py`) is byte-for-byte identical to that
  array, so the displayed content is accurate either way, and only the
  `onUpgradeTier` action needed to become a real API call (which it now
  is). Swapping the catalog to a fetched list is a small follow-up if
  the two are ever allowed to drift.
- `BlogSection.tsx` still renders `SAMPLE_BLOG_POSTS` — this is genuinely
  static content with no backend endpoint behind it, consistent with
  docs/FRONTEND_BACKEND_MAPPING.md §2.10.
- All game logic and content inside `FunZone.tsx` (jokes, anecdotes, the
  mini-games themselves) stays entirely client-side; only the XP payout at
  the end of a game now calls the backend.
