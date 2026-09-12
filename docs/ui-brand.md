---
summary: OpenBridge GUI logo asset, usage and built-in image generation record.
type: reference
last_updated: 2026-09-12
related:
  - local-ui.md
  - ../DESIGN.md
---

# OpenBridge GUI brand

The mark uses two architectural piers and two connecting arches. Its broad
silhouette represents a bridge between local knowledge and action. The live-text
wordmark is **OpenBridge**; it remains selectable, accessible and independent of
the image. The interface uses the repository's existing indigo/violet and neutral
design tokens, system font fallback, light/dark modes and English/German vocabulary.

## Asset and usage

- Production asset: [`ui/public/openbridge-mark.png`](../ui/public/openbridge-mark.png).
- Format: 1254 × 1254 RGB PNG, with an opaque white icon tile and generous padding.
- Used in the application navigation and as the favicon; no external image host.
- Keep the image square and proportional. The GUI displays it beside a live-text
  wordmark; its image alternative is empty to avoid repeating that same name.
- The white tile provides a consistent surface in both themes. Do not recolor,
  stretch, add a shadow, or overlay typography on the mark.

## Generation record

Mode: built-in `image_gen` tool, not the API/CLI fallback. The production image
was visually inspected and copied into the repository. The two transparent
explorations were not selected as the production asset.

Initial generation prompt:

> Create a polished, original professional application logo SYMBOL for an open-source developer workspace named OpenBridge. Output a single compact geometric logomark on a truly transparent background, no text, no letters drawn as typography, no mockup, no multiple variations. The symbol should evoke an open bridge joining two stable vertical piers with an elegant elevated connecting arch, subtly suggesting an open B through negative space. Precise grid-based proportions, strong recognizable silhouette at 24px, few broad flat shapes, architectural clarity, approachable technical identity. Palette strictly indigo #6366F1 and violet #8B5CF6, restrained transition if needed, transparent negative space. Balanced square composition, centered mark fills about 80 percent of the image, ample consistent transparent margin. Flat vector-like edges, no 3D, no shadows, no glows, no texture, no thin hairlines, no infinity symbol, no generic AI sparkle. This will be used as the real icon beside a separate live-text OpenBridge wordmark in a professional React GUI, on both very light #FFFFFF and dark #111827 surfaces. Deliver crisp production-quality transparent PNG.

Transparent refinement prompt:

> Polish this OpenBridge logo into a flawless production app icon. Preserve the exact two-pier double-arch silhouette, composition, proportions, transparent background, and indigo-to-violet colors. Change only edge quality: remove all stray blue/magenta pixels, detached fragments, rough alpha fringes, tiny protrusions and raster artifacts around every contour and internal opening. Every contour must be a smooth precise vector-like curve or straight line with clean antialiasing. No visible texture. All negative space must be completely transparent. Keep the broad flat shapes, no added shadows, no outlines, no text. Output one clean transparent PNG logo at high resolution.

Final production prompt (using the initial mark as the edit target):

> Create the final app-icon version of this exact two-pier, double-arch OpenBridge logo. Preserve the recognizable architectural silhouette and broad indigo #6366F1 to violet #8B5CF6 fill. IMPORTANT: put it on a perfectly solid pure WHITE #FFFFFF opaque background, including every internal opening. Do not output transparency. Replace every rough fringe, blue or magenta stray mark, protrusion, blotch and detached fragment with perfectly clean white background. Redraw smooth continuous geometric vector-quality outer and inner contours. Professional precise flat software logo, no texture, no shadows, no added outlines, no text. Square icon, symmetrically centered with 14 percent white padding. One mark only. It must be impeccably clean when inspected at high resolution and legible at 32 pixels.


## Cinematic bridge environment

Asset: `ui/public/bridge-panorama.png`. Generated with the built-in image tool
(generate mode, no reference image), then copied unchanged into the application.
It is a decorative forward-window plate. No depicted astronomical scene is a
claim about real Bridge state. The surrounding console, text and controls are
native interface elements and remain accessible without the image.

Exact generation prompt:

> Use case: cinematic production design. Asset type: panoramic background plate for a functional spaceship bridge interface, landscape 3:1 composition. Create a photoreal high-budget science fiction film establishing view from INSIDE the captain's bridge of a deep-space research vessel: a vast panoramic forward window, dark sculpted graphite-metal structural ribs framing the extreme left/right and upper edges, a razor-thin cool white light strip following the upper window arch, a low sweeping physical console sill at the bottom. Through the window see the immense curved limb of a blue-grey planet occupying the lower RIGHT half, luminous thin pale cyan atmosphere, white cloud systems, faint warm dawn sunlight at far right horizon. The LEFT and CENTER upper region are deep nearly black outer space with sparse subtle stars, deliberately low detail and dark for overlaying real interface typography. Subtle material reflections and believable scale, exquisite cinematography, quiet contemplative mood, disciplined asymmetrical composition. Palette: near-black navy #070D17, graphite #101C2B, cold silver #EDF4FA, restrained ice-blue #8DD9EC, tiny muted amber reflection #F1C78B. This is an environmental window plate, NOT a screenshot of a website, NOT a dashboard mockup. No humans, chairs, labels, letters, numbers, logos, fake charts, holograms, neon clutter, weaponry or copyrighted franchise elements. Make it refined, tactile, cinematic and convincingly spatial. Only a narrow frame; most of the image is the panoramic space view.


### Moving planet plate

`ui/public/bridge-planet.png` is a second, non-destructive asset, created with the
built-in image tool in edit mode using `bridge-panorama.png` as the reference.
It removes the frame so CSS can move the view independently beneath the fixed
console. Exact edit prompt:

> Edit this cinematic panoramic image into a clean background plate for slow animation. Remove ALL of the physical spaceship window frame, metal ribs, light strips and console sill around the edges, replacing those areas seamlessly with outer space above and the continuing planet below. Preserve the existing blue-grey planet, cloud systems, atmospheric rim, warm dawn at far right, lighting, photoreal quality and broad composition as closely as possible. Edge-to-edge unobstructed outer-space view, no spacecraft, no window frame, no foreground objects, no text, no logos. Keep the left upper half dark and low-detail for interface text. The result will move very slowly behind a separately constructed stationary UI frame. Same panoramic aspect ratio.
