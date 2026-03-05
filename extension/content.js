(() => {
if (window.__BROWSER_BRIDGE_CONTENT_LOADED__) {
  return;
}
window.__BROWSER_BRIDGE_CONTENT_LOADED__ = true;

const INTERACTIVE_SELECTORS = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "[role='button']",
  "[contenteditable='true']"
].join(",");

const DEFAULT_KEYSTROKE_DELAY_MS = 45;
const DEFAULT_KEYSTROKE_JITTER_MS = 30;
const MAX_KEYSTROKE_DELAY_MS = 1000;
const MAX_KEYSTROKE_JITTER_MS = 500;

function isVisible(el) {
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
}

function toText(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function cssAttr(name, value) {
  return `[${name}="${CSS.escape(String(value))}"]`;
}

function isUniqueSelector(selector) {
  try {
    return document.querySelectorAll(selector).length === 1;
  } catch {
    return false;
  }
}

function nthOfTypeSelector(el) {
  const parts = [];
  let node = el;
  while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
    const tag = node.tagName.toLowerCase();
    let index = 1;
    let sibling = node;
    while ((sibling = sibling.previousElementSibling)) {
      if (sibling.tagName === node.tagName) {
        index += 1;
      }
    }
    parts.unshift(`${tag}:nth-of-type(${index})`);
    node = node.parentElement;
  }
  return `html > ${parts.join(" > ")}`;
}

function selectorCandidates(el) {
  const out = [];
  if (el.id) {
    out.push(`#${CSS.escape(el.id)}`);
  }
  const dataTestId = el.getAttribute("data-testid") || el.getAttribute("data-test-id");
  if (dataTestId) {
    out.push(cssAttr("data-testid", dataTestId));
    out.push(cssAttr("data-test-id", dataTestId));
  }
  const name = el.getAttribute("name");
  if (name) {
    out.push(`${el.tagName.toLowerCase()}${cssAttr("name", name)}`);
  }
  const aria = el.getAttribute("aria-label");
  if (aria) {
    out.push(`${el.tagName.toLowerCase()}${cssAttr("aria-label", aria)}`);
  }
  const placeholder = el.getAttribute("placeholder");
  if (placeholder) {
    out.push(`${el.tagName.toLowerCase()}${cssAttr("placeholder", placeholder)}`);
  }
  const href = el.getAttribute("href");
  if (href && href.length < 200) {
    out.push(`${el.tagName.toLowerCase()}${cssAttr("href", href)}`);
  }
  return out.filter(Boolean);
}

function bestSelector(el) {
  const candidates = selectorCandidates(el);
  for (const selector of candidates) {
    if (isUniqueSelector(selector)) {
      return { selector, candidates };
    }
  }

  // Fallback to deterministic DOM-path selector.
  const fallback = nthOfTypeSelector(el);
  return { selector: fallback, candidates: [...candidates, fallback] };
}

function elementLocator(el) {
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute("role") || null,
    id: el.id || null,
    name: el.getAttribute("name") || null,
    aria_label: el.getAttribute("aria-label") || null,
    placeholder: el.getAttribute("placeholder") || null,
    data_testid: el.getAttribute("data-testid") || el.getAttribute("data-test-id") || null,
    text: toText(el.innerText || el.textContent || "")
  };
}

function observe(payload) {
  const maxNodes = Number(payload?.max_nodes || 150);
  const candidates = Array.from(document.querySelectorAll(INTERACTIVE_SELECTORS));
  const nodes = [];
  for (const el of candidates) {
    if (!isVisible(el)) {
      continue;
    }
    const rect = el.getBoundingClientRect();
    const selectorInfo = bestSelector(el);
    nodes.push({
      locator: elementLocator(el),
      selector: selectorInfo.selector,
      selector_candidates: selectorInfo.candidates.slice(0, 6),
      bounds: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) }
    });
    if (nodes.length >= maxNodes) {
      break;
    }
  }

  return {
    url: window.location.href,
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight, scroll_y: Math.round(window.scrollY) },
    interactive_nodes: nodes
  };
}

