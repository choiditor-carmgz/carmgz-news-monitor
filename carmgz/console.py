"""ASCII-safe console text; UTF-8 persistence is deliberately unchanged."""
import logging


def ascii_console(text):
    """Escape unsupported characters without changing process-wide stream settings."""
    return str(text).encode('ascii', errors='backslashreplace').decode('ascii')


class AsciiConsoleFormatter(logging.Formatter):
    def format(self, record):
        return ascii_console(super().format(record))
