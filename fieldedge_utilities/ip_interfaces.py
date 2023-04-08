"""Tools for querying IP interface properties of the system.

An environment variable `INTERFACE_VALID_PREFIXES` can be configured to
override the default set of `eth` and `wlan` prefixes.

*DEPRECATED*.
Moved to ip.interfaces

"""
from fieldedge_utilities.ip.interfaces import (VALID_PREFIXES, get_interfaces,
                                               is_address_in_subnet,
                                               is_valid_ip)

__all__ = ['VALID_PREFIXES', 'get_interfaces',
           'is_address_in_subnet', 'is_valid_ip']
