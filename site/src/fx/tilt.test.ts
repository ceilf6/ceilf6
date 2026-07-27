import { describe, expect, it } from "vitest";
import { fireEvent } from "@testing-library/dom";
import { attachTilt } from "./tilt";

describe("attachTilt", () => {
  it("mousemove 写入倾角与辉光坐标 CSS 变量", () => {
    const el = document.createElement("a");
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 }) as DOMRect;
    attachTilt(el, 10);
    fireEvent.mouseMove(el, { clientX: 100, clientY: 0 }); // 右上角
    expect(el.style.getPropertyValue("--tilt-ry")).toBe("10.00deg");
    expect(el.style.getPropertyValue("--tilt-rx")).toBe("8.00deg"); // -(-0.5) * 10 * 1.6
    expect(el.style.getPropertyValue("--gx")).toBe("100.0%");
    expect(el.style.getPropertyValue("--gy")).toBe("0.0%");
  });
  it("mouseleave 归零,cleanup 解绑", () => {
    const el = document.createElement("a");
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 }) as DOMRect;
    const off = attachTilt(el, 10);
    fireEvent.mouseMove(el, { clientX: 100, clientY: 100 });
    fireEvent.mouseLeave(el);
    expect(el.style.getPropertyValue("--tilt-ry")).toBe("0deg");
    off();
    fireEvent.mouseMove(el, { clientX: 100, clientY: 100 });
    expect(el.style.getPropertyValue("--tilt-ry")).toBe("0deg");
  });
  it("mousemove 后直接 off()(不经 mouseleave)倾角归零", () => {
    const el = document.createElement("a");
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 }) as DOMRect;
    const off = attachTilt(el, 10);
    fireEvent.mouseMove(el, { clientX: 100, clientY: 100 });
    expect(el.style.getPropertyValue("--tilt-ry")).toBe("10.00deg");
    off(); // cleanup 自带一次 leave():卸载瞬间不残留倾角
    expect(el.style.getPropertyValue("--tilt-ry")).toBe("0deg");
    expect(el.style.getPropertyValue("--tilt-rx")).toBe("0deg");
  });
});
