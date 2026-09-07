function get_el(id) {
    const element = document.getElementById(id);
    if (!element) {
        console.warn(`element ${id} not found`);
    }
    return element;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function move_dvd() {
    const dvd = document.getElementById("dvd");
    dvd.hidden = false;

    let x = 0;
    let y = 0;
    let vx = 200; // px per second
    let vy = 150;

    let lastTime = performance.now();

    function random_hue() {
        dvd.style.filter = `sepia(1) saturate(6) hue-rotate(${Math.floor(Math.random() * 360)}deg)`;
    }

    function tick(now) {
        const dt = (now - lastTime) / 1000;
        lastTime = now;

        const maxX = window.innerWidth - dvd.offsetWidth;
        const maxY = window.innerHeight - dvd.offsetHeight;

        x += vx * dt;
        y += vy * dt;

        // bounce and clamp so it can't get stuck outside the viewport
        if (x <= 0) {
            x = 0;
            vx = Math.abs(vx);
            random_hue();
        }
        if (x >= maxX) {
            x = maxX;
            vx = -Math.abs(vx);
            random_hue();
        }
        if (y <= 0) {
            y = 0;
            vy = Math.abs(vy);
            random_hue();
        }
        if (y >= maxY) {
            y = maxY;
            vy = -Math.abs(vy);
            random_hue();
        }

        dvd.style.transform = `translate(${x}px, ${y}px)`;

        requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
}

document.addEventListener("DOMContentLoaded", () => {
    if (
        navigator.userAgent.includes("YaBrowser") &&
        !(localStorage.getItem("yandex_seen") ?? false)
    ) {
        const check = get_el("captcha-check");

        get_el("captcha-dialog").showModal();
        check.checked = false;
        check.addEventListener(
            "click",
            async () => {
                localStorage.setItem("yandex_seen", true);
                check.hidden = true;
                get_el("captcha-load").hidden = false;
                await sleep(1500);
                get_el("captcha-dialog").close();
                await sleep(100);
                get_el("yandex-dialog").showModal();
                await sleep(5000);
                get_el("yandex-dialog").close();
                get_el("bear").hidden = false;
                get_el("yandex-ads").hidden = false;
                get_el("yandex-bad").hidden = false;
                get_el("rkn").hidden = false;
                get_el("putin").hidden = false;
                get_el("dima").hidden = false;
                const audio = new Audio("/static/audio/russia.mp3");
                audio.loop = true;
                audio.volume = 1;
                audio.play();
                document.querySelector("body").classList.add("yandex");
                move_dvd();
            },
            { once: true },
        );
    }
});
