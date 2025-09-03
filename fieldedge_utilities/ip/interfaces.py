"""Tools for querying IP interface properties of the system.

An environment variable `INTERFACE_VALID_PREFIXES` can be configured to
override the default set of `eth` and `wlan` prefixes.
"""
import ipaddress
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import ifaddr

_log = logging.getLogger(__name__)

try:
    VALID_PREFIXES = json.loads(os.getenv('INTERFACE_VALID_PREFIXES',
                                          '["eth","wlan"]'))
    if (not isinstance(VALID_PREFIXES, list) or
        not all(isinstance(x, str) for x in VALID_PREFIXES)):
        raise ValueError('INTERFACE_VALID_PREFIXES must decode to a list')
except Exception as exc:
    VALID_PREFIXES = ['eth', 'wlan']
    _log.error('Invalid INTERFACE_VALID_PREFIXES - falling back to [%s]: %s',
               VALID_PREFIXES, exc)

__all__ = ['get_interfaces', 'is_address_in_subnet',
           'is_valid_ip', 'IfaddrAdapter']


@dataclass
class IfaddrIp:
    """Type hint helper for ifaddr.IP within ifaddr.Adapter"""
    ip: str
    is_IPv4: bool
    is_IPv6: bool
    network_prefix: int
    nice_name: str


@dataclass
class IfaddrAdapter:
    """Type hint helper for ifaddr.Adapter"""
    name: str
    nice_name: str
    index: int
    ips: 'list[IfaddrIp]'


def get_interfaces(valid_prefixes: 'list[str]' = VALID_PREFIXES,
                   target: Optional[str] = None,
                   include_subnet: bool = False,
                   ) -> dict[str, str]:
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
    try:
        subnet = ipaddress.ip_network(subnet, strict=False)     # type: ignore
        ip_address = ipaddress.ip_address(ip_address)           # type: ignore
        return ip_address in subnet
    except Exception:
        pass
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
        ip_obj = ipaddress.ip_address(ip_address)
        return ip_obj.version == 4 if ipv4_only else True
    except ValueError:
        return False
