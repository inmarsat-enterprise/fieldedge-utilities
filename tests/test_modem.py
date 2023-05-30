from fieldedge_utilities import modem


def test_backoff():
    cnx = modem.ConnectionManager()
    assert cnx.backoff_interval == 30
    cnx.init_attempts += 1
    cnx.backoff()
    assert cnx.backoff_interval == 30
    cnx.init_attempts += 1
    cnx.backoff()
    assert cnx.backoff_interval == 30
    cnx.init_attempts += 1
    cnx.backoff()
    assert cnx.backoff_interval == 30
    cnx.init_attempts += 1
    cnx.backoff()
    assert cnx.backoff_interval == 60
    cnx.init_attempts += 3
    cnx.backoff()
    assert cnx.backoff_interval == 120
    cnx = modem.ConnectionManager(backoff_starts_after=6)
    cnx.init_attempts += 6
    cnx.backoff()
    assert cnx.backoff_interval == 30
    cnx.init_attempts += 1
    cnx.backoff()
    assert cnx.backoff_interval == 60
