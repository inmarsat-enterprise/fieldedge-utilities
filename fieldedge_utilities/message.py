"""Message management utilities for FieldEdge applications."""

import base64
from dataclasses import dataclass, field
from enum import IntEnum

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
    id: 'int|str'
    mo: bool   # mo = Mobile-Originated (else Mobile-Terminated)
    data_b64: str = ''   # Base64-encoded string
    
    @property
    def size(self) -> int:
        if not isinstance(self.data_b64, str) or len(self.data_b64) == 0:
            return 0
        return len(base64.b64decode(self.data_b64))


@dataclass
class MessageStore:
    """A temporary storage buffer in memory for messages."""
    tx_queue: 'list[MessageMeta]' = field(default_factory=list)
    rx_queue: 'list[MessageMeta]' = field(default_factory=list)
    byte_count: int = 0
    last_mo_id: int = 0
    last_mt_id: int = 0

    def add(self, message: 'MessageMeta') -> None:
        """Adds a message to the buffer."""
        if not isinstance(message, MessageMeta):
            raise ValueError('Invalid message metadata')
        queue = self.tx_queue if message.mo else self.rx_queue
        if any(queued.id == message.id for queued in queue):
            raise ValueError(f'Duplicate id {message.id} found')
        if queue == self.tx_queue:
            self.last_mo_id = message.id
        else:
            self.last_mt_id = message.id
        queue.append(message)
        self.byte_count += message.size

    def get(self, id: int, mo: bool = True, retain: bool = False) -> MessageMeta:
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
