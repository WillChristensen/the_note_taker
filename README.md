# the_note_taker

A REST API for capturing and sharing notes with small teams. The service
currently provides a health check and a database schema for users, teams,
memberships, and notes. API endpoints for these workflows are not implemented
yet.

## Requirements

- Python 3.11 or newer

## Set up locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Run the service

```bash
uvicorn app.main:app --reload
```

The API is available at <http://127.0.0.1:8000>. Interactive API documentation
is available at <http://127.0.0.1:8000/docs>.

## Database

The default database is SQLite at `./note_taker.db`. Set the `DATABASE_URL`
environment variable to use a different SQLAlchemy database URL. User, Team, Membership,
and Note models define team creators, team roles (`owner` and `member`),
team-scoped notes, and one membership per user/team pair. User and team
deletion is represented by a `deleted_at` timestamp, so notes and authorship
are retained. Apply database schema changes with:

```bash
alembic upgrade head
```

Set `DATABASE_URL` to target a database other than the default SQLite file.
The migration history is stored under `migrations/`.

## Authentication configuration

Authentication requires a secret key of at least 32 characters. Configure it
in the environment before using authenticated endpoints:

```bash
export AUTH_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Access tokens expire after 30 minutes by default. Set
`AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` to a positive integer to change the lifetime.
Do not commit or reuse production secrets in source control.

## Health check

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status": "ok"}
```

## Run tests

```bash
python -m pytest
```
