import { Navigate, Route, Routes, useLocation } from "react-router";
import { AnimatePresence } from "framer-motion";
import Home from "./pages/Home";
import Blog from "./pages/Blog";
import Vlog from "./pages/Vlog";
import Viewer from "./pages/Viewer";

/** 旧站 .html 直链的站内兜底：Nginx 301（cutover Stage B）之前/失效时依然可达 */
function LegacyViewerRedirect() {
  const { search } = useLocation();
  return <Navigate to={`/viewer${search}`} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
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
    <AnimatePresence mode="wait">
      <div key={location.pathname}>
        <AppRoutes />
      </div>
    </AnimatePresence>
  );
}
