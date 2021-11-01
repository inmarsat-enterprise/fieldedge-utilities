"""Wrapping logger common format for FieldEdge project(s) with UTC timestamp.

Provides a common log format with a console and file handler.
The file is a wrapping log of configurable size using `RotatingFileHandler`.

Format is:

* ISO UTC timestamp including milliseconds
* Log level in square brackets
* Thread name in round brackets
* ModuleName.FunctionName:(LineNumber)
* Message

*Example:*

`2021-10-30T14:19:51.012Z,[INFO],(MainThread),main.<module>:6,This is a test`

"""
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from time import gmtime

from fieldedge_utilities.path import clean_filename, get_caller_name

FORMAT = ('%(asctime)s.%(msecs)03dZ,[%(levelname)s],(%(threadName)s),'
          '%(module)s.%(funcName)s:%(lineno)d,%(message)s')


# Logging to STDOUT or STDERR
class _LessThanFilter(logging.Filter):
    """Filters logs below a specified level for routing to a given handler."""
    def __init__(self,
                 exclusive_maximum: int = logging.WARNING,
                 name: str = None):
        if name is None:
            name = f'LessThan{logging.getLevelName(exclusive_maximum)}'
        super(_LessThanFilter, self).__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        #non-zero return means we log this message
        return 1 if record.levelno < self.max_level else 0


def get_logfile_name(logger: logging.Logger) -> str:
    """Returns the logger's RotatingFileHandler name."""
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler):
            return h.baseFilename
    return None


def _is_log_handler(logger: logging.Logger, handler: object) -> bool:
    """Returns true if the handler is found in the logger.
    
    Args:
        logger (logging.Logger)
        handler (logging handler)
    
    Returns:
        True if the handler is in the logger.

    """
    if not isinstance(logger, logging.Logger):
        return False
    found = False
    for h in logger.handlers:
        if h.name == handler.name:
            found = True
            break
    return found


def get_wrapping_logger(name: str = None,
                        filename: str = None,
                        file_size: int = 5,
                        log_level: int = logging.INFO,
                        **kwargs) -> logging.Logger:
    """Sets up a wrapping logger that writes to console and optionally a file.

    Initializes logging to stdout/stderr, and optionally a CSV formatted file.
    Wraps at a given file_size in MB, with default 2 backups.
    CSV format: timestamp,[level],(thread),module.function:line,message
    Default logging level is INFO.
    Timestamps are UTC/GMT/Zulu.

    Args:
        name: Name of the logger (if None, uses name of calling module).
        filename: Name of the file/path if writing to a file.
        file_size: Max size of the file in megabytes, before wrapping.
        log_level: the logging level (default INFO)
        kwargs: Optional overrides for RotatingFileHandler
    
    Returns:
        A logger with console stream handler and (optional) file handler.
    """
    log_formatter = logging.Formatter(fmt=FORMAT, datefmt='%Y-%m-%dT%H:%M:%S')
    log_formatter.converter = gmtime
    if name is None:
        name = get_caller_name()
    logger = logging.getLogger(name)
    if logger.getEffectiveLevel() == logging.DEBUG:
        log_level = logging.DEBUG
    #: Set up log file
    if filename is not None:
        try:
            filename = clean_filename(filename)
            if not os.path.isdir(os.path.dirname(filename)):
                os.mkdir(os.path.dirname(filename))
            handler_file = RotatingFileHandler(
                filename=filename,
                mode=kwargs.pop('mode', 'a'),
                maxBytes=kwargs.pop('maxBytes', int(file_size * 1024 * 1024)),
                backupCount=kwargs.pop('backupCount', 2),
                encoding=kwargs.pop('encoding', None),
                delay=kwargs.pop('delay', 0))
            handler_file.name = name + '_file_handler'
            handler_file.setFormatter(log_formatter)
            handler_file.setLevel(log_level)
            if not _is_log_handler(logger, handler_file):
                logger.addHandler(handler_file)
        except Exception as e:
            logger.exception(f'Could not create RotatingFileHandler {filename}'
                f' ({e})')
    logger.setLevel(log_level)
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.name = name + '_stdout_handler'
    handler_stdout.setFormatter(log_formatter)
    handler_stdout.setLevel(log_level)
    handler_stdout.addFilter(_LessThanFilter(logging.WARNING))
    if not _is_log_handler(logger, handler_stdout):
        logger.addHandler(handler_stdout)
    handler_stderr = logging.StreamHandler(sys.stderr)
    handler_stderr.name = name + '_stderr_handler'
    handler_stderr.setFormatter(log_formatter)
    handler_stderr.setLevel(logging.WARNING)
    if not _is_log_handler(logger, handler_stderr):
        logger.addHandler(handler_stderr)
    return logger
