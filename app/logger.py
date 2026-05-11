import logging
from sys import stdout

from fastapi.requests import Request
from fastapi.responses import Response


class ShortNameFormatter(logging.Formatter):
    def __init__(self, fmt: str | None = None, datefmt: str | None = None, colorful: bool = True) -> None:
        super().__init__(fmt, datefmt)
        self.colorful = colorful

    def format(self, record):
        if record.name == "itd_web":
            record.display_name = ""
        elif self.colorful:
            record.display_name = f"[bold]{record.name.split('.', maxsplit=1)[-1]}:[/bold] "
        else:
            record.display_name = f"{record.name.split('.', maxsplit=1)[-1]}: "
        return super().format(record)


def setup_logging(level: str = "INFO", colorful: bool = True) -> logging.Logger:
    level = level.upper()

    logger = logging.getLogger("itd_web")
    logger.propagate = False

    for h in list(logger.handlers):
        logger.removeHandler(h)

    if colorful:
        from rich.logging import RichHandler

        handler = RichHandler(rich_tracebacks=True, markup=True)
        formatter = ShortNameFormatter("%(display_name)s%(message)s", "%y.%m.%d %H:%M:%S")
    else:
        handler = logging.StreamHandler(stream=stdout)
        formatter = ShortNameFormatter(
            "%(asctime)s [%(levelname)s] %(display_name)s%(message)s",
            "%y.%m.%d %H:%M:%S",
            False
        )

    handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


def format_request(request: Request, response: Response, colorful: bool = True) -> str:
    if colorful:
        if 200 <= response.status_code < 300:
            color = "green"
        elif 300 <= response.status_code < 400:
            color = "yellow"
        elif 400 <= response.status_code < 500:
            color = "red"
        else:
            color = "bold red"

        return f"{request.method} {request.url.path} -> [{color}]{response.status_code}"
    return f"{request.method} {request.url.path} -> {response.status_code}"



def get_logger(name: str | None = None) -> logging.Logger:
    prefix = "itd_web"
    return logging.getLogger(f"{prefix}.{name}" if name else prefix)

