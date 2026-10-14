# The Note Taker

A REST API foundation for capturing and sharing notes with small teams. The
current API supports health checks, registration, login, team creation and
listing, owner-managed team memberships, and note creation and listing. Note
retrieval, updates, and deletion are not implemented yet.

## Requirements

- Python 3.11 or newer
- GNU Make

## Set up and run

```bash
make setup
export AUTH_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
make verify
make run
```

`make verify` runs the tests and applies the latest migration to the configured
database. `make run` applies migrations and starts the development server at
<http://127.0.0.1:8000>. Interactive API docs are available at
<http://127.0.0.1:8000/docs>.

The commands use `.venv/bin/python`; set `PYTHON` when running `make setup` if
you need a different Python interpreter.

## Configuration and database

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./note_taker.db` | SQLAlchemy database URL |
| `AUTH_SECRET_KEY` | Required for login/token validation | JWT signing key, at least 32 characters |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Positive token lifetime in minutes |

Keep secrets out of source control. The database schema is managed by Alembic
under `migrations/`. Apply pending schema changes with `make db-upgrade`.
SQLite is the default for a simple local setup; the URL can be configured for
another SQLAlchemy-supported database.

Users and teams are soft-deleted with a `deleted_at` timestamp. This preserves
notes and authorship; deleted users cannot log in or use existing tokens.

## API

The public endpoints are `GET /health`, `POST /auth/register`, and
`POST /auth/token`. All other endpoints require a bearer access token. To
authenticate, register, then log in using the email in the OAuth2 `username`
field:

```bash
curl -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"person@example.com","password":"a secure password"}'

curl -X POST http://127.0.0.1:8000/auth/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=person@example.com' \
  --data-urlencode 'password=a secure password'
```

Copy `access_token` from the login response and set it in your shell:

```bash
export ACCESS_TOKEN='paste-access-token-here'
```

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | Public | Health check |
| `POST` | `/auth/register` | Public | Register with a unique email and 8–128 character password |
| `POST` | `/auth/token` | Public | Log in and receive a bearer token |
| `POST` | `/teams` | Authenticated | Create a team; creator becomes its owner |
| `GET` | `/teams` | Authenticated | List active teams the caller belongs to |
| `GET` | `/teams/{team_id}/members` | Team owner | List active members of a team |
| `POST` | `/teams/{team_id}/members` | Team owner | Add an existing active user by email as a member |
| `POST` | `/teams/{team_id}/notes` | Team member | Create a note in an active team |
| `GET` | `/teams/{team_id}/notes` | Team member | List team notes, newest first |

Example team and membership requests:

```bash
curl -X POST http://127.0.0.1:8000/teams \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Product Team"}'

curl http://127.0.0.1:8000/teams \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -X POST http://127.0.0.1:8000/teams/1/members \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email":"colleague@example.com"}'

curl http://127.0.0.1:8000/teams/1/members \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -X POST http://127.0.0.1:8000/teams/1/notes \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Planning","content":"Discuss launch timeline."}'

curl 'http://127.0.0.1:8000/teams/1/notes?limit=20&offset=0' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Note authorship is always taken from the access token, not request data. Only
active team members can create or list notes; non-members receive
`403 Forbidden`, and missing or soft-deleted teams receive `404 Not Found`.
Note listing defaults to 20 results and supports `limit` values from 1 to 100
and non-negative `offset` values. Results are ordered by creation time
descending, with note ID descending as a stable tie-breaker.

Registration returns `409 Conflict` for an existing email; malformed input
returns `422 Unprocessable Entity`. Invalid login/token requests return
`401 Unauthorized`. A non-owner attempting membership management receives
`403 Forbidden`; unknown or deleted teams/users return `404 Not Found`.

## Design choices

- **SQLite and SQLAlchemy/Alembic:** SQLite keeps local setup lightweight, while
  SQLAlchemy models and versioned migrations make the schema explicit and
  support a future move to a server database.
- **Argon2 password hashes and short-lived JWTs:** passwords are never stored
  in plaintext, and bearer tokens expire after 30 minutes by default. Token
  signing uses a required environment secret rather than a committed key.
- **Soft deletion and team-scoped authorization:** deleted users and teams are
  marked rather than immediately erased, preserving note authorship and team
  data. Membership checks restrict team information to owners or members as
  appropriate.

## If I had more time

I would implement note retrieval, updates, and deletion with membership checks;
add invitation and account-recovery flows; and exercise the migration path
against PostgreSQL. I would also define an explicit
retention/anonymization policy for soft-deleted accounts and teams before
implementing permanent data purging.

## Tests

```bash
make test
```

Tests use isolated temporary SQLite databases and cover authentication,
authorization, model constraints, and migration upgrade/downgrade behavior.
