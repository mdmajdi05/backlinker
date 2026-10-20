const path = require("node:path");
const defaultResolve = require("postcss-import/lib/resolve-id");

/**
 * `postcss-import` uses the legacy `resolve` package which does not understand
 * the `exports` map of modern packages, so `@autobacklinker/ui/styles.css`
 * cannot be found. Node's own resolver handles it, therefore package
 * specifiers are resolved through `require.resolve` and everything else keeps
 * the default behaviour.
 */
function resolveImport(id, base, options, node) {
  if (id.startsWith(".") || path.isAbsolute(id)) {
    return defaultResolve(id, base, options, node);
  }
  return new Promise((resolve, reject) => {
    try {
      resolve(require.resolve(id, { paths: [base] }));
    } catch {
      reject(
        node.error(`Failed to find '${id}'`, { word: id }),
      );
    }
  });
}

module.exports = {
  plugins: {
    "postcss-import": { resolve: resolveImport },
    tailwindcss: {},
    autoprefixer: {},
  },
};
