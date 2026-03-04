# Open Source + PyPI (pipx) Release Plan

- [x] Add packaging metadata (`pyproject.toml`) with runtime/dev extras and console scripts for server + CLI.
- [x] Add package version surface in `browser_bridge/__init__.py`.
- [x] Add repository hygiene files: `.gitignore`, `CONTRIBUTING.md`, GitHub Actions workflows for CI and trusted publishing.
- [x] Update `README.md` for open-source usage and publishing (pipx install, source install, extension flow, security notes).
- [x] Validate with tests and package build (`pytest`, `python -m build`, `twine check`) and update this checklist.
