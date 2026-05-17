function get_el(id) {
  const element = document.getElementById(id);
  if (!element) {
    console.warn(`element ${element} not found`);
  }
  return element;
}

async function fetch_users() {
  const res = await fetch('/api/ebdi/users');
  if (!res.ok) {
    alert('Ошиба получения количества пользователей');
    return;
  }
  const json = await res.json();
  console.info(`fetched users count=${json.length}`);
  return json;
}

document.addEventListener('DOMContentLoaded', async () => {
  const users = await fetch_users();

  let place = 1;
  const template = get_el('user-template');
  for (let user of users) {
    const node = template.cloneNode(true);
    node.id = undefined;
    node.querySelector('.user-place').textContent = place + '.';
    node.querySelector('.user-avatar').textContent = user.avatar;
    node.querySelector('.user-display-name').textContent = user.display_name;
    node.querySelector('.user-display-name').href = 'https://итд.com/@' + user.username;
    console.log(user.username, user.verified, user.has_itdp)
    if (user.verified && user.has_itdp) {
      const icon = document.createElement('img');
      icon.src = '/static/icons/itdp_verified.svg';
      node.querySelector('.user-display-name').appendChild(icon);
    } else if (user.verified) {
      const icon = document.createElement('img');
      icon.src = '/static/icons/verified.svg';
      node.querySelector('.user-display-name').appendChild(icon);
    } else if (user.has_itdp) {
      const icon = document.createElement('img');
      icon.src = '/static/icons/itdp.svg';
      node.querySelector('.user-display-name').appendChild(icon);
    }
    node.querySelector('.user-username').textContent = '@' + user.username;
    node.querySelector('.user-followers').textContent = new Intl.NumberFormat().format(user.followers_count);
    node.querySelector('.user-following').textContent = new Intl.NumberFormat().format(user.following_count);
    node.querySelector('.user-posts').textContent = new Intl.NumberFormat().format(user.posts_count);
    node.querySelector('.user-created-at').textContent = (new Date(user.created_at)).toLocaleString('ru-RU', {year: 'numeric', month: 'long', day: 'numeric'}).replace(' г.', '');

    get_el('users').appendChild(node);
    place++;
  }
  template.remove();
});