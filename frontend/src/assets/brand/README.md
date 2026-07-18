# Brand assets

Exported from Figma `OG4eN9FgW3gnu88CRQRMGt` (YouTube research Agent) via the
Figma MCP. Re-export with `download_assets` if the design changes.

| File | Figma node | Notes |
|---|---|---|
| `logo-yuben.svg` | `55:3156` | Full lockup (play-mark `#00809C` + "YuBen" wordmark). Clean vector; slice background stripped. |
| `logo-mark.svg` | `55:3156` (Polygon 1) | Play-mark only, fitted viewBox — for the top-bar chrome + live "YuBen" text. |
The logo is true vector.

## Adapter marks live in code, not here

`adapter-claude.png` and `adapter-gemini.png` used to sit in this folder. They
were raster image fills in Figma, so they exported as PNG — and the export
carried an opaque off-white square, invisible against the light canvas they were
drawn on and a glaring white tile in dark mode.

They are now vector components in
[`src/app/adapter-icons.tsx`](../../app/adapter-icons.tsx), one per adapter, with
monochrome marks drawn in `currentColor` so they follow the theme. Adding an
adapter means adding a component there, not exporting a bitmap here.
