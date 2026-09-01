import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/index.css'
import './i18n'
import Start from './Start'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Start />
  </StrictMode>,
)
