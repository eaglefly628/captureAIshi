# Reverse Engineering Agent -- xiaoni

Camera control for released games: bridge DLL injection, memory scan, CE tables. Files: `drivers/`, `3rdparty/bridge/`, `renderdoc/renderdoc/core/bridge/`.

Bridge TCP port 9998: `__` prefix = internal commands, else pass-through to GEngine->Exec(). Single-player only.

Coordinates: pipeline Y-up meters, convert to engine space at driver boundary.

Branch: `claudeMainBranch` only. TODO/specs in `agents/reversing/SHARED.md`.
