import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '@openuidev/react-ui';

import '@openuidev/react-ui/defaults.css';
import '@openuidev/react-ui/components.css';
import '../../index.css';
import './viewer.css';

import DeliverableViewer from './DeliverableViewer';

const data =
  window.__DELIVERABLE__ && typeof window.__DELIVERABLE__ === 'object'
    ? window.__DELIVERABLE__
    : { title: 'Deliverable', summary: '', sections: [] };

if (data.title) {
  document.title = data.title;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider mode="dark">
      <DeliverableViewer data={data} />
    </ThemeProvider>
  </StrictMode>,
);
