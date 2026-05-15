# Batman: Arkham Knight - Client Demo Scenario

Used by `web/demo.py` when the Flask app starts with `DEMOAISHI=1`.

## Files

- `manifest.json` -- scenario metadata (poses, dwell, profile id)
- `script.json` -- preamble + pose template + postamble timeline
- `frames/` -- real PNG triplets (RGB + `_d.png` Depth + `_n.png` Normal)

## Drop real frames

Without files in `frames/`, the demo still animates the log + progress
bar correctly, but the Output gallery stays empty. To populate it:

```bash
# After a real capture run on a dev machine:
cp -r ./output/<session>/*.png demo/scenarios/batman_ak/frames/
```

Or for the client-facing deploy, build the bundle into the container
image so the customer sees real captures during the showcase.

The DemoSession sets `_capture_state.output_dir` to point at this
`frames/` directory at session start, so the existing `/api/captures`
and `/api/sessions` endpoints serve the files unchanged.
