# original by @itdStatus

from asyncio import sleep
from typing import cast

from camoufox.async_api import AsyncCamoufox
from fastapi.responses import JSONResponse
from playwright.async_api import Browser
from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.logger import get_logger

l = get_logger("login")


browser: Browser | None = None
camoufox = None

INTERCEPT_SCRIPT = """
() => {
    if (window.__t_patched) return;
    window.__t_patched = true;
    window.__t__ = null;

    window.onSuccess = tk => { window.__t__ = tk; };

    window.addEventListener('message', ev => {
        try {
            const data = (typeof ev.data === 'string') ? JSON.parse(ev.data) : ev.data;
            if (!data) return;
            const tk = data.token || data['cf-turnstile-response'] || data.cfToken;
            if (tk && typeof tk === 'string' && tk.length > 20) window.__t__ = tk;
        } catch (_) {}
    }, true);

    let attempts = 0;
    const iv = setInterval(() => {
        if (typeof window.turnstile !== 'undefined') {
            clearInterval(iv);
            const orig = window.turnstile.render.bind(window.turnstile);
            window.turnstile.render = (container, opts) => {
                const cb = opts.callback;
                opts.callback = tk => {
                    window.__t__ = tk;
                    if (typeof cb === 'function') cb(tk);
                };
                return orig(container, opts);
            };
        } else if (++attempts > 150) {
            clearInterval(iv);
        }
    }, 100);

    const origFetch = window.fetch;
    window.fetch = async (...args) => {
        const res = await origFetch(...args);
        try {
            const clone = res.clone();
            const text  = await clone.text();
            const json  = JSON.parse(text);
            const tk    = json.token || json['cf-turnstile-response'];
            if (tk && tk.length > 20) window.__t__ = tk;
        } catch (_) {}
        return res;
    };

    const observer = new MutationObserver(() => {
        const inp = document.querySelector(
            'input[name="cf-turnstile-response"], input[name="cf_turnstile_response"]'
        );
        if (inp && inp.value && inp.value.length > 20) window.__t__ = inp.value;
    });
    observer.observe(document.documentElement, { subtree: true, attributes: true, childList: true });
}
"""


async def _run_session():
    global browser
    assert browser

    context = None
    try:
        context = await browser.new_context()
        await context.add_init_script(INTERCEPT_SCRIPT)
        page = await context.new_page()

        try:
            await page.goto(
                "https://xn--d1ah4a.com/turnstile.html?theme=dark",
                wait_until="domcontentloaded",
                timeout=25_000
            )
        except PlaywrightTimeout:
            return

        await sleep(2)
        await page.mouse.move(20, 30)
        await sleep(0.15)
        await page.mouse.click(20, 30)

        interval = 0.3
        elapsed = 0.0
        token = None

        while elapsed < 30:
            token = await page.evaluate("""
                (() => {
                    if (window.__t__ && window.__t__.length > 20) return window.__t__;
                    const inp = document.querySelector(
                        'input[name="cf-turnstile-response"], input[name="cf_turnstile_response"], textarea[name="cf-turnstile-response"]'
                    );
                    if (inp && inp.value && inp.value.length > 20) return inp.value;
                    return null;
                })()
            """)
            if token:
                break
            await sleep(interval)
            elapsed += interval

        if not token:
            return False

        return token

    except Exception as e:
        l.error("fail to get token error=%s", e)
        return False

    finally:
        if context:
            await context.close()


async def start_browser():
    global browser, camoufox
    l.info("start browser")
    camoufox = AsyncCamoufox(headless=True, geoip=True, humanize=True)
    browser = cast(Browser, await camoufox.__aenter__())
    l.info("browser ready")


async def stop_browser():
    global camoufox
    assert camoufox
    l.info("stop browser")
    await camoufox.__aexit__(None, None, None)


async def get_turnstile():
    global browser
    assert browser

    context = None
    try:
        context = await browser.new_context()
        await context.add_init_script(INTERCEPT_SCRIPT)
        page = await context.new_page()

        try:
            await page.goto(
                "https://xn--d1ah4a.com/turnstile.html?theme=dark",
                wait_until="domcontentloaded",
                timeout=25_000
            )
        except PlaywrightTimeout:
            return JSONResponse({"detail": "fail to init playwright"}, 500)

        await sleep(2)
        await page.mouse.move(20, 30)
        await sleep(0.15)
        await page.mouse.click(20, 30)

        interval = 0.3
        elapsed = 0.0
        token = None

        while elapsed < 30:
            token = await page.evaluate("""
                (() => {
                    if (window.__t__ && window.__t__.length > 20) return window.__t__;
                    const inp = document.querySelector(
                        'input[name="cf-turnstile-response"], input[name="cf_turnstile_response"], textarea[name="cf-turnstile-response"]'
                    );
                    if (inp && inp.value && inp.value.length > 20) return inp.value;
                    return null;
                })()
            """)
            if token:
                break
            await sleep(interval)
            elapsed += interval

        if not token:
            return False

        return JSONResponse({"token": token})

    except Exception as e:
        l.error("fail to get token error=%s", e)
        return JSONResponse({"detail": e}, 500)

    finally:
        if context:
            await context.close()
