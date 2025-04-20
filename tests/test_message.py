# test_message_utils.py

import pytest
import base64
from fieldedge_utilities import MessageState, MessageMeta, MessageStore


def test_message_state_enum():
    assert MessageState.UNAVAILABLE == 0
    assert MessageState.RX_PENDING == 1
    assert MessageState.TX_COMPLETE == 6


def test_message_meta_default_size_zero():
    msg = MessageMeta(id=1, mo=True)
    assert msg.size == 0


def test_message_meta_calculates_size_from_b64():
    raw_data = b'hello'
    b64_data = base64.b64encode(raw_data).decode()
    msg = MessageMeta(id=2, mo=False, data_b64=b64_data)
    assert msg.size == len(raw_data)


def test_message_meta_size_setter_allows_valid_override():
    raw_data = b'hello'
    b64_data = base64.b64encode(raw_data).decode()
    msg = MessageMeta(id=3, mo=True, data_b64=b64_data)
    new_size = len(raw_data) + 20
    msg.size = new_size
    assert msg.size == new_size


def test_message_meta_size_setter_rejects_non_int():
    msg = MessageMeta(id=4, mo=False)
    with pytest.raises(ValueError, match='Size must be an integer'):
        msg.size = "ten"


def test_message_meta_size_setter_rejects_smaller_than_data():
    raw_data = b'abcdef'
    b64_data = base64.b64encode(raw_data).decode()
    msg = MessageMeta(id=5, mo=False, data_b64=b64_data)
    with pytest.raises(ValueError, match='Size less than payload length'):
        msg.size = len(raw_data) - 1


def test_message_store_add_and_get_tx_message():
    store = MessageStore()
    msg = MessageMeta(id=100, mo=True)
    store.add(msg)
    assert store.last_mo_id == 100
    assert store.byte_count == msg.size
    retrieved = store.get(100, mo=True)
    assert retrieved == msg
    assert store.byte_count == 0


def test_message_store_add_and_get_rx_message():
    store = MessageStore()
    msg = MessageMeta(id=200, mo=False)
    store.add(msg)
    assert store.last_mt_id == 200
    assert store.byte_count == msg.size
    retrieved = store.get(200, mo=False)
    assert retrieved == msg
    assert store.byte_count == 0


def test_message_store_add_duplicate_raises():
    store = MessageStore()
    msg = MessageMeta(id=300, mo=True)
    store.add(msg)
    with pytest.raises(ValueError, match='Duplicate id 300 found'):
        store.add(msg)


def test_message_store_get_first_message_by_id_minus_one():
    store = MessageStore()
    msg1 = MessageMeta(id=1, mo=True)
    msg2 = MessageMeta(id=2, mo=True)
    store.add(msg1)
    store.add(msg2)
    first = store.get(-1, mo=True)
    assert first == msg1


def test_message_store_get_with_retain_flag_true():
    store = MessageStore()
    msg = MessageMeta(id=123, mo=False)
    store.add(msg)
    retained = store.get(123, mo=False, retain=True)
    assert retained == msg
    assert store.rx_queue[0] == msg


def test_message_store_get_nonexistent_raises():
    store = MessageStore()
    with pytest.raises(ValueError, match='Message 999 not found in queue'):
        store.get(999, mo=True)
