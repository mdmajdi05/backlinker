# Backend sidecar binaries

Tauri bundles the backend sidecar from this directory. The file name must
contain the target triple of the machine that builds the bundle:

```
autobacklinker-api-aarch64-apple-darwin     # macOS (Apple Silicon)
autobacklinker-api-x86_64-apple-darwin      # macOS (Intel)
autobacklinker-api-x86_64-unknown-linux-gnu # Linux
autobacklinker-api-x86_64-pc-windows-msvc.exe  # Windows
```

Build it with:

```bash
cd ../..
npm run sidecar                                        # macOS / Linux
powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1   # Windows
```

The scripts place the artefact in this directory. `tauri build` fails with
*"external binary ... not found"* when the file for the current target triple
is missing.

The binaries are **not** committed to the repository - they are build
artefacts that contain the whole Python runtime.
