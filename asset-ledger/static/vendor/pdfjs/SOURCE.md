# Mozilla PDF.js 6.5.438

From the official `pdfjs-dist` npm archive for the [Mozilla release](https://github.com/mozilla/pdf.js/releases/tag/v6.5.438). Bundled files are unmodified.

- [Registry metadata](https://registry.npmjs.org/pdfjs-dist/6.5.438)
- [Package archive](https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.5.438.tgz)
- Archive SHA-256 `7461aefcd27c4ef0dd76f9ca5760f09466eb6b3f934432670c12132e7b3d6faa`
- Archive npm integrity `sha512-vg8Pw1x+AFKy4AMDvhuWl5cOYV8d698UoEANoFFhc79hqXDnZQqnOXoxw3HG907WHOg1JYOvLhP756boddFxpA==`
- `pdf.min.mjs` from `legacy/build/`, SHA-256 `522ad2c83bc8a0010e7f0cc60d0892b77c8d2bf2c9702dc12288311d94270f42`
- `pdf.worker.min.mjs` from `legacy/build/`, SHA-256 `b4c8353ded0d88d2e2009574a29eb4e0c3ff7e942ecdf51ef5f71566a9667f31`
- The package's CMaps and standard fonts are supplied with their license files. See also the top-level Apache-2.0 license.
- The JavaScript-only image decoders and their licenses are from `wasm/` in the package. `jbig2_nowasm_fallback.js` has SHA-256 `70150223396487e1ccfef7eac61fc780074ad7fcc9e843b702a8a3bc23107494`. `openjpeg_nowasm_fallback.js` has SHA-256 `2855f4590e7fd7abbbf204cd13a5c09d30c92fe2c9313fb72b64aa763fe8b4f3`.

The two `.mjs.gz` files are locally compressed copies for HTTP delivery. The original modules are supplied for clients that do not accept gzip. After updating PDF.js, update the version in `static/pdf-preview.js` and `ledger/http.py`, then regenerate both copies from this directory.

```sh
for module in pdf.min.mjs pdf.worker.min.mjs; do
    gzip -n -9 -c "$module" > "$module.gz"
done
```
