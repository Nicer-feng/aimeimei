# 固定版本第三方依赖

- qrcode-generator 1.4.4，MIT，https://github.com/kazuhikoarase/qrcode-generator 。版权和许可链接保留在 qrcode.js 文件头。
- hash-wasm 4.12.0，MIT，https://github.com/Daninet/hash-wasm 。许可证见 hash-wasm.LICENSE。

从 npm 对应版本包原样复制；运行时不依赖 CDN。SHA256 为增量哈希；MD5 仅用于 OSS 分片传输校验，不用于密码。

- PDF.js `pdfjs-dist` 6.3.289，Apache-2.0，来自 npm `pdfjs-dist@6.3.289`（https://www.npmjs.com/package/pdfjs-dist）。本站使用 `pdfjs-6.3.289/pdf.min.mjs` 与匹配的 `pdf.worker.min.mjs`；CMaps、字体、ICC、WASM 资源及各自许可证一并保留在同目录。源码和版权见 https://github.com/mozilla/pdf.js 与 `pdfjs-6.3.289/LICENSE`。
- `pdf-lib` 1.17.1，MIT，来自 npm `pdf-lib@1.17.1`（https://www.npmjs.com/package/pdf-lib）。本站使用 `pdf-lib-1.17.1.min.js`；许可证见 `pdf-lib-1.17.1.LICENSE.md`，源码见 https://github.com/Hopding/pdf-lib。

PDF 页面整理按需加载这两项依赖，文档只经私有 OSS 和当前登录用户的浏览器，不从第三方 CDN 取库。
