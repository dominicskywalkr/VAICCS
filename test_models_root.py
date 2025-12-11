import os
import gui


def test_models_root_is_adjacent_to_project():
    app = gui.App()
    # model_root should be inside the same directory as gui module (script directory)
    script_dir = os.path.abspath(os.path.dirname(os.path.abspath(gui.__file__)))
    assert hasattr(app, 'app_root') and app.app_root == script_dir
    assert hasattr(app, 'models_root') and os.path.commonpath([app.models_root, app.app_root]) == app.app_root
    assert os.path.basename(app.models_root) == 'models'
    # ensure folder exists or will be created (the app init should create it)
    assert os.path.isdir(app.models_root)
    app.destroy()
