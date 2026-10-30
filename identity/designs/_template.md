---
# Copy to identity/designs/<id>.md. The file name is the id that a context or
# persona names with `design_ref:` and a theme with `branding.design:`.
# Same format as the root DESIGN.md (Google Labs DESIGN.md, alpha), plus
# `scope`, `use_for` and `source`. For the full set of sections and tokens,
# copy the root DESIGN.md and change its values. Schema: ./_schema.yaml.
version: alpha
scope: user                  # user | personal | org; `org` reaches every member Bridge through the org overlay
name: example-org
description: One line on the brand's voice.
use_for: [mail, html, slides]   # mail, pdf, html, slides, dashboard, certificate, video, site, cockpit
source:                      # where the truth lives; this file mirrors it (optional)
  repo: example-org/website
  manifest: DESIGN.md
  implementation: src/styles/brand.css
  taken_at: 0000000          # the commit this copy was taken from

colors:
  primary: "#1F2937"           # headlines, primary buttons
  secondary: "#6B7280"         # captions, metadata
  accent: "#2563EB"            # links, highlights
  surface: "#FFFFFF"           # page background
  surface-muted: "#F3F4F6"     # chips, inline code
  on-surface: "#374151"        # body copy
  on-surface-muted: "#6B7280"  # secondary body
  on-primary: "#FFFFFF"        # text on primary
  border: "#E5E7EB"            # hairlines
  # dark mode: either `dark-*` keys here, or a `colorsDark:` block with the same keys

typography:
  h1:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: 600
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400

rounded:
  md: 8px

spacing:
  md: 16px
---

## Overview

What the brand should feel like, in a few sentences.

## Colors

What each colour is for, and where it must not be used.

## Typography

## Layout

## Elevation & Depth

## Shapes

## Components

## Do's and Don'ts
