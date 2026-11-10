// Quote tile, a small community example. Off until "quote" is listed in
// enabled_community_tiles in config.json.
DeskboardTiles.register("quote", {
  render(data, h) {
    let out = '<blockquote class="fit-text quote-body">';
    out += '<p class="quote-text">' + h.escape(data.quote) + "</p>";
    if (data.author) out += '<p class="quote-author">' + h.escape(data.author) + "</p>";
    return out + "</blockquote>";
  },
});
