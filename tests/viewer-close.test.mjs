import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const viewerHtml = readFileSync(new URL("../viewer.html", import.meta.url), "utf8");
const inlineScripts = [...viewerHtml.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(
  (match) => match[1],
);

function createElement() {
  const listeners = new Map();

  return {
    alt: "",
    src: "",
    style: {},
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    dispatchEventType(type, event = {}) {
      const listener = listeners.get(type);
      assert.ok(listener, `expected ${type} listener to be registered`);
      listener(event);
    },
  };
}

function createLocation(initialUrl) {
  let current = new URL(initialUrl);

  return {
    get href() {
      return current.href;
    },
    set href(value) {
      current = new URL(value, current.href);
    },
    get origin() {
      return current.origin;
    },
    get search() {
      return current.search;
    },
  };
}

function loadViewer({ opener = null } = {}) {
  assert.equal(inlineScripts.length, 1, "viewer.html should have one inline script");

  const elements = {
    "viewer-img": createElement(),
    error: createElement(),
    viewer: createElement(),
    prevBtn: createElement(),
    nextBtn: createElement(),
  };
  const documentListeners = new Map();
  const timers = [];
  const location = createLocation(
    "https://ceilf6.github.io/ceilf6/viewer.html?img=5",
  );
  const window = {
    closed: false,
    closeCalls: 0,
    location,
    opener,
    close() {
      this.closeCalls += 1;
    },
    setTimeout(listener) {
      timers.push(listener);
    },
  };
  const history = {
    replaceState(_state, _title, url) {
      window.location.href = url;
    },
  };
  const document = {
    title: "",
    addEventListener(type, listener) {
      documentListeners.set(type, listener);
    },
    getElementById(id) {
      assert.ok(elements[id], `unexpected element lookup: ${id}`);
      return elements[id];
    },
  };
  const context = {
    URLSearchParams,
    document,
    history,
    images: Array.from({ length: 8 }, (_, index) => ({
      alt: `award-${index}`,
      src: `award-${index}.jpg`,
    })),
    setTimeout: window.setTimeout.bind(window),
    window,
  };

  vm.runInNewContext(inlineScripts[0], context);

  return { documentListeners, elements, timers, window };
}

test("clicking the award image from a direct README link returns to the site home", () => {
  const { elements, window } = loadViewer();

  elements["viewer-img"].dispatchEventType("click");

  assert.equal(window.location.href, "https://ceilf6.github.io/ceilf6/");
});

test("Escape from a direct README link returns to the site home", () => {
  const { documentListeners, window } = loadViewer();

  documentListeners.get("keydown")({ key: "Escape" });

  assert.equal(window.location.href, "https://ceilf6.github.io/ceilf6/");
});

test("script-opened viewer windows still try to close before falling back home", () => {
  const { elements, timers, window } = loadViewer({
    opener: {
      closed: false,
      location: {
        origin: "https://ceilf6.github.io",
      },
    },
  });

  elements["viewer-img"].dispatchEventType("click");
  assert.equal(window.closeCalls, 1);
  assert.equal(window.location.href, "https://ceilf6.github.io/ceilf6/viewer.html?img=5");

  timers.forEach((listener) => listener());

  assert.equal(window.location.href, "https://ceilf6.github.io/ceilf6/");
});

test("cross-origin opener windows return home instead of closing back to the opener", () => {
  const { elements, window } = loadViewer({
    opener: {
      closed: false,
      location: {
        origin: "https://github.com",
      },
    },
  });

  elements["viewer-img"].dispatchEventType("click");

  assert.equal(window.closeCalls, 0);
  assert.equal(window.location.href, "https://ceilf6.github.io/ceilf6/");
});
