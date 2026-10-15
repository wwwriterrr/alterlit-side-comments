# alterlit-side-comments

Боковая лента «последние комментарии» в сайдбаре alterlit.ru / altcg.ru — остров на React + TypeScript + Vite.

- Первая лента приходит прямо в странице (`{% side_comments_data %}` → `<script type="application/json" id="side-comments-data">`), без запроса.
- Дальше — опрос `GET /api/v1/side_comments_v2/?v=<версия>` раз в 20 с, только пока вкладка видна; вернулись во вкладку — сразу. Без изменений — `304` без тела.
- Новые комментарии плавно появляются сверху; комментарии AltCG — серым «облачком», как раньше; у администрации — значок у имени.
- Готовую ленту можно прислать событием `window.dispatchEvent(new CustomEvent('alterlit:side-comments', {detail: {version, comments}}))` — например, из личного потока блока пользователя.

Бэкенд (`api/side_comments/`, сигналы, тег шаблона) — `django/side_comments_patch.py`.

## Разработка

```sh
npm install
npm run dev      # http://localhost:5179
npm run build    # dist/side_comments.js, dist/side_comments.css → /assets/side_comments/
```

`.env.local` (в git не попадает): `BACKEND_URL`, `DEV_COOKIE`; `DEV_FIXTURES=1` — ленту отдаёт dev-сервер
из `dev-fixtures/feed.json` (тоже вне git), пока ручки нет на сервере.

## Подключение (вместо `<ul class="side-comments load">…</ul>` в base.html)

```html
<div id="alterlit-side-comments"></div>
{% side_comments_data %}
<link rel="stylesheet" href="/assets/side_comments/side_comments.css?v=1">
<script type="module" src="/assets/side_comments/side_comments.js?v=1"></script>
```
