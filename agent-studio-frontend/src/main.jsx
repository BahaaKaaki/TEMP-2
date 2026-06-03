import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider } from '@openuidev/react-ui'
import '@openuidev/react-ui/defaults.css'
import '@openuidev/react-ui/components.css'
import './index.css'
import App from './App.jsx'

// OpenUI ships only a `prefers-color-scheme` dark palette, so on a light-mode OS
// its components (deliverable charts, tables, tooltips) would render light inside
// our always-dark deliverable surface. OpenUI is only used for agent deliverables,
// which are always dark, so pin its theme to dark regardless of the OS scheme.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider mode="dark">
      <App />
    </ThemeProvider>
  </StrictMode>,
)
