"""Run browser-state assertions directly in Node, without a simulator."""

import re
import subprocess
from pathlib import Path


def check_browser(functions, assertions):
    html = (Path(__file__).parents[1] / "src/abc_inspect/play.html").read_text()
    sources = []
    for name in functions:
        function = re.search(rf"function {name}\([^)]*\)\{{.*?\n\}}", html, re.DOTALL)
        assert function, f"Missing browser function: {name}"
        sources.append(function.group())
    subprocess.run(
        ["node", "-e", "\n".join(sources) + assertions],
        check=True,
        capture_output=True,
        text=True,
    )


def test_browser_distinguishes_budget_exhaustion_from_manual_finish():
    check_browser(
        ["budgetState", "playStatus"],
        """
const assert = require('node:assert/strict');
assert.equal(playStatus({status:'active',max_steps:5000,sim_time:34,physics_steps:1000}),
             'Ready · 34.0s · 4000 steps left');
assert.equal(playStatus({status:'finished',max_steps:5000,sim_time:68,physics_steps:2000}),
             'Finished · 68.0s · Reset to play again');
assert.equal(playStatus({status:'active',sim_time:17,physics_steps:500}),
             'Ready · 17.0s · 500 steps left');
assert.equal(playStatus({status:'finished',sim_time:34,physics_steps:1000}),
             'Step limit reached · Reset to play again');
assert.equal(playStatus({status:'finished',sim_time:2,physics_steps:60}),
             'Finished · 2.0s · Reset to play again');
""",
    )


def test_budget_warns_before_exhaustion_and_stays_distinct_from_task_score():
    check_browser(
        ["budgetState"],
        """
const assert = require('node:assert/strict');
assert.deepEqual(budgetState({physics_steps:1000,max_steps:5000,status:'active'}),
                 {remaining:4000,tone:'ready',label:'4000 steps left'});
assert.deepEqual(budgetState({physics_steps:4500,max_steps:5000,status:'active'}),
                 {remaining:500,tone:'low',label:'500 steps left'});
assert.deepEqual(budgetState(null), {remaining:1000,tone:'idle',label:'1,000-step budget'});
assert.deepEqual(budgetState({physics_steps:900,status:'active'}),
                 {remaining:100,tone:'low',label:'100 steps left'});
assert.deepEqual(budgetState({physics_steps:1000,status:'finished'}),
                 {remaining:0,tone:'ended',label:'0 steps left'});
assert.deepEqual(budgetState({physics_steps:5,status:'finished'}),
                 {remaining:995,tone:'finished',label:'995 steps left'});
""",
    )


def test_robot_hotkeys_respect_browser_shortcuts_and_focused_controls():
    check_browser(
        ["robotHotkey"],
        """
const assert = require('node:assert/strict');
const plain = {target:{closest:()=>null},code:'KeyW'};
assert.equal(robotHotkey(plain),true);
for(const modifier of ['metaKey','ctrlKey','altKey'])
  assert.equal(robotHotkey({...plain,[modifier]:true}),false);
assert.equal(robotHotkey({...plain,target:{closest:()=>({})}}),false);
assert.equal(robotHotkey({...plain,code:'Space',target:{closest:s=>s==='button,summary,a'?{}:null}}),false);
""",
    )