function resolveByLocator(locator) {
  const normalizedText = toText(locator?.text).toLowerCase();
  const normalizedRole = toText(locator?.role).toLowerCase();
  const normalizedTag = toText(locator?.tag).toLowerCase();
  const normalizedName = toText(locator?.name).toLowerCase();
  const normalizedPlaceholder = toText(locator?.placeholder).toLowerCase();
  const normalizedAria = toText(locator?.aria_label).toLowerCase();
  const normalizedTestId = toText(locator?.data_testid).toLowerCase();
  const normalizedId = toText(locator?.id).toLowerCase();
  const desiredIndex = Number(locator?.index ?? 0);

  const all = Array.from(document.querySelectorAll(INTERACTIVE_SELECTORS)).filter(isVisible);
  const matches = all.filter((el) => {
    if (normalizedTag && el.tagName.toLowerCase() !== normalizedTag) {
      return false;
    }
    if (normalizedRole && toText(el.getAttribute("role")).toLowerCase() !== normalizedRole) {
      return false;
    }
    if (normalizedName && toText(el.getAttribute("name")).toLowerCase() !== normalizedName) {
      return false;
    }
    if (normalizedPlaceholder && toText(el.getAttribute("placeholder")).toLowerCase() !== normalizedPlaceholder) {
      return false;
    }
    if (normalizedAria && toText(el.getAttribute("aria-label")).toLowerCase() !== normalizedAria) {
      return false;
    }
    if (normalizedTestId) {
      const testId = toText(el.getAttribute("data-testid") || el.getAttribute("data-test-id")).toLowerCase();
      if (testId !== normalizedTestId) {
        return false;
      }
    }
    if (normalizedId && toText(el.id).toLowerCase() !== normalizedId) {
      return false;
    }
    if (normalizedText) {
      const elText = toText(el.innerText || el.textContent || "").toLowerCase();
      if (!elText.includes(normalizedText)) {
        return false;
      }
    }
    return true;
  });

  if (!matches.length) {
    return null;
  }
  return matches[Math.max(0, Math.min(desiredIndex, matches.length - 1))];
}

function resolveElement(payload) {
  const selector = toText(payload?.selector);
  if (selector) {
    const selected = document.querySelector(selector);
    if (selected) {
      return { element: selected, resolvedBy: "selector", selector };
    }
  }

  const locator = payload?.locator;
  if (locator && typeof locator === "object") {
    const located = resolveByLocator(locator);
    if (located) {
      const selectorInfo = bestSelector(located);
      return { element: located, resolvedBy: "locator", selector: selectorInfo.selector };
    }
  }

  throw new Error("element not found (selector and locator failed)");
}

async function clickSelector(payload) {
  const resolved = resolveElement(payload);
  resolved.element.click();
  return { clicked: true, selector: resolved.selector, resolved_by: resolved.resolvedBy };
}

function boundedNumber(value, fallback, min, max) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, Math.round(num)));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseTypingConfig(payload) {
  return {
    humanLike: payload?.human_like !== false,
    clearFirst: payload?.clear_first !== false,
    delayMs: boundedNumber(payload?.keystroke_delay_ms, DEFAULT_KEYSTROKE_DELAY_MS, 0, MAX_KEYSTROKE_DELAY_MS),
    jitterMs: boundedNumber(payload?.keystroke_jitter_ms, DEFAULT_KEYSTROKE_JITTER_MS, 0, MAX_KEYSTROKE_JITTER_MS)
  };
}

function isValueInput(el) {
  return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
}

function isEditable(el) {
  return isValueInput(el) || el.isContentEditable;
}

function dispatchKeyEvent(el, type, key) {
  el.dispatchEvent(
    new KeyboardEvent(type, {
      key,
      bubbles: true,
      cancelable: true,
      composed: true
    })
  );
}

