import os

from fieldedge_utilities import user_config


def test_obscure_unobscure():
    password = 'testPass'
    obscured = user_config.obscure(password)
    assert obscured != password
    unobscured = user_config.unobscure(obscured)
    assert unobscured == password


def test_write_read_config():
    TEST_DIR = os.path.join(os.getcwd(), 'tests/user_config')
    TEST_FILE = f'{TEST_DIR}/test.env'
    write_config = {
        'USERNAME': 'testUser',
        'PASSWORD': 'testPass',
    }
    user_config.write_user_config(write_config, TEST_FILE)
    read_config = user_config.read_user_config(TEST_FILE)
    assert len(read_config) > 0
    for k, v in read_config.items():
        assert k in write_config
        assert v == write_config[k]
