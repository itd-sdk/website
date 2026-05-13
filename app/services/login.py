from time import sleep, time
from subprocess import Popen, PIPE, run as sp_run
from app.logger import get_logger

from pyautogui import click, typewrite, hotkey, locateOnScreen as locate_on_screen, ImageNotFoundException
from pyperclip import paste

l = get_logger('services.login')

def wait_for_image(path: str, timeout: int = 60):
    path = f'app/services/login_screens/{path}'
    start = time()
    while True:
        sleep(1)
        if time() - start > timeout:
            l.warning('%s not found after timeout', path)
            break
        try:
            l.debug('start locate')
            result = locate_on_screen(path, grayscale=True)
            l.debug('end locate')
            if result is not None:
                return result
        except ImageNotFoundException:
            l.debug('error locate')

def login(email: str, password: str) -> str | None:
    # start browser
    # click(887, 1049, button='RIGHT')
    # sleep(0.05)

    # click(856, 813)
    # sleep(2)
    try:

        Popen(['firefox', '--private-window', 'https://xn--d1ah4a.com/'], stdout=PIPE, stderr=PIPE)
        assert wait_for_image('home.png')

        # login
        l.debug('enter email')
        click(680, 383)
        typewrite(email)
        sleep(0.1)

        l.debug('enter password')
        click(680, 496)
        typewrite(password)
        sleep(0.1)

        l.debug('click login button')
        click(802, 621)

        wait_for_image('captcha.png')
        l.debug('click captcha')
        click(638, 440)

        assert wait_for_image('logout.png')

        l.debug('open devtools')
        hotkey('f12')
        sleep(0.5)

        l.debug('open storage tab')
        click(769, 103)
        sleep(0.5)

        l.debug('search token')
        click(330, 124)
        typewrite('refresh_token')
        sleep(0.3)

        l.debug('copy token')
        click(401, 174, clicks=2)
        sleep(0.3)

        hotkey('ctrl', 'c')
        sleep(0.3)

        token = paste()
        if len(token) != 64:
            l.error('invlid token %s', token)
        else:
            return token
    except Exception as e:
        l.error('error %s %s', e.__class__.__name__, e)
    finally:
        sp_run(['pkill', '-SIGTERM', '-f', 'firefox'], capture_output=True)