function dispatchInput(el, data, inputType = "insertText") {
  try {
    el.dispatchEvent(
      new InputEvent("input", {
        bubbles: true,
        cancelable: false,
        composed: true,
        data,
        inputType
      })
    );
  } catch {
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

function insertIntoValueElement(el, text, clearFirst) {
  const start = Number.isInteger(el.selectionStart) ? el.selectionStart : el.value.length;
  const end = Number.isInteger(el.selectionEnd) ? el.selectionEnd : start;
  if (clearFirst) {
    if (typeof el.setRangeText === "function") {
      el.setRangeText(text, 0, el.value.length, "end");
      return;
    }
    el.value = text;
    return;
  }
  if (typeof el.setRangeText === "function") {
    el.setRangeText(text, start, end, "end");
    return;
  }
  el.value = `${el.value.slice(0, start)}${text}${el.value.slice(end)}`;
}

function placeCaretAtEnd(el) {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function insertIntoContentEditable(el, text, clearFirst) {
  if (clearFirst) {
    el.textContent = "";
    placeCaretAtEnd(el);
  }

  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  if (!selection.rangeCount) {
    placeCaretAtEnd(el);
  }
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.setEndAfter(node);
  selection.removeAllRanges();
  selection.addRange(range);
}

async function typeHumanLike(el, text, config) {
  if (isValueInput(el)) {
    if (config.clearFirst) {
      insertIntoValueElement(el, "", true);
      dispatchInput(el, "", "deleteContentBackward");
    }
    for (const ch of text) {
      dispatchKeyEvent(el, "keydown", ch);
      dispatchKeyEvent(el, "keypress", ch);
      insertIntoValueElement(el, ch, false);
      dispatchInput(el, ch, "insertText");
      dispatchKeyEvent(el, "keyup", ch);
      const randomJitter = config.jitterMs > 0 ? Math.floor(Math.random() * (config.jitterMs + 1)) : 0;
      await sleep(config.delayMs + randomJitter);
    }
    return;
  }

  if (el.isContentEditable) {
    if (config.clearFirst) {
      insertIntoContentEditable(el, "", true);
      dispatchInput(el, "", "deleteContentBackward");
    } else {
      placeCaretAtEnd(el);
    }
    for (const ch of text) {
      dispatchKeyEvent(el, "keydown", ch);
      dispatchKeyEvent(el, "keypress", ch);
      insertIntoContentEditable(el, ch, false);
      dispatchInput(el, ch, "insertText");
      dispatchKeyEvent(el, "keyup", ch);
      const randomJitter = config.jitterMs > 0 ? Math.floor(Math.random() * (config.jitterMs + 1)) : 0;
      await sleep(config.delayMs + randomJitter);
    }
  }
}

async function typeSelector(payload) {
  const text = String(payload?.text ?? "");
  const resolved = resolveElement(payload);
  const el = resolved.element;
  const config = parseTypingConfig(payload);
  const startedAt = Date.now();

  if (!isEditable(el)) {
    throw new Error("target element is not text-editable");
  }

  el.focus();
  if (config.humanLike) {
    await typeHumanLike(el, text, config);
  } else if (isValueInput(el)) {
    insertIntoValueElement(el, text, config.clearFirst);
    dispatchInput(el, text, "insertText");
  } else {
    insertIntoContentEditable(el, text, config.clearFirst);
    dispatchInput(el, text, "insertText");
  }
  el.dispatchEvent(new Event("change", { bubbles: true }));

  return {
    typed: true,
    selector: resolved.selector,
    resolved_by: resolved.resolvedBy,
    length: text.length,
    human_like_used: config.humanLike,
    clear_first: config.clearFirst,
    keystroke_delay_ms: config.delayMs,
    keystroke_jitter_ms: config.jitterMs,
    elapsed_ms: Date.now() - startedAt
  };
}

async function scrollByAmount(payload) {
  const dx = Number(payload?.dx || 0);
  const dy = Number(payload?.dy || 0);
  window.scrollBy(dx, dy);
  return { scrolled: true, dx, dy, scroll_y: Math.round(window.scrollY) };
}

function preprocessHtmlDom() {
  const clone = document.documentElement.cloneNode(true);
  const removableSelector = "script,style,noscript,template,svg,canvas";
  let removedNodes = 0;

  clone.querySelectorAll(removableSelector).forEach((node) => {
    removedNodes += 1;
    node.remove();
  });

  clone.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (attr.name === "style" || attr.name.startsWith("on")) {
        el.removeAttribute(attr.name);
      }
    }
  });

  const html = `<!doctype html>\n${clone.outerHTML}`
    .replace(/<!--([\s\S]*?)-->/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  return { html, removed_nodes: removedNodes };
}

async function getHtml(payload) {
  const maxChars = Number(payload?.max_chars || 150000);
  const preprocess = payload?.preprocess !== false;
  const notes = [];

  let html;
  let removedNodes = 0;

  if (preprocess) {
    const processed = preprocessHtmlDom();
    html = processed.html;
    removedNodes = processed.removed_nodes;
  } else {
    html = document.documentElement.outerHTML;
  }
  const truncated = html.length > maxChars;

  if (truncated) {
    notes.push(
      `HTML was truncated to ${maxChars} characters. Re-run get_html with a higher payload.max_chars to capture more content.`
    );
  }
  if (preprocess) {
    notes.push("Preprocessing is enabled. For rawer DOM output, re-run get_html with payload.preprocess=false.");
  } else {
    notes.push("Raw DOM mode is enabled (preprocess=false). Output may include scripts/styles and inline handlers.");
  }

  return {
    url: window.location.href,
    title: document.title,
    preprocess,
    removed_nodes: removedNodes,
    truncated,
    notes,
    html: html.slice(0, maxChars)
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const run = async () => {
    const type = message?.type;
    const payload = message?.payload || {};

    switch (type) {
      case "ping":
        return { ready: true, url: window.location.href, title: document.title };
      case "observe":
        return observe(payload);
      case "click":
        return clickSelector(payload);
      case "type":
        return typeSelector(payload);
      case "scroll":
        return scrollByAmount(payload);
      case "get_html":
        return getHtml(payload);
      default:
        throw new Error(`Unsupported content command: ${type}`);
    }
  };

  run()
    .then((result) => sendResponse({ ok: true, result }))
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));

  return true;
});
})();
