---
version: alpha
name: fixture-legacy-deck-brand
last_updated: 2026-01-01
colors:
  primary: "#111111"
  secondary: "#666666"
  surface: "#FFFFFF"
  surface-subtle: "#F7F7F7"
  surface-muted: "#F0F0F0"
  on-primary: "#FFFFFF"
  on-surface: "#333333"
  on-surface-muted: "#666666"
  border: "#E0E0E0"
  dark-surface: "#111111"
  dark-surface-subtle: "#1B1B1B"
  dark-surface-muted: "#222222"
  dark-on-surface: "#DDDDDD"
  dark-border: "#333333"
typography:
  display:
    fontFamily: Playfair Display
    fontSize: 64px
    fontWeight: 500
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400
  code:
    fontFamily: JetBrains Mono
    fontSize: 14px
---

# Fixture design system for the html-slides dark-role tests

The pre-2026-07 shape: `dark-<role>` keys inside `colors:`. It declares a dark
ground and dark ink but no dark `secondary` and no dark `on-surface-muted`, the
gap a deck must not fill with the light caption grey. Neutral values, not a brand.
