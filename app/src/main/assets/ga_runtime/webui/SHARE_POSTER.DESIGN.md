---
version: alpha
name: GenericAgent Editorial Product Proof
description: A responsive proof sheet that treats the real phone session as the product. The canvas follows the current device shape while three art-directed layouts preserve hierarchy from a tall handset to a 16:10 wide foldable.
colors:
  primary: "#C4501E"
  primary-text: "#9A3B14"
  paper: "#F7F6F2"
  paper-high: "#FFFDF8"
  ink: "#121316"
  ink-soft: "#3F4147"
  muted: "#666972"
  hairline: "#D8D6CF"
  device: "#17181C"
  device-soft: "#25262B"
  on-device: "#F7F7FA"
typography:
  display:
    fontFamily: "SF Pro Display, PingFang SC, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 40px
    fontWeight: "750"
    lineHeight: 1.12
    letterSpacing: -0.025em
  display-wide:
    fontFamily: "SF Pro Display, PingFang SC, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 32px
    fontWeight: "720"
    lineHeight: 1.12
    letterSpacing: -0.022em
  brand:
    fontFamily: "SF Pro Display, PingFang SC, system-ui, sans-serif"
    fontSize: 21px
    fontWeight: "800"
    lineHeight: 1
    letterSpacing: -0.02em
  metadata:
    fontFamily: "SF Mono, Roboto Mono, ui-monospace, Menlo, Consolas, monospace"
    fontSize: 10px
    fontWeight: "500"
    lineHeight: 1.4
    letterSpacing: 0.12em
  body-strong:
    fontFamily: "SF Pro Text, PingFang SC, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: "700"
    lineHeight: 1.35
    letterSpacing: -0.01em
  caption:
    fontFamily: "SF Mono, Roboto Mono, ui-monospace, Menlo, Consolas, monospace"
    fontSize: 9.5px
    fontWeight: "500"
    lineHeight: 1.35
    letterSpacing: 0.08em
rounded:
  xs: 6px
  sm: 10px
  device-wide: 14px
  device-book: 22px
  device-phone: 34px
  qr: 10px
  full: 9999px
spacing:
  unit: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  page: 40px
components:
  poster-canvas:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    padding: "{spacing.page}"
  masthead:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.brand}"
  metadata:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.metadata}"
  accent-caption:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary-text}"
    typography: "{typography.caption}"
  muted-caption:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.muted}"
    typography: "{typography.caption}"
  hairline-rule:
    backgroundColor: "{colors.hairline}"
    textColor: "{colors.ink}"
    height: 1px
  device-frame:
    backgroundColor: "{colors.device}"
    textColor: "{colors.on-device}"
    rounded: "{rounded.device-phone}"
    padding: 10px
  device-frame-book:
    backgroundColor: "{colors.device-soft}"
    textColor: "{colors.on-device}"
    rounded: "{rounded.device-book}"
    padding: 7px
  device-frame-wide:
    backgroundColor: "{colors.device-soft}"
    textColor: "{colors.on-device}"
    rounded: "{rounded.device-wide}"
    padding: 5px
  qr-card:
    backgroundColor: "{colors.paper-high}"
    textColor: "{colors.ink}"
    rounded: "{rounded.qr}"
    padding: 6px
---

## Overview

The poster is a **museum proof sheet for a real autonomous run**: Apple-like product deference meets a WIRED-like editorial opener. The captured GA session is the artifact; branding and copy establish provenance, then get out of its way.

The canvas adopts the current device ratio, but composition is art-directed rather than stretched. A tall phone, square book foldable, and 16:10 wide foldable are three volumes of one visual language. Each has its own grid, device-shell grammar, and type scale.

The memorable gesture is the truthful device stage: a thin precision frame containing the complete real viewport, sized to **fill the hero stage** rather than to a fixed unit width. The spot ink appears only as a proof marker and a restrained text underline. There is no decorative glass, no giant halo, and no toy-like oversized bezel.

## Colors

- **Paper** `{colors.paper}` is a warm gallery sheet, never clinical white.
- **Ink** `{colors.ink}` carries headlines and hard rules.
- **Spot ink** `{colors.primary}` — a letterpress vermilion on warm paper — is graphic-only: proof dot, short marker, headline underline. The spot color itself is graphic-only at 4.3:1 on paper (above the 3:1 non-text floor); spot-colored *text* must use `{colors.primary-text}` (6.4:1 on paper, AA). It replaced iOS system green `#30D158`, which belonged to neither the poster's warm-paper palette nor the app's own monochrome ink system (`--acc:#1d1d1f`) and read as a foreign, screen-native color on a print artifact.
- **Preview chrome** (segmented control, action bar, close) is drawn from ink/paper/hairline, never from the spot color. Ink is structure; the spot color is evidence marking only.
- **Device** `{colors.device}` is a near-black precision edge, not a glossy black object.
- **Hairline** `{colors.hairline}` replaces ornamental shadows and card chrome.

