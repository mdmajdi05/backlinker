# Release artifacts

Built on macOS 26.6 (x86_64) from this repository.

| Artifact | Size | What it is |
| -------- | ---- | ---------- |
| `macos/Auto Backlinker_1.0.0_x64.dmg` | 71 MB | Installable disk image (drag & drop into /Applications) |
| `macos/Auto Backlinker.app` | 75 MB | The native macOS application bundle |
| `macos/autobacklinker-api-x86_64-apple-darwin` | 69 MB | The backend sidecar (also embedded in the .app, Playwright package included) |

Rebuild with:

```bash
cd apps/desktop
npm run sidecar            # backend sidecar (PyInstaller)
npm run tauri:build        # native bundle -> target/release/bundle/macos
bash scripts/build-dmg.sh  # disk image (headless friendly)
```

The artifacts are **unsigned**. A distributable build needs an Apple
Developer ID certificate and notarization; see `apps/desktop/README.md`.
