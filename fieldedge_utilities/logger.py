"""Wrapping logger common format for FieldEdge project(s) with UTC timestamp.

Provides a common log format with a console and file handler.
The file is a wrapping log of configurable size using `RotatingFileHandler`.

Format is:

* ISO UTC timestamp (datetime) e.g. `2021-01-01T00:00:00.000Z`
* Log level, CSV encloses in square brackets e.g. `[INFO]`
* Thread name, CSV encloses in round brackets
* Module, Function and Line. CSV uses `ModuleName.FunctionName:(LineNumber)`
* Message

*CSV Example:*

`2021-10-30T14:19:51.012Z,[INFO],(MainThread),main.<module>:6,This is a test`

*JSON Example:*

`{"timestamp":"2021-01-01T00:00:00Z","level":"INFO","thread":"MainThread",
"module":"main","function":"<module>","line":6,"message":"This is a test"}`

"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from time import gmtime

from fieldedge_utilities.path import clean_path

FORMAT_CSV = ('%(asctime)s.%(msecs)03dZ,[%(levelname)s],(%(threadName)s),'
              '%(module)s.%(funcName)s:%(lineno)d,%(message)s')
FORMAT_JSON = ('{'
                '"datetime":"%(asctime)s.%(msecs)03dZ"'
                ',"level":"%(levelname)s"'
                ',"thread":"%(threadName)s"'
                ',"module":"%(module)s"'
                ',"function":"%(funcName)s"'
                ',"line":%(lineno)d'
                ',"message":"%(message)s"'
                '}')
DATEFMT = '%Y-%m-%dT%H:%M:%S'

DEFAULT_OBSCURE = ['password', 'token', 'key', 'secret']


class LogFilterLessThan(logging.Filter):
    """Filters logs below a specified level for routing to a given handler.
    
    Intended to route `WARNING` and higher to `STDERR` and lower to `STDOUT`.

    """
    def __init__(self,
                 exclusive_maximum: int = logging.WARNING,
                 name: str = None):
        if name is None:
            name = f'LessThan{logging.getLevelName(exclusive_maximum)}'
        super().__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        #non-zero return means we log this message
        return 1 if record.levelno < self.max_level else 0


class LogFormatterOneLineException(logging.Formatter):
    """Formats exceptions into a single line stack trace.
    
    Also replaces the record message with the error type.

    """
    def formatException(self, exc_info):
        original = super().formatException(exc_info)
        return ' -> '.join([x.strip() for x in original.splitlines()])

    def format(self, record):
        result = super().format(record)
        if record.exc_text:
            err_type = type(record.msg).__name__
            result = result.replace(f'{record.msg}\n', f'{err_type}: ')
        return result


class LogFormatterObscureSensitive(LogFormatterOneLineException):
    """Formats all text to remove sensitive information."""
    @staticmethod
    def obscure(record: str) -> str:
        keywords = json.loads(os.getenv('OBSCURE', json.dumps(DEFAULT_OBSCURE)))
        if not any(k in record.lower() for k in keywords):
            return record
        wrappers = ['"', '\'']
        assignments = [': ', ':', '=', ' = ']
        separators = [',', ' ', '}', ']']
        to_replace = []
        for k in keywords:
            if k in record.lower():
                index = 0
                while index < len(record) - 1:
                    tag = k
                    index = record[index:].find(tag)
                    if index == -1:
                        break
                    for w in wrappers:
                        if record[index+len(tag)] == w:
                            tag = tag + w
                            break
                    for a in assignments:
                        if record[index+len(tag):index+len(tag)+len(a)] == a:
                            tag = tag + a
                            break
                    start = index + len(tag)
                    end = len(record) - start
                    for s in separators:
                        end = record[start:].find(s)
                        if end > -1:
                            break
                        end = len(record) - start
                    pattern = record[start:start+end]
                    for w in wrappers:
                        if pattern.startswith(w) and pattern.endswith(w):
                            pattern = pattern[len(w):-len(w)]
                            break
                    if pattern not in to_replace:
                        to_replace.append(pattern)
                    index = start + end + 1
        for r in to_replace:
            record = record.replace(r, '***')
        return record
    
    def format(self, record):
        preformatted = super().format(record)
        return self.obscure(preformatted)


def get_logfile_name(logger: logging.Logger) -> str:
    """Returns the logger's RotatingFileHandler name.
    
    Args:
        logger: The Logger to retrieve its file name from.

    Raises:
        TypeError if Logger is invalid

    """
    if not isinstance(logger, logging.Logger):
        raise TypeError('Invalid Logger')
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler):
            return h.baseFilename


def add_handler(logger: logging.Logger, handler: logging.Handler) -> None:
    """Adds a handler to a logger if one of the same name is not present.
    
    Args:
        logger: The logger to add the handler to.
        handler: The handler to add to the logger.
    
    Raises:
        TypeError if Logger or Handler are invalid
        ValueError if a handler with the same name is already in the logger.

    """
    if not isinstance(logger, logging.Logger):
        raise TypeError('Invalid Logger')
    if not isinstance(handler, logging.Handler):
        raise TypeError('Invalid Handler')
    for h in logger.handlers:
        if h.name == handler.name:
            raise ValueError(f'Logger already has a handler named {h.name}')
    logger.addHandler(handler)


def apply_formatter(logger: logging.Logger,
                    formatter: logging.Formatter) -> None:
    """Applies the log formatter to all handlers in the logger.
    
    Args:
        logger: The logger with the handler targets.
        formatter: The formatter to apply.

    Raises:
        TypeError if Logger or Handler are invalid
    
    """
    if not isinstance(logger, logging.Logger):
        raise TypeError('Invalid Logger')
    if not isinstance(formatter, logging.Formatter):
        raise TypeError('Invalid Formatter')
    for h in logger.handlers:
        h.setFormatter(formatter)


def apply_loglevel(logger: logging.Logger, level: int) -> None:
    """Sets the log level on all handlers except stderr (always WARNING).
    
    Args:
        logger: The logger whose handlers to apply the level to.
        level: The logging level to apply

    Raises:
        TypeError if Logger is invalid
    
    """
    if not isinstance(logger, logging.Logger):
        raise TypeError('Invalid Logger')
    for h in logger.handlers:
        if 'stderr' not in h.name:
            h.setLevel(level)


def get_formatter(format: str = 'csv',
                  obscure: bool = False) -> logging.Formatter:
    """Returns a standardized log formatter.
    
    Args:
        format: `csv` or `json` are supported.
        obscure: `True` will obscure logged text with keys matching environment
            variable `OBSCURE` as a JSON-formatted array.
    
    Returns:
        A `logging.Formatter`

    """
    fmt = FORMAT_JSON if format == 'json' else FORMAT_CSV
    if obscure:
        log_formatter = LogFormatterObscureSensitive(fmt, DATEFMT)
    else:
        log_formatter = LogFormatterOneLineException(fmt, DATEFMT)
    log_formatter.converter = gmtime
    return log_formatter


def get_handler_file(filename: str,
                     file_size: int = 5,
                     **kwargs) -> RotatingFileHandler:
    if not filename:
        raise ValueError('Missing filename')
    filename = clean_path(filename)
    if not os.path.isdir(os.path.dirname(filename)):
        raise FileNotFoundError('Invalid logfile path'
            f' {os.path.dirname(filename)}')
    handler = RotatingFileHandler(
        filename=filename,
        mode=kwargs.pop('mode', 'a'),
        maxBytes=kwargs.pop('maxBytes', int(file_size * 1024 * 1024)),
        backupCount=kwargs.pop('backupCount', 2),
        encoding=kwargs.pop('encoding', None),
        delay=kwargs.pop('delay', 0),
    )
    handler.name = f'{kwargs.pop("name", __name__)}_file_handler'
    return handler


def get_handler_stdout(**kwargs) -> logging.StreamHandler:
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.name = f'{kwargs.pop("name", __name__)}_stdout_handler'
    handler_stdout.addFilter(LogFilterLessThan(logging.WARNING))
    return handler_stdout


def get_handler_stderr(**kwargs) -> logging.StreamHandler:
    handler_stderr = logging.StreamHandler(sys.stderr)
    handler_stderr.name = f'{kwargs.pop("name", __name__)}_stderr_handler'
    handler_stderr.setLevel(logging.WARNING)
    return handler_stderr


def get_wrapping_logger(name: str = None,
                        filename: str = None,
                        file_size: int = 5,
                        log_level: int = logging.INFO,
                        format: str = 'csv',
                        **kwargs) -> logging.Logger:
    """Sets up a wrapping logger that writes to console and optionally a file.

    DEPRECATED in favour of get_fieldede_logger

    * Default logging level is `INFO`
    * Timestamps are UTC ISO 8601 format
    * Initializes logging to stdout/stderr, and optionally a CSV or JSON
    formatted file. Default is CSV.
    * Wraps files at a given `file_size` in MB, with default 2 backups.
    
    CSV format: timestamp,[level],(thread),module.function:line,message

    Args:
        name: Name of the logger (if None, uses name of calling module).
        filename: Name of the file/path if writing to a file.
        file_size: Max size of the file in megabytes, before wrapping.
        log_level: the logging level (default INFO)
        format: `csv` or `json`
        kwargs: Optional overrides for RotatingFileHandler
            mode (str): defaults to `a` (append)
            maxBytes (int): overrides file_size
            backupCount (int): defaults to 2
    
    Returns:
        A `Logger` with console `StreamHandler` and (optional)
            `RotatingFileHandler`.
    
    Raises:
        `FileNotFoundError` if a logfile name is specified with an invalid path.
    
    """
    if not name:
        name = __name__
    logger = logging.getLogger(name)
    if filename is not None:
        filename = clean_path(filename)
        if not os.path.isdir(os.path.dirname(filename)):
            raise FileNotFoundError('Invalid logfile path'
                f' {os.path.dirname(filename)}')
        add_handler(logger, get_handler_file(filename,
                                             name=name,
                                             file_size=file_size,
                                             **kwargs))
    add_handler(logger, get_handler_stdout(name=name))
    add_handler(logger, get_handler_stderr(name=name))
    apply_formatter(logger, get_formatter(format))
    logger.setLevel(log_level)
    return logger


def get_fieldedge_logger(filename: str = None,
                         file_size: int = 5,
                         log_level: 'int|str' = logging.INFO,
                         format: str = 'csv',
                         **kwargs) -> logging.Logger:
    """Sets up a root logger that writes to console and optionally a file.

    * Default logging level is `INFO`
    * Timestamps are UTC ISO 8601 format
    * Initializes logging to stdout/stderr, and optionally a CSV or JSON
    formatted file. Default is CSV.
    * Wraps files at a given `file_size` in MB, with default 2 backups.
    
    Args:
        name: Name of the logger (if None, uses name of calling module).
        filename: Name of the file/path if writing to a file.
        file_size: Max size of the file in megabytes, before wrapping.
        log_level: the logging level (default INFO)
        format: `csv` or `json`
    
    Keyword Args:
        mode (str): writing mode defaults to `a` (append)
        maxBytes (int): overrides file_size
        backupCount (int): defaults to 2
        obscure (bool): Set `True` to obscure values in logs defined by the
            `OBSCURE` environment variable as a JSON array of keywords. Default
            keywords: `password`, `token`, `key`, `secret`.
    
    Returns:
        A `Logger` with console `StreamHandler` and (optional)
            `RotatingFileHandler`.
    
    Raises:
        `FileNotFoundError` if a logfile name is specified with an invalid path.
    
    """
    logger = logging.getLogger()
    filehandler_kwargs = {}
    for k, v in kwargs.items():
        if k in ['mode', 'maxBytes', 'backupCount']:
            filehandler_kwargs[k] = v
    if isinstance(log_level, str):
        log_level = log_level.upper()
    if filename is not None:
        filename = clean_path(filename)
        if not os.path.isdir(os.path.dirname(filename)):
            raise FileNotFoundError('Invalid logfile path'
                                    f' {os.path.dirname(filename)}')
        add_handler(logger, get_handler_file(filename,
                                             file_size=file_size,
                                             **kwargs))
    add_handler(logger, get_handler_stdout())
    add_handler(logger, get_handler_stderr())
    apply_formatter(logger, get_formatter(format, kwargs.get('obscure', False)))
    logger.setLevel(log_level)
    return logger


def verbose_logging(filter: str = '', case_sensitive: bool = True) -> bool:
    """Indicates if verbose logging is configured, with an optional filter.
    
    Args:
        filter: An optional filter e.g. the package+module name
        case_sensitive: Defaults to case sensitive filter.
    
    Returns:
        True if `LOG_VERBOSE` environment variable is set
            and includes the filter.
            
    """
    log_verbose = os.getenv('LOG_VERBOSE')
    if log_verbose:
        if filter:
            if (filter in log_verbose or
                not case_sensitive and filter.upper() in log_verbose.upper()):
                return True
            return False
        return True
    return False
