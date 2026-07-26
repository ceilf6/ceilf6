import { PageTransition } from "../components/PageTransition";
import { PlatformStage } from "../components/PlatformStage";
import { vlogStage } from "../data/platforms";

export default function Vlog() {
  return (
    <PageTransition testId="page-vlog">
      <PlatformStage {...vlogStage} />
    </PageTransition>
  );
}
