#!/usr/bin/env bash
# EABench Python Installation Script
# Usage: bash install.sh [--dev]
#
# This script creates a virtual environment and installs all required dependencies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

echo "==> EABench Python Setup"
echo "    Working directory: ${SCRIPT_DIR}"

# Check Python version (3.10+)
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.10 or later."
    exit 1
fi

PY_VERSION=$("${PYTHON_BIN}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("${PYTHON_BIN}" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("${PYTHON_BIN}" -c "import sys; print(sys.version_info.minor)")

if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ is required (found ${PY_VERSION})."
    exit 1
fi
echo "    Python ${PY_VERSION} found at: $(command -v ${PYTHON_BIN})"

# Create virtual environment
if [ ! -d "${VENV_DIR}" ]; then
    echo "==> Creating virtual environment at ${VENV_DIR} ..."
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# Activate virtual environment
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
echo "==> Activated virtual environment"

# Upgrade pip
pip install --quiet --upgrade pip

# Install dependencies
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"
if [ -f "${REQUIREMENTS}" ]; then
    echo "==> Installing dependencies from requirements.txt ..."
    pip install -r "${REQUIREMENTS}"
else
    echo "WARNING: requirements.txt not found at ${REQUIREMENTS}"
fi

# Install dev dependencies if requested
if [[ "${1:-}" == "--dev" ]]; then
    echo "==> Installing development dependencies ..."
    pip install pytest pytest-asyncio black ruff
fi

echo ""
echo "==> Installation complete!"
echo ""
echo "To activate the environment, run:"
echo "    source ${VENV_DIR}/bin/activate"
echo ""
echo "To run the web UI:"
echo "    python -m streamlit run app.py"
echo ""
echo "To run the CLI:"
echo "    python main.py"
echo ""
echo "To run tests:"
echo "    pytest tests/ -q"
