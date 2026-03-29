"""captureAIshi bridge — self-hosted UE5 console injection.

Provides DLL injection + TCP console server for controlling
UE5 shipped games.

Components:
  - injector.py: Python-based DLL injector (Windows only)
  - src/bridge.cpp: C++ TCP console server DLL

When --auto-inject is enabled, the pipeline will:
  1. Launch the game (via renderdoccmd as usual)
  2. Inject captureAIshi_bridge.dll into the game process
  3. The DLL starts a TCP console server on port 9998
  4. The UE5 driver connects and sends camera commands
"""
