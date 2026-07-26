import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/azeret-mono/400.css";
import "@fontsource/azeret-mono/500.css";
import "@fontsource/azeret-mono/700.css";
import "@fontsource/zcool-xiaowei/400.css";
import "./styles/tokens.css";
import "./styles/global.css";
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
