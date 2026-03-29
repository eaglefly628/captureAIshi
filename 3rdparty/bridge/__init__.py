"""captureAIshi bridge — self-hosted UE5 console injection.

This module provides DLL injection as an alternative to UUU.
It is OPTIONAL and disabled by default (--auto-inject flag).

The bridge consists of:
  - injector.py: Python-based DLL injector (Windows only)
  - src/bridge.cpp: C++ TCP console server DLL for UE5 games

When enabled, the pipeline will:
  1. Launch the game (via renderdoccmd as usual)
  2. Inject captureAIshi_bridge.dll into the game process
  3. The DLL starts a TCP console server on port 9998
  4. The UE5 driver connects to it (same as with UUU)

This replaces the manual UUU injection step.
"""
