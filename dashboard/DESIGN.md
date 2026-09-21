# EXNIGHT dashboard design direction

This is an adapted design study from Inspo MCP. It is a reference record, not copied source
code or branding.

## References

- Inspo's `bento-grid` recommendation: a strong first viewport, irregular visual weight,
  and clear grouping of primary state with supporting evidence.
- [Slush](https://slush.app): a light canvas with electric blue, mint, and playful color
  used as purposeful accents rather than decoration.
- [State of AI Design](https://stateofaidesign.com/chapters/tools): technical precision,
  coral energy, and controlled gradient moments.
- Inspo's comparison-table archetype: thin rules, no zebra striping, row hover to preserve
  scanability.

## Adapted tokens

The dashboard uses a colorful light editorial/stat-led skin rather than copying a source
site's values:

```css
--bg: #f8f6f1;
--panel: #ffffff;
--line: #d8ddd7;
--text: #07182f;
--blue: #1261b0;
--deep-blue: #052361;
--cyan: #3bebf3;
--mint: #55b189;
--coral: #f24706;
--violet: #7567e8;
```

Spacing follows a 4/8/12/16/32 rhythm with larger 40/48px section breathing room. Tables use thin rules and hover state; status
colors communicate evidence state, not trading performance. Color is assigned by meaning:
cobalt/cyan for active observation, mint for healthy coverage, coral/amber for attention,
and violet for validation. The interface remains read-only: interactive controls inspect,
filter, refresh, chart, and download evidence only.

Motion is deliberately informative: the hero and metrics enter once, the recorder status
pulses gently, and a newly rendered recorder series draws into view. `prefers-reduced-motion`
is respected and disables the motion layer.

## Information architecture

Home is a standalone landing surface. It carries the observation headline, current metrics,
the read-only principle, and three destination cards. Detailed content is intentionally kept
out of the landing view:

- `#/signals` contains the frozen signal table, filters, and row-level arithmetic dialog.
- `#/recorder` contains the price/public-book chart and collection health.
- `#/evidence` contains validation state, provenance, downloads, and known limits.

These are client-side routes inside the same dashboard shell, so the top navigation and
refresh state remain consistent while each workspace has its own heading and return path.

## Interaction principles

1. The next upcoming ex-date is the default view; older dates remain selectable.
2. Every signal row can be opened for its arithmetic and evidence sources.
3. Recorder health and public-book coverage are visible before any signal interpretation.
4. Missing evidence is shown as a warning or incomplete state, never filled with an assumption.
5. Any future execution flow must be a separate, explicitly gated screen.
