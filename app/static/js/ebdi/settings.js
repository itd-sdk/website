// interface settings of the ebdi pages, kept in this browser; loaded in the
// head so the theme is set before the page is drawn
const ebdi_settings = (() => {
    const KEY = "ebdi-settings";
    const DEFAULTS = {
        theme: "dark",
        rounded: false,
        marks: true,
        user_styles: true,
        compact_numbers: false,
        audio_proxy: true,
    };
    let values = { ...DEFAULTS };
    try {
        values = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
    } catch (error) {
        console.warn("settings are not readable", error);
    }

    function apply() {
        const root = document.documentElement;
        root.dataset.theme = values.theme;
        root.toggleAttribute("data-rounded", values.rounded);
    }

    function set(key, value) {
        values[key] = value;
        try {
            localStorage.setItem(KEY, JSON.stringify(values));
        } catch (error) {
            console.warn("settings are not saved", error);
        }
        apply();
        // the pages redraw what depends on the setting
        window.dispatchEvent(
            new CustomEvent("ebdi-settings", { detail: { key, value } }),
        );
    }

    const exact = new Intl.NumberFormat("ru-RU");
    const compact = new Intl.NumberFormat("ru-RU", {
        notation: "compact",
        maximumFractionDigits: 1,
    });

    function format_count(value) {
        return (values.compact_numbers ? compact : exact).format(value);
    }

    function css_var(name) {
        return getComputedStyle(document.documentElement)
            .getPropertyValue(name)
            .trim();
    }

    function init_panel() {
        const button = document.getElementById("settings-button");
        const panel = document.getElementById("settings-panel");
        if (!button || !panel) {
            return;
        }
        const toggle = (open) => {
            panel.hidden = !open;
            button.setAttribute("aria-expanded", open);
        };
        button.addEventListener("click", () => toggle(panel.hidden));
        document.addEventListener("click", (event) => {
            if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) {
                toggle(false);
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key == "Escape" && !panel.hidden) {
                toggle(false);
                button.focus();
            }
        });
        for (const input of panel.querySelectorAll("input[name=theme]")) {
            input.checked = input.value == values.theme;
            input.addEventListener("change", () => set("theme", input.value));
        }
        for (const input of panel.querySelectorAll("input[data-setting]")) {
            input.checked = values[input.dataset.setting];
            input.addEventListener("change", () =>
                set(input.dataset.setting, input.checked),
            );
        }
    }

    apply();
    document.addEventListener("DOMContentLoaded", init_panel);
    return { values, set, format_count, css_var };
})();
