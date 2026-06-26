// Minimal ESLint flat config for the vendored same-origin JS files in
// packages/server/src/claudeplans/assets/js/.  No framework plugins needed --
// these are plain ES5-style IIFEs that run in-browser without a bundler.
"use strict";

module.exports = [
  {
    // Config file itself is CommonJS (Node) -- ignore it from the browser rules.
    files: ["eslint.config.cjs"],
    rules: {},
    languageOptions: {
      sourceType: "commonjs",
      globals: {
        module: "writable",
        require: "readonly",
        __dirname: "readonly",
        __filename: "readonly",
        exports: "writable",
      },
    },
  },
  {
    files: ["**/*.js", "**/*.mjs"],
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error",
    },
    languageOptions: {
      ecmaVersion: 2019,
      sourceType: "script",
      globals: {
        window: "readonly",
        document: "readonly",
        localStorage: "readonly",
        fetch: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        encodeURIComponent: "readonly",
        console: "readonly",
      },
    },
  },
];
