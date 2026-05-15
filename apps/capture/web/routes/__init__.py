"""Flask blueprints for the web UI, grouped by domain."""

from web.routes.bridge import bp as bridge_bp
from web.routes.capture import bp as capture_bp
from web.routes.games import bp as games_bp
from web.routes.hacks import bp as hacks_bp
from web.routes.input_rec import bp as input_rec_bp
from web.routes.obs import bp as obs_bp
from web.routes.paths import bp as paths_bp
from web.routes.reshade import bp as reshade_bp
from web.routes.sessions import bp as sessions_bp
from web.routes.tools import bp as tools_bp
from web.routes.trajectory import bp as trajectory_bp

ALL_BLUEPRINTS = [
    capture_bp,
    hacks_bp,
    trajectory_bp,
    bridge_bp,
    sessions_bp,
    paths_bp,
    games_bp,
    tools_bp,
    obs_bp,
    input_rec_bp,
    reshade_bp,
]
