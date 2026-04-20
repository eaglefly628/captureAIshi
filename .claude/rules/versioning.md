# Versioning Rules

**Current: v0.2.0**

## Changelog

| Version | Date       | Summary |
|---------|------------|---------|
| v0.1.0  | 2026-03-28 | End-to-end pipeline: renderdoccmd launch, trigger capture, export RGB+Depth PNG |
| v0.2.0  | 2026-03-29 | trajectory.json output, normal buffer export, camera intrinsics (FOV/aspect), UI lightbox/progress/gallery/3D visualizer |
| v0.2.0  | 2026-03-30 | Bridge console server embedded in renderdoc.dll (GEngine auto-scan, camera path, timestop, HUD toggle, hotsampling). External memory driver for anti-cheat games. Removed UUU dependency. |

## Rules

- **Bump minor** (v0.X.0) for new features or API/schema changes that other agents need to know about.
- **Bump patch** (v0.X.Y) for bug fixes or internal refactors that don't affect inter-agent contracts.
- Lead programmer bumps the version in this file. Agents do NOT bump it themselves.
- **All SHARED.md updates MUST include a version tag** in the section header, e.g. `## [v0.2.0] Feature Name`. This is how agents reference specific changes.
- When an agent needs to tell another agent about a change, reference the version: "see rendering SHARED.md [v0.2.0]" -- not dates or commit hashes.
- Agents reading SHARED.md should check the version tag to know if they've already consumed that update.
- **Every push MUST include a changelog entry** in the agent's own SHARED.md. A push without a corresponding CL entry is an incomplete submission. Format: `### [v0.X.Y] <sha> -- <agent name>` with bullet summary. No exceptions.
- **Auto-archive rule**: SHARED.md keeps only the **latest 3 CL entries** and **open TODO items**. On session start, move CL entries older than 14 days (or beyond the top 3) to `agents/<role>/ARCHIVE.md`. Closed `[x]` TODO items also move to ARCHIVE. Goal: SHARED.md stays under 300 lines / 15 KB.
