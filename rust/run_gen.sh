#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
set -a && source "$SCRIPT_DIR/../.env" && set +a
cargo run -- generate \
  --company "HugeSmoothTech Corp" \
  --industry "Software Technology" \
  --description "A software giant building SaaS products" \
  --events "Project Kickoff" "Q1 Review" "Performance Review" "Sales Layoff" "SDE Reorganization" "Product Refocus" "AI and LLM replacements" "Use coding agents to replace SDE" "SDE layoff" \
  --size large \
  --num-users 40 \
  --days 10 \
  --provider azure
