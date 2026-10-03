"""Exercise the browser's budget status without a browser or simulator."""

import re
import subprocess
from pathlib import Path


def test_browser_distinguishes_budget_exhaustion_from_manual_finish():
    html = (Path(__file__).parents[1] / "src/abc_inspect/play.html").read_text()
    function = re.search(r"function playStatus\(s\)\{.*?\n\}", html, re.DOTALL)
    assert function, "The browser must explain why a trial stopped"
    subprocess.run(
        [
            "node",
            "--input-type=commonjs",
            "-e",
            function.group()
            + """
const assert = require('node:assert/strict');
assert.equal(playStatus({status:'active',sim_time:17,physics_steps:500}),
             'Ready · 17.0s · 500 steps left');
assert.equal(playStatus({status:'finished',sim_time:34,physics_steps:1000}),
             'Step limit reached · Reset to play again');
assert.equal(playStatus({status:'finished',sim_time:2,physics_steps:60}),
             'Finished · 2.0s · Reset to play again');
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
