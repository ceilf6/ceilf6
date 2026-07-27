import { PageTransition } from "../components/PageTransition";
import { PlatformStage } from "../components/PlatformStage";
import { NotesPreview } from "../components/NotesPreview";
import { blogStage } from "../data/platforms";

/** 两层:上层站内札记(空时不渲染),下层平台跳转卡(LINUX DO/CSDN,不变项)。 */
export default function Blog() {
  return (
    <PageTransition testId="page-blog">
      <NotesPreview heading="站内札记" />
      <PlatformStage {...blogStage} />
    </PageTransition>
  );
}
