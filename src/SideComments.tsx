import { useState } from 'react';
import type { SideComment } from './api';
import { useFeed } from './useFeed';
import s from './SideComments.module.css';

/** Боковая лента «последние комментарии» — как прежняя .side-comments сайдбара. */
export default function SideComments() {
  // fresh — новые с прошлой ленты: плавно «въезжают» сверху; первая лента — без анимации
  const { feed, status, fresh } = useFeed();
  const comments = feed?.comments ?? [];

  if (status === 'loading') return <Skeleton />;
  if (status === 'error' && !comments.length) {
    return <p className={s.note}>Не удалось загрузить комментарии. Обновите страницу.</p>;
  }
  if (!comments.length) return <p className={s.note}>Комментариев пока нет.</p>;

  return (
    <ul className={s.list} aria-label="Последние комментарии">
      {comments.map((c) => (
        <Item key={c.id} comment={c} fresh={fresh.has(c.id)} />
      ))}
    </ul>
  );
}

function Item({ comment: c, fresh }: { comment: SideComment; fresh: boolean }) {
  const profile = `/profile/${encodeURIComponent(c.author.username)}/`;
  const postLine = [c.post.author, c.post.title].filter(Boolean).join(': ');
  return (
    <li className={s.item} data-site={c.site === 'ALT' ? 'alt' : 'al'} data-fresh={fresh || undefined}>
      <div className={s.head}>
        <a className={s.avatarLink} href={profile} tabIndex={-1} aria-hidden="true">
          <Avatar id={c.author.id} name={c.author.name} src={c.author.avatar} />
        </a>
        <a className={s.name} href={profile}>
          <span className={s.nameText}>{c.author.name}</span>
          <AdminBadge id={c.author.id} isStaff={c.author.is_staff} />
        </a>
      </div>
      <a className={s.text} href={c.url}>
        {c.text}
      </a>
      {postLine && (
        <a className={s.post} href={c.url} title={postLine}>
          {postLine}
        </a>
      )}
    </li>
  );
}

const AVATAR_COLORS = ['#254F23', '#C9861E', '#407BC8', '#B85454', '#5B48D1', '#2F8C9C', '#6B7F2A', '#8A5A3C'];

function Avatar({ id, name, src }: { id: number; name: string; src: string | null }) {
  const [broken, setBroken] = useState(false);
  if (src && !broken) return <img className={s.avatar} src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
  const parts = name.trim().split(/[\s_.-]+/).filter(Boolean);
  const initials = parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] ?? '?').slice(0, 2);
  return (
    <span className={s.avatar} style={{ background: AVATAR_COLORS[id % AVATAR_COLORS.length] }}>
      {initials.toUpperCase()}
    </span>
  );
}

/** id владельца сайта — красный значок; администрация (is_staff) — синий. Как в чате и комментариях. */
const OWNER_ID = 79691;
const BADGE_LABEL = { staff: 'Администрация сайта', owner: 'Владелец сайта' } as const;

function AdminBadge({ id, isStaff }: { id: number; isStaff: boolean }) {
  const kind = id === OWNER_ID ? 'owner' : isStaff ? 'staff' : null;
  if (!kind) return null;
  return (
    <svg className={s.badge} data-kind={kind} viewBox="0 0 50 50" role="img" aria-label={BADGE_LABEL[kind]}>
      <title>{BADGE_LABEL[kind]}</title>
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M25 48C37.7025 48 48 37.7025 48 25C48 17.5654 44.4725 10.9547 39 6.75025C35.8069 25.6826 32.9139 35.1307 25 48ZM11 6.75025C14.1931 25.6826 17.0861 35.1307 25 48C12.2975 48 2 37.7025 2 25C2 17.5654 5.52745 10.9547 11 6.75025ZM13.1778 5.26687C22.46 8.25353 27.6384 8.35772 36.8222 5.26687C33.3674 3.19265 29.323 2 25 2C20.677 2 16.6326 3.19265 13.1778 5.26687Z"
      />
      <path d="M19.2778 11C19.0769 10.2616 19.183 10.0051 20 10H30C30.8111 10.0027 30.9445 10.2249 30.7445 10.9199L28.7778 18C28.5214 18.8123 28.2295 19.0106 27.5 19H22.5C21.6701 18.9923 21.4421 18.7134 21.2222 18L19.2778 11Z" />
      <path d="M19 33C20.9255 37.9373 22.2483 40.673 25 45.5C27.6861 40.8225 29.0148 38.0944 31 33L28.6793 21.3963C28.5251 20.7218 28.2919 20.4994 27.5 20.5H22.5C21.7009 20.4917 21.4615 20.7077 21.3207 21.3963L19 33Z" />
    </svg>
  );
}

function Skeleton() {
  return (
    <ul className={`${s.list} ${s.skeleton}`} aria-busy="true" aria-label="Загрузка комментариев">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <li key={i} className={s.item}>
          <div className={s.head}>
            <span className={`${s.avatar} ${s.ghost}`} />
            <span className={`${s.ghost} ${s.gName}`} />
          </div>
          <span className={`${s.ghost} ${s.gLine}`} />
          <span className={`${s.ghost} ${s.gShort}`} />
        </li>
      ))}
    </ul>
  );
}
