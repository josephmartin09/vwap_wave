import logging
import os
import time

import coloredlogs


def enable_sublogger(logger_name):
    """Enable a sub-logger by name.

    :param str logger_name: Name of the logger to enable
    """
    root_level = logging.getLogger().level
    logging.getLogger(logger_name).setLevel(root_level)


def disable_sublogger(logger_name):
    """Disable a sub-logger by name.

    :param str logger_name: Name of the logger to disable
    """
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)


def setup_logging(logfile="app.log", utc_time=False, root_level=logging.INFO):
    """Configure the root logger with both a command line logger and a file logger.

    :param str logfile: Desired logfile name
    :param bool utc_time: Log time in UTC if True. Otherwise log in OS-local time.
    :param logging.level root_level: Default logging level of root logger. Defaults to INFO
    """
    # Setup logging
    logger = logging.getLogger()
    logging_fmt = "[{levelname:^8s}] [{asctime}] [{name}] {message}"
    date_fmt = "%y-%m-%d %H:%M:%S"

    # Create a coloredlog formatter for command line logging
    colored_formatter = coloredlogs.ColoredFormatter(
        fmt=logging_fmt,
        datefmt=date_fmt,
        style="{",
        level_styles={
            "debug": {"color": "green", "bright": True},
            "info": {"color": "white", "bright": True},
            "warning": {"color": "yellow", "bright": True},
            "error": {"color": "red", "bright": True},
            "critical": {
                "color": "black",
                "background": "red",
                "bold": True,
                "bright": True,
            },
        },
        field_styles={
            "levelname": {"color": "white", "bright": True},
            "asctime": {"color": "white"},
            "filename": {"color": "white"},
        },
    )

    # Create a simple formatter for other output
    formatter = logging.Formatter(fmt=logging_fmt, datefmt=date_fmt, style="{")

    formatters = [colored_formatter, formatter]
    if utc_time:
        for f in formatters:
            f.converter = time.gmtime

    # Reuse handlers installed by this function so repeated setup calls do not
    # duplicate output. Leave handlers owned by libraries or callers alone.
    console_handler = next(
        (
            handler
            for handler in logger.handlers
            if getattr(handler, "_vwap_wave_console_handler", False)
        ),
        None,
    )
    if console_handler is None:
        console_handler = logging.StreamHandler()
        console_handler._vwap_wave_console_handler = True
        logger.addHandler(console_handler)
    console_handler.setFormatter(colored_formatter)

    desired_logfile = os.path.abspath(logfile)
    file_handler = next(
        (
            handler
            for handler in logger.handlers
            if getattr(handler, "_vwap_wave_file_handler", False)
        ),
        None,
    )
    if file_handler is not None and file_handler.baseFilename != desired_logfile:
        logger.removeHandler(file_handler)
        file_handler.close()
        file_handler = None

    if file_handler is None:
        file_handler = logging.FileHandler(desired_logfile, mode="w")
        file_handler._vwap_wave_file_handler = True
        logger.addHandler(file_handler)
    file_handler.setFormatter(formatter)

    # Set default logging level
    logger.setLevel(root_level)
