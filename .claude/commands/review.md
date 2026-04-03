# /project:review -- Code Review

Review the specified commit or file for issues.

## Usage
/project:review <commit-sha or file-path>

## Steps

1. Read the diff or file
2. Check against project rules:
   - `.claude/rules/code-style.md` (Python conventions)
   - `.claude/rules/cpp-rules.md` (C++ ASCII rules)
   - `.claude/rules/no-sleep.md` (no sleep for readiness)
   - `.claude/rules/versioning.md` (CL entry required)
3. Check domain boundaries: does the change touch files outside the author's domain?
4. Rate each issue P0/P1/P2:
   - P0: Security, data loss, crash
   - P1: Correctness, contract violation
   - P2: Style, documentation, minor
5. Write findings to the relevant agent's SHARED.md TODO section
6. Update `agents/STATUS.md`
