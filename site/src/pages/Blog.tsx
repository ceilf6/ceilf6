import { PageTransition } from "../components/PageTransition";
import { PlatformStage } from "../components/PlatformStage";
import { NotesPreview } from "../components/NotesPreview";
import { blogStage } from "../data/platforms";

/** 两层:上层平台跳转卡(LINUX DO/CSDN,不变项),下层站内札记(空时不渲染)。
    层序为对 spec 的有意偏差(协调者裁定):平台卡是用户明示保护的长期沉淀入口,
    札记增多后不该把它挤出首屏;且 main 在前、补充 section 在后,h1→h2 语义序自然成立。 */
export default function Blog() {
  return (
    <PageTransition testId="page-blog">
      <PlatformStage {...blogStage} />
      <NotesPreview heading="站内札记" />
    </PageTransition>
  );
}
