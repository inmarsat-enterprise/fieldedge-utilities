import os
import shutil

from fieldedge_utilities import user_config

TEST_DIR = os.path.join(os.getcwd(), 'tests/user_config')
TEST_FILE = f'{TEST_DIR}/test.env'


def test_obscure_unobscure():
    password = 'testPass'
    obscured = user_config.obscure(password)
    assert obscured != password
    unobscured = user_config.unobscure(obscured)
    assert unobscured == password


def test_read_config():
    config = user_config.read_user_config(TEST_FILE)
    assert isinstance(config, dict)
    assert config.get('USERNAME') == 'testUser'
    assert config.get('PASSWORD') == 'testPass'
    assert config.get('NUMBER') == 42
    assert config.get('FLOAT_NUMBER') == -1.234
    assert config.get('OBJECT') == {'name': 'testName', 'value': 1}
    assert config.get('ARRAY') == ['one', 'two']


def test_read_config_tag():
    config = user_config.read_user_config(TEST_FILE, prefix='TAGGED')
    assert len(config.keys()) == 1
    assert config.get('KEY') == 'taggedValue'


def test_write_config():
    try:
        shutil.copy(TEST_FILE, f'{TEST_FILE}.original')
        original_lines = []
        with open(TEST_FILE) as file:
            original_lines = [line.strip() for line in file.readlines()]
        write_config = {
            'USERNAME': 'testUser',
            'PASSWORD': 'newPass',
        }
        user_config.write_user_config(write_config, TEST_FILE)
        with open(TEST_FILE) as file:
            written_lines = [line.strip() for line in file.readlines()]
            assert written_lines != original_lines
            assert len(written_lines) == len(original_lines)
            for i, line in enumerate(written_lines):
                if line.startswith('PASSWORD'):
                    assert line != original_lines[i]
                else:
                    assert line == original_lines[i]
        user_config.write_user_config({'NEW_KEY': 'newValue'}, TEST_FILE)
        with open(TEST_FILE) as file:
            written_lines = [line.strip() for line in file.readlines()]
            assert len(written_lines) == len(original_lines) + 1
        user_config.write_user_config({'NEW_KEY': 'newTaggedValue'},
                                      TEST_FILE,
                                      prefix='TAGGED')
        with open(TEST_FILE) as file:
            written_lines = [line.strip() for line in file.readlines()]
            assert len(written_lines) == len(original_lines) + 2
            assert written_lines[-1].startswith('TAGGED_')
        
    finally:
        shutil.move(f'{TEST_FILE}.original', TEST_FILE)
