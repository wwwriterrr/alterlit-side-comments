# Боковая лента «последние комментарии» — остров React (в сайдбаре сайта).
# Работает ПАРАЛЛЕЛЬНО старой ленте: свои ключи кеша (side_comments_v2:*), своя ручка, свои сигналы.
# Старое (Comment.is_sidecomment, AppendSideComment, sc% в /checker/, RequestToAPI("sc_add"))
# не трогаем — уберём, когда новая лента заменит старую.
#
# ── Как устроено ────────────────────────────────────────────────────────────
#   rules.py  — ЕДИНСТВЕННОЕ место с условиями: какие комментарии попадают в ленту сайта;
#   feed.py   — лента из БД → JSON с версией, кеш на сутки; при пустом кеше собирается из БД.
#               Сборка не сортирует таблицу комментариев: ищет окнами по диапазону id (1000, 2000,
#               4000… — только первичный ключ; редкие комментарии AltCG тоже находятся) и проверяет посты/рубрики/авторов по списку
#               id — 4 коротких запроса, а не перебор всей таблицы;
#               (раньше лента пустела после рестарта/истечения кеша до следующего комментария);
#   signals   — любое изменение, влияющее на ленту → пересборка обеих лент после коммита,
#               в фоновом потоке (ответ на POST/DELETE её не ждёт)
#               (новый/изменённый/удалённый/забаненный комментарий, смена статуса или рубрик поста,
#               скрытие/ник/аватар автора, деактивация) — раньше бан и скрытие поста ленту не трогали;
#   ручка     — GET /api/v1/side_comments_v2/?v=<версия> → 200 {version, comments} или 304, из кеша;
#   шаблон    — первая лента прямо в странице (<script type="application/json">), без запроса.
#
# Фронт опрашивает ручку раз в 20 секунд, только пока вкладка видна; вернулись во вкладку —
# сразу. Если ничего не изменилось — 304 без тела.
#
# ── Правила ленты (rules.py) — проверьте ────────────────────────────────────
#   • комментарий к публикации: опубликован, не забанен, с текстом; ответы — тоже;
#   • автор активен, не скрыт (global_hidden), не id 6501;
#   • пост опубликован (status='published': не в профиле, не на модерации, не скрыт, не черновик),
#     дата публикации наступила, пост не 46184 / 91187;
#   • рубрики поста: хотя бы одна из списка сайта и ни одной не из списка;
#       alterlit — комментарии с AL и ALT, рубрики SC_IDS + SC_IDS_ALT;
#       altcg    — только ALT, рубрики SC_IDS_ALT; «чужими» считаются только рубрики AltCG.
#   Где старый код расходился, выбрано так:
#     – is_sidecomment пропускал пост вовсе без рубрик, _get_side_comments — нет → без рубрик НЕ идёт;
#     – is_sidecomment исключал только profile/moderate/rejected, но не hidden/draft → только published;
#     – AppendSideComment клал комментарий AltCG только в ленту AltCG, а HTML-лента Альтерлита
#       показывала и AltCG → на Альтерлите видны оба (как в HTML-ленте).
#
# ── Подключение ─────────────────────────────────────────────────────────────
#   1) пакет api/side_comments/ (п. 1–5), в INSTALLED_APPS не добавлять;
#   2) api/urls.py:  path('side_comments_v2/', include('api.side_comments.urls')),
#   3) сигналы — в blog/signals.py (п. 6);
#   4) тег шаблона — в blog/templatetags/blog_extras.py (п. 7);
#   5) шаблон — п. 8; статика острова — /assets/side_comments/;
#   7) мгновенно у вошедших: channels_utils и ChatStreamConsumer — п. 10.
#   6) индекс (site, id) у Comment — обязателен для ленты AltCG (п. 9.1);
#      по желанию — индекс по дате для старого кода (п. 9.2).


# ── 1. api/side_comments/__init__.py — пустой файл ──────────────────────────


# ── 2. api/side_comments/rules.py ───────────────────────────────────────────
"""
Боковая лента «последние комментарии» — ЕДИНСТВЕННОЕ место, где описано, какие комментарии в неё
попадают. Всё остальное (кеш, ручка, сигналы, шаблон) берёт выборку отсюда.

Правила собраны из старого кода (Comment.is_sidecomment, Comment._get_side_comments,
Comment._get_comments, AppendSideComment), где они местами расходились.
"""
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone as tz

