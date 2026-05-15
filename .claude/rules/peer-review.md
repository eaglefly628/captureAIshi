# Peer Review (Mandatory)

Agents are in a **competitive** relationship. When you read another agent's SHARED.md or touch code they wrote:

1. **Actively look for bugs, security holes, protocol mismatches, and CLAUDE.md violations.** Don't skim -- audit.
2. **If you find a problem**, write it to their SHARED.md TODO section with your name:
   ```
   - [ ] **P1: [issue title]** (spotted by <your name>) -- description and suggested fix
   ```
3. **Never silently accept** another agent's assumptions about your domain.
4. **Challenge assumptions.** Verify claims against actual code and specs.
5. **Your reputation depends on shipping correct code and catching others' mistakes.** The lead programmer reviews everyone.

## Agent Names (canonical)

| Agent | Name | Domain |
|-------|------|--------|
| UI | xiaoyu | web_ui.py, web/templates/ |
| Rendering | xiaoxuan | renderdoccmd, grabbers/ |
| Reversing | xiaoni | drivers/, 3rdparty/bridge/ |
| PCG | xiaohuan | apps/adore_robot/.../Content/PCG/, configs/scenes/ |
| UE5 Fullstack | xiaoxu | apps/adore_robot/.../Source/, Plugins/, Config/, MRQ |

Use these exact names in all CL entries, TODO attributions, and peer review comments.
