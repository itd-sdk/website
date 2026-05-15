from time import sleep, time
from subprocess import Popen, PIPE, run as sp_run
from app.logger import get_logger

from itd import ITDClient
from itd.api.auth import sign_in
from pyautogui import click, typewrite, hotkey, locateOnScreen as locate_on_screen, ImageNotFoundException
from pyperclip import paste

l = get_logger('services.login')

def wait_for_image(path: str, timeout: int = 10):
    path = f'app/services/login_screens/{path}'
    start = time()
    while True:
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
        sleep(3)


def get_turnstile() -> str | None:
    # start browser
    # click(887, 1049, button='RIGHT')
    # sleep(0.05)

    # click(856, 813)
    # sleep(2)
    start = time()
    try:
        for i in range(1, 4):
            Popen(['firefox', '--private-window', 'https://xn--d1ah4a.com/'], stdout=PIPE, stderr=PIPE)
            if wait_for_image('home.png') is not None:
                break
            l.warning('failed to connect attempt=%s', i)
        else:
            l.error('failed to connect')
            return None

        l.debug('open devtools')
        hotkey('f12')
        sleep(0.3)

        l.debug('open console')
        hotkey('ctrl', 'shift', 'k')
        sleep(0.3)

        l.debug('inject script')
        typewrite('window.fetch = (input, init) => {console.log(init.body.turnstileToken)}')
        sleep(0.5)

        l.debug('enter email')
        click(530, 425)
        typewrite('itd_sdk_login@gmail.com')
        sleep(0.1)

        l.debug('enter password')
        click(530, 530)
        typewrite('123')
        sleep(0.1)

        l.debug('click login button')
        click(603, 659)

        wait_for_image('captcha.png')
        l.debug('click captcha')
        click(480, 440)

        assert wait_for_image('home.png')

        l.debug('copy turnstile')
        click(1288, 422, clicks=3)
        hotkey('ctrl', 'c')

        return eval(paste())['turnstileToken']
    except Exception as e:
        l.error('error %s %s', e.__class__.__name__, e)
    finally:
        l.info('spent %ss', round(time() - start))
        sp_run(['pkill', '-SIGTERM', '-f', 'firefox'])


def login(email: str, password: str):
    turnstile = get_turnstile()
    if turnstile is None:
        return
    return sign_in(ITDClient(), email, password, turnstile).cookies.get('refresh_token')
