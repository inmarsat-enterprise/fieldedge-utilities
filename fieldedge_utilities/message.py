"""Message management utilities for FieldEdge applications."""

import base64
from dataclasses import dataclass, field, InitVar
from enum import IntEnum
from typing import Optional

__all__ = ['MessageState', 'MessageMeta', 'MessageStore']


class MessageState(IntEnum):
    """Message state enumerated type."""
    UNAVAILABLE = 0
    RX_PENDING = 1
    RX_COMPLETE = 2
    RX_RETRIEVED = 3 
    TX_QUEUED = 4
    TX_SENDING = 5
    TX_COMPLETE = 6
    TX_FAILED = 7
    TX_CANCELLED = 8


@dataclass
class MessageMeta:
    """Message metadata."""
    id: int|str
    mo: bool   # mo = Mobile-Originated (else Mobile-Terminated)
    data: InitVar[Optional[str|bytes]] = None
    _data_b64: Optional[str] = None   # Base64-encoded string of payload data
    _size: Optional[int] = field(init=False, repr=False, default=None)
    
    def __post_init__(self, data: Optional[str|bytes]):
        if data is not None:
            self.data_b64 = data
    
    @property
    def data_b64(self) -> Optional[str]:
        return self._data_b64
    
    @data_b64.setter
    def data_b64(self, value: Optional[str|bytes]) -> None:
        if value is None:
            self._data_b64 = None
            return
        elif isinstance(value, (bytes, bytearray)):
            value = base64.b64encode(value).decode()
        if not isinstance(value, str):
            raise ValueError('data_b64 must be str or bytes-like')
        try:
            decoded = base64.b64decode(value, validate=True)  # type: ignore
            self._data_b64 = value
            self._size = len(decoded)
        except Exception as exc:
            raise ValueError(f'Invalid base64 string ({exc})') from exc

    @property
    def size(self) -> Optional[int]:
        return self._size
    
    @size.setter
    def size(self, value: int):
        # allows size to be modified e.g. IP headers
        if not isinstance(value, int):
            raise ValueError('Size must be an integer')
        if (isinstance(self.data_b64, str) and 
            value < len(base64.b64decode(self.data_b64))):
            raise ValueError('Size must equal or exceed payload length')
        self._size = value


@dataclass
class MessageStore:
    """A temporary storage buffer in memory for messages."""
    tx_queue: list[MessageMeta] = field(default_factory=list)
    rx_queue: list[MessageMeta] = field(default_factory=list)
    byte_count: int = 0
    last_mo_id: Optional[int|str] = None
    last_mt_id: Optional[int|str] = None

    def add(self, message: MessageMeta) -> None:
        """Adds a message to the buffer."""
        if not isinstance(message, MessageMeta):
            raise ValueError('Invalid message metadata')
        queue = self.tx_queue if message.mo else self.rx_queue
        if any(queued.id == message.id for queued in queue):
            raise ValueError(f'Duplicate id {message.id} found')
        if queue is self.tx_queue:
            self.last_mo_id = message.id
        else:
            self.last_mt_id = message.id
        queue.append(message)
        self.byte_count += message.size or 0

    def get(self,
            id: int|str,
            mo: bool = True,
            retain: bool = False,
            ) -> MessageMeta:
        """Retrieves a message from the buffer, optionally retaining it.
        
        id -1 indicates the first enqueued message.
        """
        queue = self.tx_queue if mo else self.rx_queue
        if id == -1 and len(queue) > 0:
            if not retain:
                return queue.pop(0)
            return queue[0]
        for i, message in enumerate(queue):
            if message.id == id:
                if not retain:
                    return queue.pop(i)
                return message
        raise ValueError(f'Message {id} not found in queue')
