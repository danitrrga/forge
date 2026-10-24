// The wordmark: a grid of characters taken in order from the files forge read and wrote (whitespace removed), with
// every cell that "forge" set in Mona Sans 800 covers knocked out in ink, and a pink block cursor on the baseline
// after the e. The letters are drawn on a hidden canvas one pixel per cell, so their shape is the typeface's.
window.drawField = async function (el, o) {
  const F = window.FORGE, CW = o.cw, RH = o.rh, COLS = o.cols, ROWS = o.rows;
  const src = ["config/profiles/api.claude.json", "config/profiles/site.claude.json", "~/code/api/.claude/settings.local.json"]
    .map(k => F.files[k]).join("").replace(/\s+/g, "");
  el.style.gridTemplateColumns = "repeat(" + COLS + "," + CW + "px)";
  el.style.gridAutoRows = RH + "px";
  const lit = new Uint8Array(COLS * ROWS);
  let cur = null;
  if (o.word) {
    await document.fonts.load('800 100px "Mona Sans"');
    const cv = document.createElement("canvas"); cv.width = COLS; cv.height = ROWS;
    const g = cv.getContext("2d");
    g.scale(1, CW / RH);                       // a cell is taller than wide: squash so the letters keep their shape
    let size = 100; g.font = '800 ' + size + 'px "Mona Sans"';
    size = size * (COLS * o.width) / g.measureText("forge").width; g.font = '800 ' + size + 'px "Mona Sans"';
    const w = g.measureText("forge").width, x0 = (COLS - w) / 2 + (o.dx || 0) - 2, base = (ROWS * RH / CW) * o.baseline;
    g.fillText("forge", x0, base);
    const px = g.getImageData(0, 0, COLS, ROWS).data;
    for (let i = 0; i < COLS * ROWS; i++) lit[i] = px[i * 4 + 3] > 127 ? 1 : 0;
    cur = [Math.round(base * CW / RH) - 2, Math.round(x0 + w) + 2];
  }
  const esc = ch => ch === "&" ? "&amp;" : ch === "<" ? "&lt;" : ch;
  let i = 0, html = "";
  for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
    const ch = esc(src[i++ % src.length]);
    if (cur && r >= cur[0] && r <= cur[0] + 1 && c >= cur[1] && c <= cur[1] + 2) html += '<span class="cur">' + ch + "</span>";
    else html += lit[r * COLS + c] ? "<b>" + ch + "</b>" : "<span>" + ch + "</span>";
  }
  el.innerHTML = html;
};
