<!-- Auto-generated: tailored Copilot instructions for the BattleBugs repo -->
# Copilot / AI agent instructions — BattleBugs

This repository currently contains only a minimal README and a (blank) Docker Compose file. Use these instructions to decide how to proceed and what to ask the human maintainers before making changes.

1) Quick repo snapshot (discoverable facts)
- `README.md` — file exists but contains only a title (`# BattleBugs`). No language, entry point, or build scripts are present.
- `docker-compose.yml` — file exists but is effectively empty/whitespace.

2) Primary rule: do not assume a language, framework, or build system
- There is no discoverable source code or config (package.json, pyproject.toml, go.mod, etc.). Before adding or changing code, run a repository-wide search for common build files and confirm with the human owner.

3) Productive first steps for an AI agent
- Report back these findings and ask the user for the project's language, intended services, and expected local workflow.
- If asked to implement a feature, propose a concrete file layout and wait for confirmation. Example proposal: a `src/` folder for application code and `docker-compose.yml` entries for services.
- If asked to add CI or tooling, create a draft PR with minimal changes and include clear README updates explaining required developer commands.

4) If you find additional files later, use them to update these instructions
- Look for: `package.json`, `pyproject.toml`, `requirements.txt`, `go.mod`, `pom.xml`, `Makefile`, `Dockerfile`, `.github/workflows/`.
- If a real `docker-compose.yml` is present, prefer it for local service wiring; reference exact service names/ports when making changes.

5) Merge behavior (when this file already exists)
- Preserve any existing guidance. If you add or modify sections, keep original author intent and mention what you changed at the top with a short changelog entry.

6) Examples of actionable prompts to present to the human maintainer
- "Which language/framework is this repo using (Node/Python/Go/Rust)?"
- "Where should source code live (root, `src/`, `services/`)?"
- "What local command(s) do you run to build/test/debug this project?"

7) Safety and scope
- Avoid large speculative rewrites. When missing information prevents safe changes, create a tiny, reversible PR (README + instruction) rather than changing application code.

If any part of this repo is inaccurate or incomplete, tell me what I should inspect next and I will re-run the discovery steps and update this file.
