import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import App from './App'
import './globals.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Toaster
      position="top-center"
      richColors
      toastOptions={{
        style: { borderRadius: 0 },
        duration: 3000,
      }}
    />
    <App />
  </StrictMode>,
)
