from slowapi import Limiter

limiter: Limiter | None = None


def set_limiter(new_limiter: Limiter):
    global limiter
    limiter = new_limiter


def get_limiter():
    global limiter
    assert limiter
    return limiter
