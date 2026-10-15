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
