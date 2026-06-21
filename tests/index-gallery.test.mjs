import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const indexHtml = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const styleMatch = indexHtml.match(/<style>([\s\S]*?)<\/style>/i);
assert.ok(styleMatch, "index.html should include an inline style block");
const indexStyles = styleMatch[1];
const inlineScripts = [...indexHtml.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(
  (match) => match[1],
);

function getCssRule(selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = indexStyles.match(new RegExp(`${escapedSelector}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`));
  assert.ok(match, `${selector} rule should exist`);
  return match[1];
}

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
      if (selector.startsWith(".")) {
        const className = selector.slice(1);
        return element.children.find((child) => child.classList.contains(className)) ?? null;
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
  const readmeCards = [
    createElement("a"),
    createElement("a"),
    createElement("a"),
    createElement("a"),
  ];
  for (const [index, card] of readmeCards.entries()) {
    card.className = "readme-card is-loading";
    const loader = createElement("span");
    loader.className = "readme-card-loader";
    loader.textContent = "加载中";
    const image = createElement("img");
    image.alt = `readme-card-${index}`;
    image.complete = false;
    image.naturalWidth = 0;
    card.appendChild(loader);
    card.appendChild(image);
  }
  const openedUrls = [];
  const resizeListeners = [];
  const document = {
    createElement,
    getElementById(id) {
      assert.equal(id, "gallery");
      return gallery;
    },
    querySelectorAll(selector) {
      if (selector === ".gallery .card") return gallery.children;
      if (selector === ".readme-card") return readmeCards;
      throw new Error(`unexpected selector: ${selector}`);
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

  return { gallery, openedUrls, readmeCards, resizeListeners };
}

test("page background uses fixed visual layers instead of a body paint fallback", () => {
  const htmlRule = getCssRule("html");
  const bodyRule = getCssRule("body");
  const bodyBeforeRule = getCssRule("body::before");
  const bodyAfterRule = getCssRule("body::after");
  const htmlAfterRule = getCssRule("html::after");

  assert.match(indexStyles, /--page-background:\s*[\s\S]*linear-gradient\(/);
  assert.match(htmlRule, /background-color:\s*var\(--bg-void\);/);
  assert.match(bodyRule, /background:\s*transparent;/);
  assert.doesNotMatch(bodyRule, /background-color:/);
  assert.match(bodyBeforeRule, /position:\s*fixed;/);
  assert.match(bodyBeforeRule, /background:\s*var\(--page-background\);/);
  assert.match(bodyBeforeRule, /z-index:\s*-3;/);
  assert.match(bodyAfterRule, /position:\s*fixed;/);
  assert.match(bodyAfterRule, /z-index:\s*-2;/);
  assert.match(htmlAfterRule, /position:\s*fixed;/);
  assert.match(htmlAfterRule, /background-image:[\s\S]*linear-gradient\([\s\S]*feTurbulence/);
});

test("homepage uses an ordered responsive four-card grid", () => {
  const cardSources = [
    "./assets/github-stats-card.svg",
    "./assets/huggingface-card.svg",
    "assets/vlog-card.svg",
    "assets/blog-card.svg",
  ];
  let position = -1;
  for (const source of cardSources) {
    const next = indexHtml.indexOf(`src="${source}"`);
    assert.ok(next > position, `${source} is not in the required order`);
    position = next;
  }
  assert.match(indexHtml, /href="https:\/\/huggingface\.co\/ceilf6"/);
  assert.match(getCssRule(".readme-cards"), /display:\s*grid;/);
  assert.match(
    getCssRule(".readme-cards"),
    /grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(getCssRule(".readme-card"), /width:\s*100%;/);
  assert.match(
    indexStyles,
    /@media \(max-width: 900px\) \{[\s\S]*?\.readme-cards\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(
    indexStyles,
    /@media \(max-width: 640px\) \{[\s\S]*?\.readme-cards\s*\{[\s\S]*?grid-template-columns:\s*1fr;/,
  );
  assert.equal(runIndexScript().readmeCards.length, 4);
});

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

test("README cards use the shared loading state before their images load", () => {
  const { readmeCards } = runIndexScript();
  const card = readmeCards[0];
  const image = card.querySelector("img");

  assert.ok(card.classList.contains("is-loading"));
  assert.ok(!card.classList.contains("is-loaded"));
  assert.equal(image.style.opacity, "0");

  image.complete = true;
  image.naturalWidth = 340;
  image.dispatchEventType("load");

  assert.ok(!card.classList.contains("is-loading"));
  assert.ok(card.classList.contains("is-loaded"));
  assert.equal(image.style.opacity, "1");
});

test("README cards show an error loading state without exposing broken images", () => {
  const { readmeCards } = runIndexScript();
  const card = readmeCards[0];
  const image = card.querySelector("img");
  const loader = card.querySelector(".readme-card-loader");

  image.dispatchEventType("error");

  assert.ok(!card.classList.contains("is-loading"));
  assert.ok(card.classList.contains("is-error"));
  assert.equal(image.style.opacity, "0");
  assert.equal(loader.textContent, "加载失败");
});
