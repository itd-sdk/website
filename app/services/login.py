from time import sleep
from subprocess import Popen, PIPE
from logging import getLogger

l = getLogger('services.login')
l.setLevel('DEBUG')

def login(email: str, password: str) -> str | None:
    # start browser
    # click(887, 1049, button='RIGHT')
    # sleep(0.05)

    # click(856, 813)
    # sleep(2)
    try:
        from pyautogui import click, typewrite, hotkey
        from pyperclip import paste

        firefox = Popen(['firefox', '--private-window', 'https://xn--d1ah4a.com/'], stdout=PIPE, stderr=PIPE)
        sleep(8)

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
        sleep(8)

        l.debug('click captcha')
        click(638, 440)
        sleep(5)

        # token spizdet
        l.debug('open devtools')
        hotkey('f12')
        sleep(0.5)

        l.debug('open storage tab')
        click(769, 103)
        sleep(0.5)

        l.debug('copy token')
        click(406, 306, clicks=2)
        sleep(0.5)

        hotkey('ctrl', 'c')
        sleep(0.3)

        firefox.kill()
        token = paste()
        if len(token) != 64:
            l.error('invlid token', token)
        else:
            return token
    except Exception as e:
        l.error('error', e.__class__.__name__, e)
        return None
