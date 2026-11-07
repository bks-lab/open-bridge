# Credits

## Inspiration: frontend-slides
- **Repo:** https://github.com/zarazhangrui/frontend-slides
- **License:** MIT
- **What was adopted:**
  - Style preset concept (curated YAML-defined themes instead of single default)
  - Visual discovery workflow (preset picker before generation)
  - Anti-AI-slop blacklist (banned fonts, colors, patterns)
  - Content-density limits (hard caps per slide type, split-not-cram rule)
  - Map-not-manual architecture (compact SKILL.md routing to reference files)
- **What was NOT adopted:**
  - PowerPoint conversion (python-pptx dependency)
  - Inline editing (contenteditable + localStorage)
  - Fontshare CDN (fonts are self-hosted instead, see `assets/fonts/`; no external font CDN at all)
- **What we kept from our original:**
  - Automatic dark + light mode (prefers-color-scheme)
  - Semantic color system (green/red/amber/cyan + dim variants)
  - The first eleven slide types, Pipeline/Flow among them
  - Scroll-snap engine with staggered reveal animations

## Fonts
- **Source:** [@fontsource](https://fontsource.org) Latin subsets, converted from woff to woff2
  with fontTools; the glyph data is unchanged. Montserrat and Heebo are the woff2 files
  @fontsource 5.1.0 ships, unchanged.
- **License:** SIL Open Font License 1.1 for every family; each license sits next to the
  fonts as `assets/fonts/LICENSE-<family>.txt`.
- **Families:** Archivo Black, Bodoni Moda, Cormorant Garamond, DM Mono, DM Sans, Fira Code,
  Fraunces, Heebo, IBM Plex Mono, IBM Plex Sans, Inter Tight, JetBrains Mono, Montserrat,
  Outfit, Plus Jakarta Sans, Space Grotesk, Space Mono, Syne, Work Sans.
