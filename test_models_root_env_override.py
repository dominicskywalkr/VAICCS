import os
import tempfile
import gui


def test_models_root_env_override(tmp_path):
    # set env var to override
    env_dir = tmp_path / "my_models"
    env_dir.mkdir(parents=True, exist_ok=True)
    os.environ['VAICCS_MODELS_ROOT'] = str(env_dir)
    app = gui.App()
    # models_root should be env_dir/models
    expected = os.path.join(os.path.abspath(str(env_dir)), 'models')
    assert app.models_root == expected
    # cleanup
    app.destroy()
    del os.environ['VAICCS_MODELS_ROOT']
