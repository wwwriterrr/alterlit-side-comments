/** Комментарий боковой ленты: GET /api/v1/side_comments_v2/ и <script id="side-comments-data">. */
export interface SideComment {
  id: number;
  /** AL — Альтерлит, ALT — AltCG */
  site: string;
  date: string;
  /** обычный текст, до 100 символов */
  text: string;
  /** абсолютная ссылка на комментарий в посте */
  url: string;
  author: {
    id: number;
    username: string;
    name: string;
    avatar: string | null;
    is_staff: boolean;
  };
  post: { id: number; title: string; author: string };
}

export interface Feed {
  /** меняется при любом изменении ленты */
  version: string;
  comments: SideComment[];
}

/** Лента из страницы — её кладёт шаблон ({% side_comments_data %}), без запроса. */
export function readInitialFeed(): Feed | null {
  const el = document.getElementById('side-comments-data');
  if (!el?.textContent) return null;
  try {
    const data = JSON.parse(el.textContent) as Feed;
    return Array.isArray(data?.comments) ? data : null;
  } catch {
    return null;
  }
}

/** Свежая лента; null — не изменилась (304). */
export async function fetchFeed(version: string | null, signal?: AbortSignal): Promise<Feed | null> {
  const q = version ? `?v=${encodeURIComponent(version)}` : '';
  const r = await fetch(`/api/v1/side_comments_v2/${q}`, { headers: { Accept: 'application/json' }, signal });
  if (r.status === 304) return null;
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as Feed;
}
