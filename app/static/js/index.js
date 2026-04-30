function get_el(id) {
  const element = document.getElementById(id);
  if (!element) {
    console.warn(`element ${element} not found`);
  }
  return element;
}

async function fetch_users_count() {
  const res = await fetch('/api/users/count');
  if (!res.ok) {
    alert('Ошиба польучения количества пользователей');
    return;
  }
  const json = await res.json();
  console.info(`fetched users count count=${json.count}`);
  return json.count;
}

document.addEventListener('DOMContentLoaded', async () => {
  const count = await fetch_users_count();

  get_el('graph-progress-bar').style.background = `linear-gradient(to right, #fd7f08 ${count / 500}%, #1E1C1A ${count / 500}%)`;
  get_el('graph-progress-count-value').textContent = `${Math.round(count / 500)}%`;
  get_el('graph-descriription-current').textContent = count;
  get_el('graph').hidden = false;
});