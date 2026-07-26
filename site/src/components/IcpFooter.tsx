import { ICP } from "../data/site";
import "./IcpFooter.css";

export function IcpFooter() {
  return (
    <footer className="icp-footer">
      <a href={ICP.href} target="_blank" rel="noopener noreferrer">
        {ICP.text}
      </a>
    </footer>
  );
}
