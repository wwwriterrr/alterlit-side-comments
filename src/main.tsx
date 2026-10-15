import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import SideComments from './SideComments';

// Шаблон: <div id="alterlit-side-comments"></div> и {% side_comments_data %} — первая лента в странице.
const rootEl = document.getElementById('alterlit-side-comments');
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <SideComments />
    </StrictMode>,
  );
}
