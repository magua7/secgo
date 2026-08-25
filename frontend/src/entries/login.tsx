import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LoginPage } from '../pages/LoginPage'
import '../styles/tokens.css'
import '../styles/globals.css'

document.documentElement.dataset.theme = 'light'
createRoot(document.getElementById('root')!).render(<StrictMode><LoginPage initialTheme="light" /></StrictMode>)
