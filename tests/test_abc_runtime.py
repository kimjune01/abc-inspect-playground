"""Real laptop integration gates, using the unmodified pinned ABC environment."""

import numpy as np
import pytest


@pytest.fixture
def env():
    import abc_sim

    instance = abc_sim.make_env(
        task="put_plastic_bottles_in_bin",
        camera_backend="mujoco",
        camera_height=168,
        camera_width=224,
        terminate_on_success=False,
    )
    yield instance
    instance.close()


def test_scene_renders_real_camera_pixels_and_seeded_reset(env):
    first, _ = env.reset(seed=7, randomize=True)
    initial = env.data.qpos.copy()
    assert first["state"].shape == (14,)
    assert first["images"]
    for pixels in first["images"].values():
        assert pixels.shape == (3, 168, 224)
        assert pixels.dtype == np.uint8
        assert pixels.std() > 5, "Renderer returned blank/constant frames"
    env.reset(seed=7, randomize=True)
    np.testing.assert_allclose(env.data.qpos, initial, atol=1e-8)


def test_joint_target_advances_dynamics_without_teleporting(env):
    obs, _ = env.reset(seed=7, randomize=True)
    start = obs["state"].copy()
    target = start.copy()
    target[0] += 0.1
    before_time = env.data.time
    obs, *_ = env.step(target)
    assert env.data.time > before_time
    assert abs(float(obs["state"][0] - start[0])) > 1e-6
    assert not np.array_equal(obs["state"], target), "Target was teleported into state"
    assert env.evaluate_task() is not None
