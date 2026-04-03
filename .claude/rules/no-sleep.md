# No Time-Based Assumptions for Async Readiness

**Never use `sleep(N)` to wait for an external process or service to become ready.** Always use a deterministic signal:

- **Process readiness**: Poll for a concrete indicator (TCP port open, file appears on disk, process stdout contains ready message).
- **Game startup**: `_wait_for_game_ready()` polls the game's control port. Only after the port responds does the pipeline proceed to driver connection.
- **Capture completion**: Check for `.rdc` file existence on disk, don't assume a fixed delay is enough.
- **Timeouts are safety nets**, not expected flow. Log a warning when a timeout is hit — it means something unexpected happened.
