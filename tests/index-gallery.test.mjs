import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const indexHtml = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const inlineScripts = [...indexHtml.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(
  (match) => match[1],
);

function createClassList(element) {
  const classes = new Set();

  return {
    add(...names) {
      names.forEach((name) => classes.add(name));
      element.className = [...classes].join(" ");
    },
    contains(name) {
      return classes.has(name);
    },
    remove(...names) {
      names.forEach((name) => classes.delete(name));
      element.className = [...classes].join(" ");
    },
    setFromClassName(value) {
      classes.clear();
      value
        .split(/\s+/)
        .filter(Boolean)
        .forEach((name) => classes.add(name));
    },
  };
}

function createElement(tagName) {
  const listeners = new Map();
  const element = {
    attributes: {},
    children: [],
    offsetWidth: tagName === "div" ? 200 : 0,
    parentNode: null,
    style: {
      setProperty(name, value) {
        this[name] = value;
      },
    },
    tagName: tagName.toUpperCase(),
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    appendChild(child) {
      child.parentNode = element;
      element.children.push(child);
      return child;
    },
    dispatchEventType(type, event = {}) {
      const listener = listeners.get(type);
      assert.ok(listener, `expected ${type} listener on ${tagName}`);
      listener(event);
    },
    querySelector(selector) {
      if (selector === "img") {
        return element.children.find((child) => child.tagName === "IMG") ?? null;
      }
      return null;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
  };
  const classList = createClassList(element);
  Object.defineProperty(element, "className", {
    get() {
      return element._className ?? "";
    },
    set(value) {
      element._className = value;
      classList.setFromClassName(value);
    },
  });
  element.classList = classList;
  return element;
}

function runIndexScript() {
  assert.equal(inlineScripts.length, 1, "index.html should have one inline script");

  const gallery = createElement("div");
  gallery.id = "gallery";
  const openedUrls = [];
  const resizeListeners = [];
  const document = {
    createElement,
    getElementById(id) {
      assert.equal(id, "gallery");
      return gallery;
    },
    querySelectorAll(selector) {
      assert.equal(selector, ".gallery .card");
      return gallery.children;
    },
  };
  const window = {
    addEventListener(type, listener) {
      assert.equal(type, "resize");
      resizeListeners.push(listener);
    },
    open(url, target) {
      openedUrls.push({ target, url });
    },
  };

  vm.runInNewContext(inlineScripts[0], {
    document,
    images: [
      {
        alt: "fixture-award",
        src: "resume-awards/imgs/source.png",
        thumb: "resume-awards/imgs/thumb.jpg",
        width: 1000,
        height: 1500,
        thumbWidth: 200,
        thumbHeight: 300,
      },
    ],
    window,
  });

  return { gallery, openedUrls, resizeListeners };
}

test("gallery cards reserve metadata-based masonry space before thumbnails load", () => {
  const { gallery } = runIndexScript();
  const card = gallery.children[0];
  const img = card.querySelector("img");

  assert.ok(card.classList.contains("is-loading"));
  assert.equal(card.style.aspectRatio, "200 / 300");
  assert.equal(card.style.gridRowEnd, "span 324");
  assert.equal(img.width, 200);
  assert.equal(img.height, 300);
  assert.equal(img.style.opacity, "0");
});

test("gallery cards hide loading state after thumbnail load", () => {
  const { gallery } = runIndexScript();
  const card = gallery.children[0];
  const img = card.querySelector("img");

  img.dispatchEventType("load");

  assert.equal(img.style.opacity, "1");
  assert.ok(!card.classList.contains("is-loading"));
  assert.ok(card.classList.contains("is-loaded"));
  assert.equal(card.style.gridRowEnd, "span 324");
});
