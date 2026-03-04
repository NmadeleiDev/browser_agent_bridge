# Contributing

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run tests

```bash
pytest -v
```

## Build package

```bash
python -m build
python -m twine check dist/*
```

## Pull requests

- Keep changes scoped to one goal.
- Add or update tests for behavior changes.
- Update `README.md` when CLI/server behavior or setup changes.
