# API Documentation

Base path: `/api/v1`. All responses use the envelope:

```json
{ "success": true, "data": { ... } }
{ "success": false, "error": { "code": "SOME_CODE", "message": "Human readable" } }
```

Auth: `Authorization: Bearer <accessToken>` unless marked **Public**.
Roles shown are enforced server-side via `@roles_required(...)`.

## Auth
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| POST | `/auth/register` | Public | Creates a PARENT account. Returns `{user, accessToken, refreshToken}`. |
| POST | `/auth/login` | Public | `{email, password}` → tokens. |
| POST | `/auth/child-login` | Parent | `{studentId, pin}` → a STUDENT-scoped access token, after verifying the child belongs to the caller and the PIN matches. |
| POST | `/auth/refresh` | Public (refresh token in body) | Rotates the refresh token; returns a new pair. |
| POST | `/auth/logout` | Any | Revokes the given refresh token. |

## Parents & children
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| GET | `/parents/me` | Parent | Profile + subscription tier. |
| GET | `/parents/me/children` | Parent | List of `ChildAccount`. |
| POST | `/parents/me/children` | Parent | Enforces `maxChildren` from the plan. |
| PUT | `/parents/me/children/{id}` | Parent (owns child) | Partial update. |
| DELETE | `/parents/me/children/{id}` | Parent (owns child) | |
| GET | `/parents/me/children/{id}/overview` | Parent (owns child) | Dashboard aggregate: child + recent exams + topic mastery. |
| GET | `/parents/me/children/{id}/learning-path` | Parent (owns child) | `LearningPathNode[]`. |

## Students (self-service, STUDENT-scoped tokens from `/auth/child-login`)
| Method | Endpoint | Auth |
|---|---|---|
| GET | `/students/me` | Student |
| GET | `/students/me/overview` | Student |
| GET | `/students/me/learning-path` | Student |

## Teachers
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| GET | `/teachers` | Any authenticated | Directory for PTC. |
| GET | `/teachers/me/students` | Teacher | |
| GET | `/teachers/me/students/{id}/performance` | Teacher (assigned) | |
| GET | `/teachers/me/students/{id}/mastery` | Teacher (assigned) | |
| GET | `/teachers/me/students/{id}/diagnostics` | Teacher (assigned) | Misconceptions list. |

## Exams
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| POST | `/exams/generate` | Parent or Student | Re-checks subscription quota server-side regardless of client state. Response never includes `correctAnswer`. |
| POST | `/exams/{examId}/submit` | Parent or Student (owns exam) | `{answers, timeTakenSeconds}`. Triggers evaluation, AI/fallback diagnostic analysis, mastery/misconception/learning-path updates, XP + badge awards — all server-side, atomically. Returns 409 on double-submit. |

## Runbooks (K-Graph)
| Method | Endpoint | Auth |
|---|---|---|
| GET | `/runbooks` | Public — `?board=&classGrade=&subject=` |
| GET | `/runbooks/{id}` | Public |
| POST | `/runbooks` | Admin |
| PUT | `/runbooks/{id}` | Admin |
| DELETE | `/runbooks/{id}` | Admin |

## Gamification
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| GET | `/gamification/badges` | Public | Badge catalog. |
| POST | `/gamification/award-xp` | Parent or Student | Backs Fun Zone mini-games; amount capped 1-100 server-side. |
| GET | `/leaderboard?period=daily\|weekly\|monthly\|all_time` | Public | |

## Parent-teacher communication
| Method | Endpoint | Auth |
|---|---|---|
| GET/POST | `/conversations` | Parent |
| GET | `/conversations/{id}` | Parent or Teacher (party to it) |
| POST | `/conversations/{id}/messages` | Parent or Teacher (party to it) |
| PUT | `/messages/{id}/read` | Any authenticated |
| POST/GET | `/dossiers` | Parent |

## Subscriptions
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| GET | `/subscriptions/plans` | Public | |
| POST | `/subscriptions/upgrade` | Parent | `{tier}`. No payment processor wired up — see docs/FRONTEND_BACKEND_MAPPING.md §2.7. |

## Admin
| Method | Endpoint | Auth |
|---|---|---|
| GET | `/admin/statistics` | Public (matches original unauthenticated `/api/stats`) |
| GET | `/admin/dashboard` | Admin |
| GET | `/admin/users` | Admin — paginated |
| GET | `/admin/students` | Admin — paginated |
| POST | `/admin/children/{id}/reset-quota` | Admin or owning Parent |

## Files (RAG document ingestion)
| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| POST | `/files/upload` | Admin | multipart `file` + optional `board`/`classGrade`/`subject`/`runbookId`. Runs extract → chunk → embed (Mistral) → ChromaDB. |
| GET | `/files/{id}` | Admin | Ingestion status. |

## Health
| Method | Endpoint | Auth |
|---|---|---|
| GET | `/health` | Public — reports DB, vector store, knowledge graph, and Mistral configuration status. |

## Error codes worth knowing
`VALIDATION_ERROR` (422), `UNAUTHORIZED`/`TOKEN_EXPIRED`/`TOKEN_INVALID` (401),
`FORBIDDEN` (403), `NOT_FOUND` (404), `ALREADY_SUBMITTED` (409),
`QUOTA_EXCEEDED` (429), `RATE_LIMITED` (429), `INTERNAL_ERROR` (500).
