import { PageTransition } from "../components/PageTransition";
import { PlatformStage } from "../components/PlatformStage";
import { blogStage } from "../data/platforms";

export default function Blog() {
  return (
    <PageTransition testId="page-blog">
      <PlatformStage {...blogStage} />
    </PageTransition>
  );
}
