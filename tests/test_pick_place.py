"""A demonstration must physically lift and release a cube inside the bin."""

from abc_inspect.pick_place import run_demo


def test_scripted_demo_physically_picks_and_places(tmp_path):
    result = run_demo(tmp_path, store_frames=False)
    assert result["lift_height"] > 0.12
    assert result["objects_in_box"] == 1
    assert result["task_metrics"]["pick_place"] == 1.0
    assert result["task_metrics"]["abc_success"] == 0.0
    assert result["final_gripper"] > 0.9
    assert result["physics_steps"] > 100
