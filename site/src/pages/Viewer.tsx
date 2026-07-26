import { useLocation } from "react-router";

/** 占位：后续任务（P10）实现真正的查看器 UI，这里先暴露 search 供路由测试断言 query 保留 */
export default function Viewer() {
  const { search } = useLocation();
  return (
    <div data-testid="page-viewer">
      <span data-testid="viewer-search">{search}</span>
    </div>
  );
}
