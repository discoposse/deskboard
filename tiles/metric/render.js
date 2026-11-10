// Metric tile. The reference example for the tile catalog.
// data holds the fields from tile.json plus col_span and row_span.
// h.escape turns any value into safe text for markup.
DeskboardTiles.register("metric", {
  render(data, h) {
    const t = String(data.trend || "").toLowerCase();
    const dir = t.includes("up") || t.startsWith("+") ? "up" : t.includes("down") || t.startsWith("-") ? "down" : "";
    let out = '<p class="metric-label">' + h.escape(data.label) + "</p>";
    out += '<p class="metric-value">' + h.escape(data.value) + "</p>";
    if (data.trend) out += '<p class="' + (dir ? "metric-trend " + dir : "metric-trend") + '">' + h.escape(data.trend) + "</p>";
    if (data.hint) out += '<p class="metric-hint">' + h.escape(data.hint) + "</p>";
    return out;
  },
});
