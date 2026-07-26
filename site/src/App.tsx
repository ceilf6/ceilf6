import { Navigate, Route, Routes, useLocation, type Location } from "react-router";
import { AnimatePresence } from "framer-motion";
import { SplashScreen } from "./components/SplashScreen";
import Home from "./pages/Home";
import Blog from "./pages/Blog";
import Vlog from "./pages/Vlog";
import Viewer from "./pages/Viewer";

/** 旧站 .html 直链的站内兜底：Nginx 301（cutover Stage B）之前/失效时依然可达 */
function LegacyViewerRedirect() {
  const { search } = useLocation();
  return <Navigate to={`/viewer${search}`} replace />;
}

/**
 * `location` 可选：App 会把它钉在 AnimatePresence 的 key 所对应的那个 location 上，
 * 否则退场中的旧页会跟着实时 location 重新匹配路由、渲染出新页内容。
 */
export function AppRoutes({ location }: { location?: Location }) {
  return (
    <Routes location={location}>
      <Route path="/" element={<Home />} />
      <Route path="/blog" element={<Blog />} />
      <Route path="/vlog" element={<Vlog />} />
      <Route path="/viewer" element={<Viewer />} />
      <Route path="/blog.html" element={<Navigate to="/blog" replace />} />
      <Route path="/vlog.html" element={<Navigate to="/vlog" replace />} />
      <Route path="/viewer.html" element={<LegacyViewerRedirect />} />
      <Route path="/index.html" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  const location = useLocation();
  return (
    <>
      <SplashScreen />
      <AnimatePresence mode="wait">
        <div key={location.pathname}>
          <AppRoutes location={location} />
        </div>
      </AnimatePresence>
    </>
  );
}
