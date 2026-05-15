# Deploying the Client Demo

Cloud-deployable build that drives the full UI without any local
RenderDoc, OBS, or game install. Triggered by the env var
`DEMOAISHI=1`. The active scenario is selected via
`DEMOAISHI_SCENARIO=<name>` (default `batman_ak`).

## What's in the image

- Flask + numpy + gunicorn (`requirements-demo.txt`)
- The full `web/templates/index.html` UI, unchanged
- `demo/scenarios/batman_ak/` — manifest + script.json + frames/

What's NOT in the image (excluded by `.dockerignore`):

- `renderdoc/` (the fork) and `3rdparty/`
- `output/` and `*.rdc` / `*.exr`
- `recorders/obs_recorder.py`, `desktop_app.py`
- `tests/`, `agents/`, `.claude/`, `docs/refCode/`

## Build + run locally

```bash
docker build -t captureaishi-demo .
docker run --rm -p 8080:8080 captureaishi-demo
# open http://localhost:8080
```

You should see:

- A red/orange "演示模式 / Demo" pill in the top-right of the toolbar
- Click **Start** -> log lines stream in, progress bar advances 0 -> 30
- Click **注入菜单** -> all buttons return canned ok responses
- Output gallery is empty until you drop frames in (see below)

## Adding real Batman frames

The DemoSession points `_capture_state.output_dir` at
`demo/scenarios/batman_ak/frames/` whenever that directory contains
files. To populate it from a real run on a dev machine:

```bash
# After a successful capture on Windows:
cp ./output/<session>/*.png demo/scenarios/batman_ak/frames/
git add demo/scenarios/batman_ak/frames/
git commit -m "demo(batman): bake real frame triplet"
docker build -t captureaishi-demo .   # rebuild to ship them
```

Each capture should be a triplet:

- `0001_main.png` (RGB)
- `0001_main_d.png` (Depth, log-curve compressed)
- `0001_main_n.png` (Normal, GBufferA WorldNormal)

## Deploy targets

### Fly.io (simplest free path)

```bash
fly launch --no-deploy            # accepts the Dockerfile, picks a region
fly deploy
fly open
```

`fly.toml` should expose port `8080` and set `DEMOAISHI=1`. Defaults
work because the Dockerfile already declares both.

### Render

1. New -> Web Service -> Connect repo
2. Environment: Docker
3. Add env var `DEMOAISHI=1` (already in the Dockerfile, kept here for
   override clarity)
4. Deploy

### Railway

```bash
railway init
railway up
```

Railway auto-detects the Dockerfile. Set `DEMOAISHI=1` in the project
settings if you want to override the image-baked default.

### Plain VPS (Docker)

```bash
docker run -d --restart=unless-stopped \
  -p 80:8080 -e DEMOAISHI=1 \
  --name aishi-demo captureaishi-demo
```

## Adding a new scenario

```
demo/scenarios/<my_scenario>/
  manifest.json     {scenario, display_name, total_poses, pose_dwell_seconds, frames_dir}
  script.json       {preamble: [[t,msg],...], pose_template, postamble: [[t,msg],...]}
  frames/           PNG triplets
```

Switch the container to it:

```bash
docker run -e DEMOAISHI_SCENARIO=my_scenario captureaishi-demo
```

The default `batman_ak` falls back to `_DEFAULT_PREAMBLE` /
`_DEFAULT_POSTAMBLE` baked into `web/demo.py` if the scenario files
are malformed, so a syntax error in your scenario won't crash the app.

## How the short-circuit works

In `DEMOAISHI=1` every route that would otherwise hit a TCP socket /
subprocess / OBS WebSocket short-circuits to a canned response. The
guards live at the top of each handler in `web/routes/*.py`:

```python
if is_demo_mode():
    return jsonify(canned_xxx())
```

`web/demo.py` owns all the canned strings, so the audit surface for
"could this accidentally talk to real hardware" is one file. New
routes that touch IO **must** add an `is_demo_mode()` guard.

## Smoke test the deployed URL

```bash
curl https://your-deploy.example.com/api/defaults | jq .demo_mode
# true

curl -X POST https://your-deploy.example.com/api/start | jq
# {"demo": true, "ok": true}

sleep 1
curl https://your-deploy.example.com/api/status | jq '.logs | length'
# >= 4

curl -X POST https://your-deploy.example.com/api/stop | jq
# {"demo": true, "ok": true}
```
