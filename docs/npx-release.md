Run YuBen with one command on macOS, Windows or Linux (Node.js required):

```bash
npx https://github.com/shkuratovdesigner/yuben-app/releases/latest/download/yuben-app.tgz
```

The first run provisions Python automatically, installs locked dependencies and opens YuBen in your browser. The interface is prebuilt. Later launches reuse the runtime. History and keys stay in a persistent user data folder outside npm's cache.

Existing source users can set `YUBEN_DATA_DIR` to their checkout's `backend/.yuben` directory to keep using their saved history. See the README for platform paths and options.

The short `npx yuben-app@latest` alias requires the separate first publication to npm; this release's URL works without npm publishing credentials.