from blog.models import Comment, Post

LIMIT = 6

# Рубрики, комментарии к постам которых идут в ленту (были Comment.SC_IDS / SC_IDS_ALT)
CATEGORIES_AL = [1, 3, 4, 6, 7, 10, 25, 32, 33, 34, 35, 37, 40, 42, 43, 44, 45, 46, 48, 49, 50, 51, 53, 54, 58, 59, 61]
CATEGORIES_ALT = [19, 20, 21, 22]

EXCLUDED_POSTS = [46184, 91187]  # было захардкожено в is_sidecomment
EXCLUDED_AUTHORS = [6501]        # было в Comment._get_comments

# Лента сайта (request.mode):
#   sites       — с какого сайта комментарии: на Альтерлите — и свои, и AltCG (как в старой ленте);
#   categories  — у поста должна быть хотя бы одна из этих рубрик и ни одной другой;
#   alt_only    — «другие рубрики» считаем только среди рубрик AltCG (Category.site='ALT'),
#                 как is_sidecomment для AltCG: альтерлитовские рубрики у кросспоста не мешают;
#   sparse      — комментарии сайта редкие (на AltCG последние подходящие — сотни тысяч записей
#                 назад): ищем не окнами по id, а по индексу (site, id) — см. п. 9 патча.
MODES = {
    'alterlit': {'sites': ['AL', 'ALT'], 'categories': CATEGORIES_AL + CATEGORIES_ALT, 'alt_only': False,
                 'sparse': False},
    'altcg': {'sites': ['ALT'], 'categories': CATEGORIES_ALT, 'alt_only': True, 'sparse': True},
}


WINDOW = 1000  # первое окно по id; каждое следующее — вдвое шире (1000, 2000, 4000, …)
# Альтерлиту обычно хватает первого окна. На AltCG комментируют редко — окна растут, пока не
# наберётся лента или не кончится таблица: при ~2 млн комментариев это ~11 окон, все — чтение
# первичного ключа по диапазону. Сборка идёт в фоне после коммита и кешируется.


def modes_for_site(site):
    """Ленты, в которые может попасть комментарий этого сайта: AL — только Альтерлит, ALT — обе."""
    return [mode for mode, rule in MODES.items() if site in rule['sites']]


def _post_ok(post_ids, rule):
    """Какие из постов подходят ленте сайта. 2 запроса по списку id, без перебора таблиц."""
    now = tz.now()
    visible = set(Post.objects
                  .filter(id__in=post_ids, status='published', date__lte=now)
                  .exclude(id__in=EXCLUDED_POSTS)
                  .values_list('id', flat=True))
    if not visible:
        return set()
    allowed = set(rule['categories'])
    cats = {}
    for post_id, cat_id, cat_site in (Post.category.through.objects
                                      .filter(post_id__in=visible)
                                      .values_list('post_id', 'category_id', 'category__site')):
        cats.setdefault(post_id, []).append((cat_id, cat_site))
    ok = set()
    for post_id in visible:
        post_cats = cats.get(post_id, [])
        # хотя бы одна рубрика из списка сайта…
        if not any(cat_id in allowed for cat_id, _ in post_cats):
            continue
        # …и ни одной чужой (для AltCG — среди рубрик AltCG)
        considered = [c for c in post_cats if not rule['alt_only'] or c[1] == 'ALT']
        if all(cat_id in allowed for cat_id, _ in considered):
            ok.add(post_id)
    return ok


def _author_ok(comment):
    profile = getattr(comment.author, 'profile', None)
    return comment.author.is_active and not getattr(profile, 'global_hidden', False)


BATCH = 200  # кандидатов за один заход по индексу (site, id)


def _candidates_dense(rule, base):
    """Сайт, где комментируют часто: окна по диапазону первичного ключа (1000, 2000, 4000…).
    Диапазон PK MySQL читает только по первичному ключу — без сортировки всей таблицы."""
    top = Comment.objects.order_by('-id').values_list('id', flat=True).first()
    if not top:
        return
    upper, size = top + 1, WINDOW
    while upper > 0:
        lower = max(upper - size, 0)
        size *= 2
        yield list(base.filter(id__gte=lower, id__lt=upper).order_by('-id'))
        upper = lower


