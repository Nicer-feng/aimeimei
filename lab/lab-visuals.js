export const colors = {
  wire: "#ad9cdd",
  quiet: "#b8a9d0",
  ink: "#f7edff",
  pink: "#f0a0eb",
  mint: "#a7f3cb",
  line: "#54426c",
  panel: "#221630",
};

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function label(x, y, text, options = {}) {
  const { size = 18, color = colors.ink, anchor = "middle", mono = false, weight = 500 } = options;
  const font = mono ? "ui-monospace, SFMono-Regular, Menlo, monospace" : "inherit";
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" fill="${color}" font-family="${font}"
    font-size="${size}" font-weight="${weight}">${escapeXml(text)}</text>`;
}

export function stroke(path, color = colors.wire, width = 2.5, dashed = false) {
  return `<path d="${path}" fill="none" stroke="${color}" stroke-width="${width}"
    stroke-linecap="round" stroke-linejoin="round"${dashed ? ' stroke-dasharray="4 5"' : ""}/>`;
}

export function point(x, y, radius, color) {
  return `<circle cx="${x}" cy="${y}" r="${radius}" fill="${color}"/>`;
}

export function canvas(prefix, description, content) {
  return `<svg viewBox="20 0 480 208" width="480" height="208" role="img" aria-label="${escapeXml(description)}">
    <defs>
      <radialGradient id="${prefix}-glow">
        <stop stop-color="#f8acff" stop-opacity=".55"/><stop offset="1" stop-color="#f8acff" stop-opacity="0"/>
      </radialGradient>
    </defs>
    ${content}
  </svg>`;
}

function ticks([min, max]) {
  return [min, (min + max) / 2, max];
}

function tickLabel(value) {
  if (value && Math.abs(value) < 0.01) return value.toExponential(1);
  return Number(value.toPrecision(3)).toString();
}

function project([low, high], start, end) {
  return (value) => start + (value - low) / (high - low) * (end - start);
}

function drawSeries(trace, projectX, projectY, color) {
  const coords = trace.points.map(([x, y]) => [projectX(x).toFixed(2), projectY(y).toFixed(2)]);
  if (trace.mode === "points") {
    return coords.map(([x, y]) => point(x, y, 3.6, color)).join("");
  }
  const path = coords.map(([x, y], index) => {
    if (index === 0) return `M${x} ${y}`;
    if (trace.mode === "step") return `H${x} V${y}`;
    return `L${x} ${y}`;
  }).join(" ");
  return stroke(path, color, 2.35, trace.dashed);
}

const seriesColors = [colors.mint, colors.pink, colors.wire];

export function plot({ prefix, description, xLabel, yLabel, x, y, series, markers = [], yTicks = ticks(y) }) {
  const left = 87;
  const right = 477;
  const top = 41;
  const bottom = 159;
  const projectX = project(x, left, right);
  const projectY = project(y, bottom, top);

  const xAxis = ticks(x).map((value) => {
    const position = projectX(value);
    return stroke(`M${position} ${bottom} v5`, colors.wire, 1.2)
      + label(position, 181, tickLabel(value), { size: 15, mono: true, color: colors.quiet });
  }).join("");
  const yAxis = yTicks.map((value) => {
    const position = projectY(value);
    return stroke(`M${left} ${position} H${right}`, colors.line, 1.2, true)
      + label(left - 10, position + 5, tickLabel(value), { anchor: "end", size: 15, mono: true, color: colors.quiet });
  }).join("");

  const traces = series.map((trace, index) => ({
    ...trace,
    color: trace.color ?? seriesColors[index % seriesColors.length],
  }));
  const graph = traces.map((trace) => drawSeries(trace, projectX, projectY, trace.color)).join("");
  const plottedMarkers = markers.map(({ x, y, label: caption, color = colors.pink }) => {
    const cx = projectX(x);
    const cy = projectY(y);
    const nearRight = cx > 350;
    const anchor = nearRight ? "end" : "start";
    const text = caption
      ? label(cx + (nearRight ? -8 : 8), cy + (cy < top + 20 ? 21 : -8), caption, { anchor, size: 15, color })
      : "";
    return point(cx, cy, 4.8, color) + text;
  }).join("");

  const namedTraces = traces.filter((trace) => trace.label);
  const legend = namedTraces.map((trace, index) => {
    const start = right - (namedTraces.length - index) * 105;
    const sample = trace.mode === "points"
      ? point(start + 8, 20, 3.2, trace.color)
      : stroke(`M${start} 20 h15`, trace.color, 2, trace.dashed);
    return sample + label(start + 21, 25, trace.label, { anchor: "start", size: 15, color: colors.quiet });
  }).join("");

  return canvas(prefix, description, `
    <defs><clipPath id="${prefix}-plot"><rect x="${left - 1}" y="${top - 1}" width="${right - left + 2}" height="${bottom - top + 2}"/></clipPath></defs>
    ${yAxis}${xAxis}${stroke(`M${left} ${top} V${bottom} H${right}`, colors.wire, 1.5)}
    ${label(43, 25, yLabel, { anchor: "start", color: colors.quiet, size: 15 })}
    ${label(right, 201, xLabel, { anchor: "end", color: colors.quiet, size: 15 })}
    ${legend}
    <g clip-path="url(#${prefix}-plot)">${graph}</g>
    ${plottedMarkers}
  `);
}

export function schematic({ prefix, description, nodes }) {
  const panelLeft = 37;
  const rowWidth = 446;
  const gap = nodes.length > 2 ? 22 : 36;
  const boxWidth = (rowWidth - gap * (nodes.length - 1)) / nodes.length;
  const content = nodes.map(({ label: heading, value, color = colors.mint }, index) => {
    const x = panelLeft + index * (boxWidth + gap);
    const middle = x + boxWidth / 2;
    const arrow = index > 0
      ? stroke(`M${x - gap + 3} 104 H${x - 4} m-5 -4 l5 4 -5 4`, colors.wire, 1.6)
      : "";
    return `${arrow}<rect x="${x}" y="59" width="${boxWidth}" height="90" rx="11" fill="${colors.panel}" stroke="${colors.line}" stroke-width="1.6"/>
      ${label(middle, 91, heading, { color: colors.quiet, size: 16 })}
      ${label(middle, 121, value, { color, size: nodes.length > 3 ? 17 : 20, weight: 650 })}`;
  }).join("");
  return canvas(prefix, description, content);
}

export function bars({ prefix, description, items, max }) {
  const height = 16;
  const step = Math.min(47, 156 / items.length);
  const start = 104 - (items.length - 1) * step / 2;
  const barWidth = 243;
  const content = items.map(({ label: heading, value, display, color }, index) => {
    const cy = start + step * index;
    const filled = barWidth * Math.max(0, Math.min(value / max, 1));
    const fill = color ?? seriesColors[index % seriesColors.length];
    return `${label(42, cy + 6, heading, { anchor: "start", color: colors.quiet, size: 16 })}
      <rect x="142" y="${cy - height / 2}" width="${barWidth}" height="${height}" rx="6" fill="${colors.line}"/>
      <rect x="142" y="${cy - height / 2}" width="${filled}" height="${height}" rx="6" fill="${fill}"/>
      ${label(478, cy + 6, display ?? value, { anchor: "end", color: fill, size: 17, mono: true, weight: 650 })}`;
  }).join("");
  return canvas(prefix, description, content);
}
