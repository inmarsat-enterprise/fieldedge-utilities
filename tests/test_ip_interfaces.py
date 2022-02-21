from fieldedge_utilities import ip_interfaces


def test_is_valid_ip():
    test_good_ip = '192.168.1.1'
    assert ip_interfaces.is_valid_ip(test_good_ip)
    test_bad_ip = '12345'
    assert not ip_interfaces.is_valid_ip(test_bad_ip)


def test_get_interfaces():
    ifaces = ip_interfaces.get_interfaces(['en'])
    assert len(ifaces) > 0
    for iface in ifaces:
        assert ip_interfaces.is_valid_ip(ifaces[iface])


def test_is_ip_in_subnet():
    test_good_ip = '192.168.1.1'
    test_good_subnet = '192.168.0.0/16'
    assert ip_interfaces.is_address_in_subnet(test_good_ip, test_good_subnet)
    test_bad_subnet = '172.1.1.0/24'
    assert not ip_interfaces.is_address_in_subnet(test_good_ip, test_bad_subnet)
