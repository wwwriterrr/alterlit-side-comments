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
