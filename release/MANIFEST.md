# Release artifacts

Built on macOS from this repository.

| Artifact | Size | What it is |
| -------- | ---- | ---------- |
| `macos/Auto Backlinker_1.0.0_universal.dmg` | 160 MB | The disk image to share - **runs on Intel and Apple Silicon** |
| `macos/Auto Backlinker.app` | 317 MB | The application bundle (same content as the DMG) |
| `HOW-TO-USE.md` | - | The guide for the people you share it with |

The application contains **everything**: the user interface, the FastAPI
backend, the SQLite database handling, the background worker and the browser
automation engine - for both macOS architectures.  The user never installs
Python, Node.js, PostgreSQL or Redis and never starts a server manually.

Rebuild with:

```bash
cd apps/desktop
npm run backend                                  # bundle the backend for both architectures
npm run tauri:build -- --target universal-apple-darwin
bash scripts/build-dmg.sh --app \
  src-tauri/target/universal-apple-darwin/release/bundle/macos/"Auto Backlinker.app" \
  --output src-tauri/target/universal-apple-darwin/release/bundle/dmg/Auto\ Backlinker_1.0.0_universal.dmg
```

The artifacts are **unsigned**.  A distributable build needs an Apple
Developer ID certificate and notarization; see `apps/desktop/README.md`.
