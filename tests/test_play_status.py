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


def test_budget_warns_before_exhaustion_and_stays_distinct_from_task_score():
    html = (Path(__file__).parents[1] / "src/abc_inspect/play.html").read_text()
    function = re.search(r"function budgetState\(s\)\{.*?\n\}", html, re.DOTALL)
    assert function, "Budget needs a visible countdown and a near-limit warning"
    subprocess.run(
        [
            "node",
            "-e",
            function.group()
            + """
const assert = require('node:assert/strict');
assert.deepEqual(budgetState(null), {remaining:1000,tone:'idle',label:'1,000-step budget'});
assert.deepEqual(budgetState({physics_steps:900,status:'active'}),
                 {remaining:100,tone:'low',label:'100 steps left'});
assert.deepEqual(budgetState({physics_steps:1000,status:'finished'}),
                 {remaining:0,tone:'ended',label:'0 steps left'});
assert.deepEqual(budgetState({physics_steps:5,status:'finished'}),
                 {remaining:995,tone:'finished',label:'995 steps left'});
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_robot_hotkeys_respect_browser_shortcuts_and_focused_controls():
    html = (Path(__file__).parents[1] / "src/abc_inspect/play.html").read_text()
    function = re.search(r"function robotHotkey\(e\)\{.*?\n\}", html, re.DOTALL)
    assert function, "Robot commands must not intercept browser/control keys"
    subprocess.run(
        [
            "node",
            "-e",
            function.group()
            + """
const assert = require('node:assert/strict');
const plain = {target:{closest:()=>null},code:'KeyW'};
assert.equal(robotHotkey(plain),true);
for(const modifier of ['metaKey','ctrlKey','altKey'])
  assert.equal(robotHotkey({...plain,[modifier]:true}),false);
assert.equal(robotHotkey({...plain,target:{closest:()=>({})}}),false);
assert.equal(robotHotkey({...plain,code:'Space',target:{closest:s=>s==='button,summary,a'?{}:null}}),false);
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
