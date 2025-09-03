"""Unit tests for interservice.
"""
import logging
import time

import pytest

from fieldedge_utilities.microservice.interservice import IscTask, IscTaskQueue

logger = logging.getLogger(__name__)


@pytest.fixture
def isc_task() -> IscTask:
    return IscTask(uid='a-unique-id',
                   task_type='test',
                   task_meta={
                       'test': 'test',
                       'timeout_callback': isc_task_timeout,
                   },
                   callback=isc_task_chained)


def isc_task_timeout(*args, **kwargs):
    for arg in args:
        logger.info(f'Task timeout received {arg}')
    for k, v in kwargs.items():
        logger.info(f'Task timeout received {k}={v}')


def isc_task_chained(*args, **kwargs):
    for arg in args:
        logger.info(f'Task chain received {arg}')
    for k, v in kwargs.items():
        logger.info(f'Task chain received {k}={v}')


def test_isc_task_creation():
    queued_task = IscTask(task_type='test')
    assert isinstance(queued_task.uid, str)
    assert queued_task.task_type == 'test'
    assert queued_task.lifetime == 10


def test_isc_task_queue_basic(isc_task: IscTask):
    task_queue = IscTaskQueue()
    task_queue.append(isc_task)
    with pytest.raises(ValueError):
        task_queue.append(isc_task)
    assert task_queue.is_queued(isc_task.uid)
    assert task_queue.is_queued(task_type=isc_task.task_type)
    assert task_queue.is_queued(task_meta=('test', 'test'))     # type: ignore legacy compatibility
    assert task_queue.is_queued(task_meta={'test': 'test'})
    got = task_queue.get(isc_task.uid)
    assert isinstance(got, IscTask) and got == isc_task and got.task_meta
    assert not task_queue.is_queued(isc_task.uid)
    assert callable(got.task_meta.pop('timeout_callback'))
    assert callable(got.callback)
    got.callback(got.task_meta)


def test_isc_task_queue_expiry(isc_task: IscTask):
    isc_task.lifetime = 1
    task_queue = IscTaskQueue()
    task_queue.append(isc_task)
    while task_queue.is_queued(isc_task.uid):
        time.sleep(1)
        task_queue.remove_expired()
    assert not task_queue.is_queued(isc_task.uid)
