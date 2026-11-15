from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator


def with_offset(value: datetime) -> datetime:
    # naive columns hold the server's local time, a browser would read them as
    # its own local time, so the offset is attached before they are sent
    return value.astimezone() if value.tzinfo is None else value


LocalDatetime = Annotated[datetime, AfterValidator(with_offset)]