def _candidates_sparse(rule, base):
    """Сайт с редкими комментариями: WHERE site=… ORDER BY id DESC LIMIT — по индексу (site, id)
    это несколько сотен строк индекса, а не перебор таблицы. Без индекса — медленно (п. 9 патча)."""
    before = None
    while True:
        qs = base.filter(id__lt=before) if before else base
        batch = list(qs.order_by('-id')[:BATCH])
        if not batch:
            return
        yield batch
        before = batch[-1].id


def feed_comments(mode, limit=LIMIT):
    """
    Комментарии ленты сайта, новые сверху (не больше limit).

    Кандидатов берём пачками (по первичному ключу или по индексу сайта — см. sparse),
    посты, рубрики и авторов проверяем потом по списку id (2 коротких запроса на пачку).
    Не сортируем всю таблицу по date/status: индекса по date нет, а с индексом status
    оптимизатор может собрать все опубликованные комментарии и отсортировать их — секунды.
    """
    rule = MODES[mode]
    base = (Comment.objects
            .filter(content_type=ContentType.objects.get_for_model(Post), site__in=rule['sites'],
                    status='published', is_banned=False)
            .exclude(content__isnull=True)
            .exclude(content='')
            .exclude(author_id__in=EXCLUDED_AUTHORS)
            .select_related('author', 'author__profile'))
    batches = _candidates_sparse(rule, base) if rule['sparse'] else _candidates_dense(rule, base)
    found = []
    for batch in batches:
        if not batch:
            continue
        ok_posts = _post_ok({c.object_id for c in batch}, rule)
        for c in batch:
            if c.object_id in ok_posts and _author_ok(c):
                found.append(c)
                if len(found) == limit:
                    return found
    return found


# ── 3. api/side_comments/feed.py ────────────────────────────────────────────
"""Сборка ленты, кеш и обновление. Источник правды — БД (rules.feed_queryset), кеш — только ускорение."""
import hashlib
import html
import json
import logging
import re
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import connections, transaction
from django.utils.html import strip_tags
from django.utils.text import Truncator

from blog.models import Post

from alterlit.channels_utils import CHANNELS_MESSAGE_TYPES, send_to_group, side_comments_group
from api.side_comments.rules import MODES, feed_comments

logger = logging.getLogger('alterlit')

CACHE_KEY = 'side_comments_v2:{mode}'
CACHE_TTL = 60 * 60 * 24  # сутки; при пустом кеше лента пересобирается из БД, а не пропадает
EXCERPT = 100

RE_BREAKS = re.compile(r'<(?:br|/p|/div|/li|/h[1-6]|/blockquote)\b[^>]*>', re.I)


def excerpt(content):
    """Текст без HTML; абзацы и переносы — пробелом, чтобы не склеивались («…ПетропавловскийMayor1»)."""
    text = html.unescape(strip_tags(RE_BREAKS.sub(' ', content or '')))
    text = re.sub(r'\s+', ' ', text).strip()
    return Truncator(text).chars(EXCERPT)


def _domain(site):
    return settings.ALTCG_DOMAIN if site == 'ALT' else settings.AL_DOMAIN


def build(mode):
    """Лента из БД: {"version": "...", "comments": [...]}."""
    comments = feed_comments(mode)
    posts = {p.id: p for p in (Post.objects
                               .filter(id__in={c.object_id for c in comments})
                               .select_related('author', 'author__profile')
                               # status — его читает Post.__init__ (__original_status); без него — лишний запрос на пост
                               .only('id', 'title', 'status', 'author__id', 'author__username',
                                     'author__profile__nickname'))}
    items = []
    for c in comments:
        post = posts.get(c.object_id)
        url = f'{_domain(c.site)}/post/{c.object_id}/?anchor=comments&comment_id={c.id}'
        items.append({
            'id': c.id,
            'site': c.site,
            'date': c.date.isoformat(),
            'text': excerpt(c.content),
            'url': url,
            'author': {
                'id': c.author.id,
                'username': c.author.username,
                'name': c.author.get_name(),
                'avatar': c.author.get_avatar(),
                'is_staff': c.author.is_staff,
            },
            'post': {
                'id': c.object_id,
                'title': strip_tags(post.title) if post else '',
                'author': post.author.get_name() if post else '',
            },
        })
    payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
    # версия меняется при любом изменении ленты: новый, удалённый, отредактированный комментарий
    version = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]
    return {'version': version, 'comments': items}


