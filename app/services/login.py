from time import sleep
from subprocess import Popen

from pyautogui import click, typewrite, hotkey
from pyperclip import paste


def login(username: str, password: str) -> str | None:
    # start browser
    # click(887, 1049, button='RIGHT')
    # sleep(0.05)

    # click(856, 813)
    # sleep(2)
    try:
        firefox = Popen(['firefox'])
        sleep(5)

        hotkey('ctrl', 'shift', 'p')
        sleep(5)

        typewrite('https://xn--d1ah4a.com/')
        hotkey('enter')
        sleep(5)

        # login
        click(708, 422)
        typewrite(username)
        sleep(0.05)

        click(671, 534)
        typewrite(password)
        sleep(0.05)

        click(754, 659)
        sleep(5)

        click(636, 438)
        sleep(5)

        # token spizdet

        hotkey('f12')
        sleep(0.05)

        click(769, 103)
        sleep(0.1)

        click(589, 372, clicks=2)
        sleep(0.05)

        hotkey('ctrl', 'c')
        sleep(0.05)

        firefox.kill()
        token = paste()
        if len(token) != 64:
            print('invlid token', token)
        else:
            return token
    except Exception as e:
        print('error', e.__class__.__name__, e)
        return None
