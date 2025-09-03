"""Conigurable Property class for microservices."""
from dataclasses import dataclass, asdict
from enum import EnumMeta
from typing import Optional, Union, Type, Any

from .utils import json_compatible

@dataclass
class ConfigurableProperty:
    """Data structure for a remotely configurable property.
    
    Attributes:
        type (str): The data type from a list of supported types.
        min (int|float): Optional minimum allowed numeric value.
        max (int|float): Optional maximum allowed numeric value.
        enum (list[str]): Optional list of 
    """
    type: str
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    enum: Optional[Union[list[str], EnumMeta]] = None
    desc: Optional[str] = None
    
    def __post_init__(self):
        if self.type not in self.supported_types().keys():
            raise ValueError('Invalid type string')
        if self.min is not None:
            if not isinstance(self.min, (int, float)):
                raise ValueError('Invalid min value')
        if self.max is not None:
            if not isinstance(self.max, (int, float)):
                raise ValueError('Invalid max value')
        if self.enum is not None:
            if isinstance(self.enum, list):
                if not all(isinstance(e, str) and e for e in self.enum):
                    raise ValueError('Enum list must be non-empty strings')
            elif isinstance(self.enum, EnumMeta):
                # Enum was passed, convert to list of strings
                self.enum = list(self.enum.__members__.keys())
            else:
                raise ValueError('Invalid enum values')
        
    @classmethod
    def supported_types(cls) -> dict[str, Type[Any]]:
        return {
            'int': int,
            'bool': bool,
            'float': float,
            'str': str,
            'enum': str,
            'list': list,
            'dict': dict,
        }
    
    def json_compatible(self) -> dict[str, Any]:
        """Converts to a JSON-compatible representation.
        
        Will be deprecated, use json_compatible(configurable_property)
        """
        return {
            k: json_compatible(v) for k, v in asdict(self).items()
            if v is not None
        }
