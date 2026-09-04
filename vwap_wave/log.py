import inspect
import logging
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
    coloredFormatter = coloredlogs.ColoredFormatter(
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

    formatters = [coloredFormatter, formatter]
    if utc_time:
        for f in formatters:
            f.converter = time.gmtime

    # Add the colored logs to the logger
    h = logging.StreamHandler()
    h.setFormatter(coloredFormatter)
    logger.addHandler(h)

    # Add file logging to the logger
    h = logging.FileHandler(logfile, mode="w")
    h.setFormatter(formatter)
    logger.addHandler(h)

    # Set default logging level
    logger.setLevel(root_level)
