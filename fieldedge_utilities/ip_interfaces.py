"""Tools for querying IP interface properties of the system.

An environment variable `INTERFACE_VALID_PREFIXES` can be configured to
override the default set of `eth` and `wlan` prefixes.
"""
import ifaddr
import ipaddress
import json
import os

VALID_PREFIXES = json.loads(os.getenv('INTERFACE_VALID_PREFIXES',
                                      '["eth","wlan"]'))


def get_interfaces(valid_prefixes: 'list[str]' = VALID_PREFIXES,
                   target: str = None,
                   include_subnet: bool = False,
                   ) -> dict:
    """Returns a dictionary of IP interfaces with IP addresses.
    
    Args:
        valid_prefixes: A list of prefixes to include in the search e.g. `eth`
        target: (optional) A specific interface to check for its IP address
        include_subnet: (optional) If true will append the subnet e.g. /16

    Returns:
        A dictionary e.g. { "eth0": "192.168.1.100" }
    
    """
    interfaces = {}
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        assert isinstance(adapter, ifaddr.Adapter)
        assert isinstance(adapter.name, str)
        if (valid_prefixes is not None and
            not any(adapter.name.startswith(x) for x in valid_prefixes)):
            continue
        for ip in adapter.ips:
            assert isinstance(ip, ifaddr.IP)
            if '.' in ip.ip:
                base_ip = ip.ip
                if include_subnet:
                    base_ip += f'/{ip.network_prefix}'
                interfaces[adapter.name] = base_ip
                break
        if target is not None and adapter.name == target:
            break
    return interfaces


def is_address_in_subnet(ip_address: str, subnet: str) -> bool:
    """Returns True if the IP address is part of the IP subnetwork.
    
    Args:
        ip_address: Address e.g. 192.168.1.101
        subnet: Subnet e.g. 192.168.0.0/16
    
    Returns:
        True if the IP address is within the subnet range.

    """
    subnet = ipaddress.ip_network(subnet, strict=False)
    ip_address = ipaddress.ip_address(ip_address)
    if ip_address in subnet:
        return True
    return False


def is_valid_ip(ip_address: str, ipv4_only: bool = True) -> bool:
    """Returns True if the value is a valid IP address.
    
    Args:
        ip_address: A candidate IP address
        ipv4_only: If True enforces that the address must be IPv4
    
    Returns:
        True if it is a valid IP address.

    """
    try:
        ip_address = ipaddress.ip_address(ip_address)
        assert (isinstance(ip_address, ipaddress.IPv4Address) or
                isinstance(ip_address, ipaddress.IPv6Address))
        if ipv4_only:
            return ip_address.version == 4
        return True
    except ValueError:
        return False
