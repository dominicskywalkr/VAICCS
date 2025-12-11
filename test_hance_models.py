from parse_hance_headless import parse_hance_models


def test_parse_hance_models_structure():
    m = parse_hance_models()
    # ensure the function returns a mapping with at least one key and iterable values
    assert isinstance(m, dict)
    # values should be lists
    found_hance = False
    for k, v in m.items():
        assert isinstance(v, list)
        for it in v:
            assert 'name' in it and 'url' in it
            if (it.get('name') or '').lower().endswith('.hance'):
                found_hance = True
    assert found_hance, 'Expected at least one .hance model in the parsed results'