## Typography

Display type is a native, tightly tracked grotesk. It is strong but not oversized: the session image remains the hero. Metadata is monospace and factual—steps, elapsed time, and unedited status only.

Wide layouts use `{typography.display-wide}` because the copy column is narrow. Headlines remain at most two lines in portrait/book layouts and three short lines in wide layouts.

## Layout

The design coordinate system is 540 units wide; height is `540 × deviceAspect`.

### Portrait profile — aspect ≥ 1.35

Use a vertical editorial stack: masthead, rule, headline, metadata, centered phone stage, footer. The device **fills the hero stage** — the largest aspect-correct rectangle that fits it (measured: 96% of stage height, ~70% of page width on a 19.5:9 handset; width tracks the screenshot aspect, so a squarer viewport yields a wider frame). Its size is derived from the leftover stage box, never from a fixed unit width: a hard cap left ~28% of the stage empty and made the session image, the poster's whole subject, read as a thumbnail.

### Book profile — 0.85 ≤ aspect < 1.35

Use a compact vertical stack with reduced top chrome. The square/book device expands to 78–84% of page width. Footer and QR remain a single calm baseline.

### Wide profile — aspect < 0.85

Use a two-column opener. The left rail contains masthead, headline, metadata, hook, URL, and QR. The right 60–64% is a wide device stage. For Huawei Pura X Max at 16:10 (`height/width = 0.625`), the screen should read as a premium landscape display, not a square phone.

Below 0.62 (tri-fold band) the wide profile switches to dense tokens: display drops to 24px, QR to 64 units, and rail chrome tightens so the left rail never overflows the sheet. Pura X Max at 0.625 keeps the flagship 28px/76-unit look.

Wide metadata is factual only — steps, elapsed time, and the automation word; the user quote stays on portrait/book where the rail affords it. Overflowing metadata elides with an ellipsis instead of clipping mid-glyph.

The canvas tracks the measured viewport ratio between 0.55 and 2.6. Only the supported hardware profile changes at thresholds; dimensions inside each profile remain fluid.

## Elevation & Depth

Everything is flat except the captured device, which receives one low-opacity, wide product shadow. Wide and book frames use less shadow than portrait frames. Hairlines create all other hierarchy.

No blur is required in the rendered poster. No decorative radial halo is allowed.

## Shapes

- Portrait frames use `{rounded.device-phone}` and a slim top sensor treatment.
- Book frames use `{rounded.device-book}` with a thinner bezel and camera dot.
- Wide frames use `{rounded.device-wide}`, the thinnest bezel, and no fake hinge or fold crease.
- Screenshot corners are always the outer frame radius minus bezel width.
- QR uses `{rounded.qr}`; no other card is independently rounded.

## Components

**Device stage:** the frame's *aspect* comes from screenshot aspect plus the synthetic status bar; its *size* comes from the stage. The screenshot must be fully visible with no crop, stretch, black band, or filler. The bezel is drawn with per-axis percentage insets on an absolutely positioned screen, not with padding: percentage *padding* resolves against the containing block's width (CSS 2.1 §8.4) — i.e. the stage, not the frame — so it drifts as the stage changes. Absolute-inset percentages resolve against the frame's own width (left/right) and height (top/bottom), keeping the inner box exactly at the screenshot aspect at any scale.

**Preview segmented control:** a paper-filled, hairline-bordered rounded rectangle (14px outer / 10px segment) with equal-width segments and a solid ink active segment. Not a full-radius pill, not dark glass, and never tinted with the spot color. Segments keep a 48px touch height.

**Masthead:** proof dot + GenericAgent + “REAL RUN · UNEDITED”. On wide layouts it lives in the left rail; on portrait/book it spans the page.

**Footer:** hook, URL, and QR. Wide mode integrates it into the left rail to avoid a compressed bottom strip.

**Preview surface:** use paper-matched neutral gutters rather than black bars when the poster does not fill the physical screen.

## Do's and Don'ts

### Do

- Do treat the screenshot as product photography.
- Do preserve the measured device ratio and switch layout profiles at explicit thresholds.
- Do keep one accent color and one product shadow.
- Do use whitespace as structure; use hairlines for hierarchy.
- Do render Pura X Max 16:10 and tri-fold ratios as intentional landscape compositions.

### Don't

- Don't reuse the portrait column unchanged for wide devices.
- Don't clamp every foldable to a square canvas.
- Don't cap the device to a fixed unit width or height; profile numbers are aspect inputs, not sizes.
- Don't draw hinges or creases without hardware metadata.
- Don't add giant rounded corners, thick black bezels, halos, glass blur, or multiple shadows.
- Don't crop the real session to make the mock frame look better.
