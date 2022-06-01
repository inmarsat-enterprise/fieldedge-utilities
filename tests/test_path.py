from fieldedge_utilities import path

REAL_PATH = '/Users/gbp/projects/fieldedge-utilities'

def test_get_caller():
    def callerfunc():
        return path.get_caller_name(mod=True, cls=False, mth=True)
    res = callerfunc()
    assert res == 'tests.test_path.test_get_caller'

def test_clean_path():
    res1 = path.clean_path('./')
    assert res1 == REAL_PATH
    res2 = path.clean_path('$HOME/projects/fieldedge-utilities')
    assert res2 == REAL_PATH
    res3 = path.clean_path('~/projects/fieldedge-utilities')
    assert res3 == REAL_PATH
