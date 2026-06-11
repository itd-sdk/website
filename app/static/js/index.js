function get_el(id) {
    const element = document.getElementById(id);
    if (!element) {
        console.warn(`element ${element} not found`);
    }
    return element;
}

async function fetch_users_count() {
    const res = await fetch("/api/users/count");
    if (!res.ok) {
        alert("Ошиба получения количества пользователей");
        return;
    }
    const json = await res.json();
    console.info(`fetched users count count=${json.count}`);
    return json.count;
}

document.addEventListener("DOMContentLoaded", async () => {
    const count = await fetch_users_count();
    get_el("graph-description-current").textContent = count;
    get_el("graph").hidden = false;
    if (Math.floor(Math.random() * 101) < 5) {
        console.info("пасхалка добавлена :)");
        get_el("ebdi-description").textContent =
            "Ебливая База Данных ИТД - топ пользователей, вложения, (скоро посты и комментарии).";
    }
});