def get(mode):
    """Лента из кеша; нет в кеше (холодный старт, истёк TTL) — собираем из БД."""
    if mode not in MODES:
        mode = 'alterlit'
    data = cache.get(CACHE_KEY.format(mode=mode))
    if data is None:
        data = build(mode)
        cache.set(CACHE_KEY.format(mode=mode), data, CACHE_TTL)
    return data


def refresh(modes=None):
    """
    Пересобрать ленты сайтов (по умолчанию — обе). Вызывать через refresh_on_commit.
    Лента изменилась — разослать её вошедшим: личный поток (ws/chat/stream/) состоит в группе
    side_comments_<сайт>, блок пользователя пересылает событие острову ленты. Анонимы — опросом.
    """
    for mode in modes or MODES:
        key = CACHE_KEY.format(mode=mode)
        old = cache.get(key)
        data = build(mode)
        cache.set(key, data, CACHE_TTL)
        if not old or old['version'] != data['version']:
            push(mode, data)


def push(mode, data):
    """Событие {type: side_comments, version, comments} в группу ленты сайта."""
    try:
        send_to_group(side_comments_group(mode), {'type': CHANNELS_MESSAGE_TYPES['side_comments'], **data})
    except Exception:
        logger.exception('side_comments: push')


def _refresh_in_background(modes):
    try:
        refresh(modes)
    except Exception:
        logger.exception('side_comments: refresh')
    finally:
        connections.close_all()  # у потока своё соединение с БД — не оставляем висеть


def refresh_on_commit(modes=None):
    """
    После коммита — в фоновом потоке: ответ на POST/DELETE комментария не ждёт пересборку,
    а лента видит итог транзакции. Несколько изменений подряд — несколько коротких пересборок.
    """
    transaction.on_commit(
        lambda: threading.Thread(target=_refresh_in_background, args=(modes,), daemon=True).start())


# ── 4. api/side_comments/views.py ───────────────────────────────────────────
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.notification.notifications import request_mode
from api.side_comments import feed


