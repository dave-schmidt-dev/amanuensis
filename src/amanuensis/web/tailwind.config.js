// Tailwind config for the amanuensis local web app.
//
// `content` scans templates so unused utilities are tree-shaken.
// Re-run `python -m amanuensis.web.build_css` after editing templates.
module.exports = {
  content: ['./src/amanuensis/web/templates/**/*.html'],
  theme: { extend: {} },
  plugins: [],
};
