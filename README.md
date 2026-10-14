# the_note_taker

A REST API for capturing and sharing notes with small teams. This initial
foundation provides a health check; note, team, and authentication features
will be added in subsequent steps.

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