class SideCommentsView(APIView):
    """
    GET /api/v1/side_comments_v2/?v=<version>
        → 200 {"version": "...", "comments": [...]}  — лента сайта (по request.mode)
        → 304 без тела                                — v совпадает: ничего не изменилось
    Публичная, без сессии и CSRF: ответ из кеша, без запросов в БД.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        data = feed.get(request_mode(request))
        if request.query_params.get('v') == data['version']:
            return Response(status=304)
        response = Response(data)
        response['Cache-Control'] = 'no-cache'
        return response


# ── 5. api/side_comments/urls.py ────────────────────────────────────────────
from django.urls import path

from api.side_comments import views

# в api/urls.py: path('side_comments_v2/', include('api.side_comments.urls')),
urlpatterns = [
    path('', views.SideCommentsView.as_view(), name='side_comments'),
]


# ── 6. blog/signals.py — пересборка ленты ───────────────────────────────────
# Отдельные получатели — рядом с существующими (старые comment_post_save и т. п. не трогаем).
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User

from blog.models import Comment, Post, Profile
from api.side_comments.feed import refresh_on_commit
from api.side_comments.rules import modes_for_site


@receiver(post_save, sender=Comment)
@receiver(post_delete, sender=Comment)
def side_comments_on_comment(sender, instance, **kwargs):
    # новый, правка текста, бан, смена статуса, удаление — лента пересобирается из БД.
    # Только ленты сайтов, куда комментарий может попасть: с Альтерлита — не трогаем AltCG
    # (там редкие комментарии ищутся по всей таблице — незачем делать это на каждый чужой).
    if instance.content_type.model == 'post':
        refresh_on_commit(modes_for_site(instance.site))


def _remember(fields):
    """pre_save: запомнить старые значения полей, чтобы post_save понял, изменилось ли важное."""
    def handler(sender, instance, **kwargs):
        old = sender.objects.filter(pk=instance.pk).values(*fields).first() if instance.pk else None
        instance._side_comments_old = old
    return handler


def _changed(instance, fields):
    old = getattr(instance, '_side_comments_old', None)
    return old is None or any(old[f] != getattr(instance, f) for f in fields)


POST_FIELDS = ['status', 'date', 'title', 'author_id']
PROFILE_FIELDS = ['global_hidden', 'nickname', 'avatar']   # профиль сохраняется часто (last_seen) —
USER_FIELDS = ['is_active', 'username']                    # пересобираем, только если поменялось видное

pre_save.connect(_remember(POST_FIELDS), sender=Post, weak=False, dispatch_uid='sc_post_old')
pre_save.connect(_remember(PROFILE_FIELDS), sender=Profile, weak=False, dispatch_uid='sc_profile_old')
pre_save.connect(_remember(USER_FIELDS), sender=User, weak=False, dispatch_uid='sc_user_old')


@receiver(post_save, sender=Post, dispatch_uid='sc_post_saved')
def side_comments_on_post(sender, instance, created, **kwargs):
    if not created and _changed(instance, POST_FIELDS):
        refresh_on_commit()


@receiver(post_delete, sender=Post, dispatch_uid='sc_post_deleted')
def side_comments_on_post_delete(sender, instance, **kwargs):
    refresh_on_commit()


@receiver(m2m_changed, sender=Post.category.through, dispatch_uid='sc_post_categories')
def side_comments_on_post_categories(sender, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        refresh_on_commit()


@receiver(post_save, sender=Profile, dispatch_uid='sc_profile_saved')
def side_comments_on_profile(sender, instance, created, **kwargs):
    if not created and _changed(instance, ['global_hidden', 'nickname', 'avatar']):
        refresh_on_commit()


@receiver(post_save, sender=User, dispatch_uid='sc_user_saved')
def side_comments_on_user(sender, instance, created, **kwargs):
    if not created and _changed(instance, USER_FIELDS):
        refresh_on_commit()


# ── 7. blog/templatetags/blog_extras.py — первая лента в странице ───────────
from django.utils.html import json_script


@register.simple_tag(takes_context=True)
def side_comments_data(context):
    """<script type="application/json" id="side-comments-data">{version, comments}</script> — из кеша."""
    from api.side_comments import feed  # не тянем при импорте тегов
    request = context.get('request')
    return json_script(feed.get(getattr(request, 'mode', 'alterlit')), 'side-comments-data')


# ── 8. Шаблон (base.html) ───────────────────────────────────────────────────
# Вместо:
#     <ul class="side-comments load"> … sc-preload … </ul>
# поставить:
#     <div id="alterlit-side-comments"></div>
#     {% side_comments_data %}
#     <link rel="stylesheet" href="/assets/side_comments/side_comments.css?v=1">
#     <script type="module" src="/assets/side_comments/side_comments.js?v=1"></script>
#
# Старый JS сам «выключится»: блок SIDE_COMMENTS и sc% в $._main_checker срабатывают, только если
# на странице есть .side-comments / .side-comment — их больше нет. Остальное в чекере не меняется.
# Для проверки рядом со старой лентой можно сначала включить новую только себе:
#     {% if request.user.id == 1 %} … новая … {% else %} … старая … {% endif %}


# ── 9. Индексы для blog.Comment ─────────────────────────────────────────────
# 9.1 ОБЯЗАТЕЛЬНО для ленты AltCG — индекс (site, id).
# На AltCG комментируют редко: последние подходящие комментарии — сотни тысяч записей назад
# (замер: ~470 000 при top ~1 980 000). Без индекса найти их можно только перебором — ~11 с.
# С индексом WHERE site='ALT' … ORDER BY id DESC LIMIT 200 читает несколько сотен записей индекса.
#
# blog/models.py — в class Meta модели Comment:
#
#     indexes = [
#         models.Index(fields=['site', 'id'], name='comment_site_id'),
#     ]
#
#     ./manage.py makemigrations blog --name comment_site_id
#     ./manage.py migrate blog
#
# • MySQL (InnoDB) строит вторичный индекс онлайн, запись не блокируется; на ~2 млн строк —
#   десятки секунд. Лучше, когда на сайте тихо.
# • Проверка (./manage.py dbshell):
#       EXPLAIN SELECT id FROM blog_comment WHERE site = 'ALT' AND status = 'published'
#       ORDER BY id DESC LIMIT 200;
#   key — comment_site_id, в Extra нет «Using filesort».
# • Пока индекса нет, лента AltCG собирается секунды (перебор таблицы): холодный запрос ручки
#   на altcg.ru будет ждать, пересборка после комментария AltCG — тоже (в фоне, ответ не ждёт).
#
# 9.2 По желанию — индекс для СТАРОГО кода, который сортирует комментарии по date.
# НОВОЙ ленте индекс не нужен: она идёт по первичному ключу (ORDER BY id DESC LIMIT 200)
# и останавливается на первых подходящих. Список комментариев поста в v2 — тоже по id
# внутри одного object_id (индекс по object_id уже есть).
#
# Нужен он СТАРОМУ коду, который сортирует комментарии по date по всей таблице:
#   Comment._get_side_comments / _check_sidecomments (старая лента), страница «Комментарии»
#   (comment_api post all), Comment._get_comments(..., order='-date'). У Comment есть индексы
#   по author, status, object_id, но не по date — MySQL сортирует всю выборку (filesort).
#
# blog/models.py — в class Meta модели Comment:
#
#     indexes = [
#         # «последние комментарии к постам»: WHERE content_type_id=… AND status=… ORDER BY date
#         models.Index(fields=['content_type', 'status', 'date'], name='comment_ct_status_date'),
#     ]
#
# затем:
#     ./manage.py makemigrations blog --name comment_ct_status_date
#     ./manage.py migrate blog
#
# • MySQL (InnoDB 5.6+) добавляет вторичный индекс онлайн: таблица не блокируется на запись,
#   но на большой таблице сборка займёт от секунд до минут — лучше, когда на сайте тихо.
# • Проверка, что индекс используется (./manage.py dbshell):
#       EXPLAIN SELECT id FROM blog_comment
#       WHERE content_type_id = 1 AND status = 'published' ORDER BY date DESC LIMIT 6;
#   в key — comment_ct_status_date, в Extra нет «Using filesort».
# • Таблица — blog_comment, если у Comment нет Meta.db_table; content_type_id = 1 — post
#   (так в старом коде: content_type.id == 1).


# ── 10. Мгновенное обновление у вошедших — через личный поток ───────────────
# feed.refresh() после пересборки, если лента изменилась, шлёт в группу side_comments_<сайт>:
#     {"message": {"type": "side_comments", "version": "…", "comments": [...]}}
# Личный поток (ws/chat/stream/) вступает в группу своего сайта; блок пользователя пересылает
# событие на страницу (window 'alterlit:side-comments'), остров ленты его принимает.
# Анонимы (личного потока у них нет) — опросом ручки, как раньше.

# 10.1 alterlit/channels_utils.py
CHANNELS_MESSAGE_TYPES = {
    # ...существующие типы без изменений...
    'side_comments': 'side_comments',
}


def side_comments_group(mode):
    """Лента «последние комментарии» сайта (alterlit | altcg)."""
    return f'side_comments_{mode}'


# 10.2 blog/consumers.py — ChatStreamConsumer.connect: + группа ленты своего сайта
#
#     from alterlit.channels_utils import user_group, notifications_group, side_comments_group
#
#     async def connect(self):
#         user = self.scope.get('user')
#         if user is None or user.is_anonymous:
#             await self.close(code=4001)
#             return
#         mode = mode_for_scope(self.scope)
#         self.groups_joined = [user_group(user.id), notifications_group(user.id, mode),
#                               side_comments_group(mode)]
#         for group in self.groups_joined:
#             await self.channel_layer.group_add(group, self.channel_name)
#         await self.accept()
#
# disconnect уже выходит из всех groups_joined — менять не нужно.
