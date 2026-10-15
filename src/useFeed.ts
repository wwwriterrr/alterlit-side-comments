import { useEffect, useRef, useState } from 'react';
import { fetchFeed, readInitialFeed, type Feed } from './api';

/** Как часто спрашивать, пока вкладка на экране. Ответ «ничего нового» — 304 без тела. */
const POLL_MS = 20_000;
/** Ленту уже присылают по сокету (вошедшим — через блок пользователя): опрос — только подстраховка. */
const POLL_WITH_PUSH_MS = 60_000;
/** После ошибки сети — реже, чтобы не долбить лежащий сервер. */
const RETRY_MS = 60_000;

export type FeedState = {
  feed: Feed | null;
  status: 'loading' | 'ready' | 'error';
  /** id, которых не было в прошлой ленте — для анимации появления; в первой ленте пусто */
  fresh: ReadonlySet<number>;
};

const NONE: ReadonlySet<number> = new Set();

/**
 * Лента: сначала из страницы, дальше — опрос ручки, только пока вкладка видна.
 * Вернулись во вкладку — сразу проверяем. Готовую ленту можно прислать и событием
 * window 'alterlit:side-comments' (например, из личного потока юзербара) — опрос не нужен.
 */
export function useFeed(): FeedState {
  const [state, setState] = useState<FeedState>(() => {
    const feed = readInitialFeed();
    return { feed, status: feed ? 'ready' : 'loading', fresh: NONE };
  });
  const version = useRef(state.feed?.version ?? null);

  useEffect(() => {
    let timer: number | undefined;
    let ctrl: AbortController | null = null;
    let alive = true;
    let pushed = false; // хоть раз пришла лента по сокету — значит, он работает
    const pollMs = () => (pushed ? POLL_WITH_PUSH_MS : POLL_MS);

    const apply = (feed: Feed) => {
      if (feed.version === version.current) return;
      version.current = feed.version;
      setState((prev) => {
        const before = new Set(prev.feed?.comments.map((c) => c.id) ?? []);
        const fresh = prev.feed ? new Set(feed.comments.filter((c) => !before.has(c.id)).map((c) => c.id)) : NONE;
        return { feed, status: 'ready', fresh };
      });
    };

    const schedule = (ms: number) => {
      window.clearTimeout(timer);
      if (document.visibilityState === 'visible') timer = window.setTimeout(check, ms);
    };

    async function check() {
      ctrl?.abort();
      ctrl = new AbortController();
      try {
        const feed = await fetchFeed(version.current, ctrl.signal);
        if (!alive) return;
        if (feed) apply(feed);
        schedule(pollMs());
      } catch (err) {
        if (!alive || (err as Error).name === 'AbortError') return;
        setState((s) => (s.feed ? s : { feed: null, status: 'error', fresh: NONE }));
        schedule(RETRY_MS);
      }
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') check();
      else window.clearTimeout(timer);
    };
    const onPush = (e: Event) => {
      const feed = (e as CustomEvent<Feed>).detail;
      if (!feed || !Array.isArray(feed.comments)) return;
      pushed = true;
      apply(feed);
      schedule(pollMs()); // свежая лента только что пришла — следующий опрос отодвигаем
    };

    // в странице ленты нет (старый шаблон, ошибка кеша) — грузим сразу, иначе ждём первый интервал
    if (version.current) schedule(pollMs());
    else check();
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('alterlit:side-comments', onPush);

    return () => {
      alive = false;
      window.clearTimeout(timer);
      ctrl?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('alterlit:side-comments', onPush);
    };
  }, []);

  return state;
}
