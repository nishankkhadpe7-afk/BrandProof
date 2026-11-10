// BrandProof Figma plugin: main thread. Reads text layers, exports frames, focuses layers and applies fixes.
// Network calls happen in ui.html (the iframe); this file only talks to the Figma document.
figma.showUI(__html__, { width: 380, height: 640, themeColors: true });

function textNodes(nodes) {
  const out = [];
  const walk = (n) => {
    if (n.visible === false) return;
    if (n.type === "TEXT") out.push({ id: n.id, name: n.name, text: n.characters });
    else if ("children" in n) n.children.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

function selectionInfo() {
  const sel = figma.currentPage.selection;
  return {
    type: "selection",
    count: sel.length,
    nodes: textNodes(sel),
    title: sel.length === 1 ? sel[0].name : sel.length + " layers on " + figma.currentPage.name,
    file: figma.root.name,
    canExport: sel.some((n) => "exportAsync" in n),
  };
}

figma.on("selectionchange", () => figma.ui.postMessage(selectionInfo()));

figma.ui.onmessage = async (msg) => {
  try {
    if (msg.type === "init") {
      const settings = (await figma.clientStorage.getAsync("brandproof")) || {};
      figma.ui.postMessage({ type: "init", settings });
      figma.ui.postMessage(selectionInfo());
    } else if (msg.type === "save-settings") {
      await figma.clientStorage.setAsync("brandproof", msg.settings);
    } else if (msg.type === "export") {
      const target = figma.currentPage.selection.find((n) => "exportAsync" in n);
      let b64 = null;
      if (target) {
        const big = Math.max(target.width || 0, target.height || 0);
        const scale = big > 2000 ? 2000 / big : 1;
        b64 = figma.base64Encode(await target.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: scale } }));
      }
      figma.ui.postMessage({ type: "export", b64 });
    } else if (msg.type === "focus") {
      const n = await figma.getNodeByIdAsync(msg.id);
      if (!n) throw new Error("That layer no longer exists.");
      figma.currentPage.selection = [n];
      figma.viewport.scrollAndZoomIntoView([n]);
    } else if (msg.type === "apply") {
      const n = await figma.getNodeByIdAsync(msg.id);
      if (!n || n.type !== "TEXT") throw new Error("That text layer no longer exists.");
      if (n.characters.slice(msg.start, msg.end) !== msg.expect) throw new Error("The text changed since the check. Run the check again.");
      if (n.hasMissingFont) throw new Error("This layer uses a font that isn't installed, so it can't be edited.");
      for (const f of n.getRangeAllFontNames(0, n.characters.length)) await figma.loadFontAsync(f);
      n.insertCharacters(msg.end, msg.text, "BEFORE"); // keep the styling of the replaced text
      n.deleteCharacters(msg.start, msg.end);
      figma.ui.postMessage({ type: "applied", key: msg.key });
      figma.notify("Fix applied");
    } else if (msg.type === "open") {
      figma.openExternal(msg.url);
    } else if (msg.type === "notify") {
      figma.notify(msg.text, { error: !!msg.error });
    }
  } catch (e) {
    figma.ui.postMessage({ type: "error", key: msg.key, message: String((e && e.message) || e) });
  }
};
