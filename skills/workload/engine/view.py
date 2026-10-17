"""view: the declared runs as one page a human reads.

The easiest place in this skill to state something nobody measured. A page has
no return code, nobody diffs it, and a green tick on it reads as proof to the
person looking. So three rules shape everything here.

**It repeats the honest sentence.** `reconcile` already says in words whether a
live source was asked, and how many of the declarations it reached. That
sentence is carried through verbatim AND as a structural attribute, because a
reader who skips the prose still has to be able to tell "these are running"
from "these are the declarations".

**It shows every declaration, including the ones nothing was said about.** A
page built from findings alone drops a workload nobody reported on, and an
absent row reads as a healthy one.

**Its data is never markup.** A declaration is a file a human writes and a
finding quotes a machine, so both are untrusted text and both are escaped.

Self-contained by construction: no font CDN, no script src, no image host. A
dashboard that fetches anything logs the reader's address somewhere else and
stops working the moment the machine is offline. Colours and type follow the
repository's DESIGN.md tokens rather than being invented here.
"""

from __future__ import annotations

import html as html_mod
import re as re_mod
from dataclasses import dataclass

from engine import errors, model
from engine import report as report_mod
from engine.backends import base as backend_base

#: The state a declaration is in when nothing at all was said about it. Not a
#: verdict: the absence of one, and it says so.
UNREPORTED = "not reported"

#: Which states are counted instead of listed, read from the terminal renderer
#: rather than repeated here. A real machine answers with over a thousand units
#: no declaration claims; `reconcile` ends on one line about them, and a page
#: that spells all of them out turns the same run into a summary in one place
#: and a wall of somebody else's daemons in the other.
COUNTED_ONLY_VALUES = tuple(state.value for state in report_mod.COUNTED_ONLY)

#: States that are about a machine's INVENTORY FILE rather than the machine.
#: They belong under their own heading: an entry that exists only in
#: `infra/remotes/<host>.yaml` filed under "on the machine" says the opposite of
#: what the finding says.
INVENTORY_VALUES = (model.WorkloadState.inventory_stale.value,
                    model.WorkloadState.inventory_missing.value,
                    model.WorkloadState.intentionally_absent.value)

#: The half of that bucket that is a DECISION rather than a gap. It shares the
#: bucket because it is anchored in the same file, and it gets its own heading
#: because the other heading says these entries have drifted and the advice
#: under it is to delete them.
DECIDED_VALUE = model.WorkloadState.intentionally_absent.value

#: Severity order for display, loudest first. Same order the table uses, so the
#: two surfaces cannot disagree about what matters.
_SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}

#: Brand-neutral tokens, hand-maintained. This skill ships as CORE (open-bridge
#: OSS), so it must not carry any one instance's DESIGN.md brand; the page has
#: to stand alone as one file regardless.
_CSS = """
/* Brand-neutral tokens. Editorial minimalism: hairlines, generous space, one
   gradient used once. Nothing is fetched. */
:root {
  --surface: #FFFFFF;
  --surface-subtle: #F9FAFB;
  --surface-muted: #F3F4F6;
  --on-surface: #111827;
  --secondary: #6B7280;
  --border: #E5E7EB;
  --accent-from: #3B82F6;
  --accent-to: #1D4ED8;
  --high: #B4232B;
  --medium: #8A5A00;
  --info: #6B7280;
  --ok: #10B981;
  /* gray-300, between the hairline and the secondary text. The day needs a
     rule a reader can follow across a track without it reading as a mark. */
  --rule: #D1D5DB;
  --topbar: 3.5rem;
  /* The measure of the page. The day is the widest column on it, and at the
     old 78rem it was about 270px for twenty-four hours: a strip, not a
     timeline. Prose keeps its own narrower measure (.lede), so the extra
     width goes to the table and to nothing else. */
  --max: 88rem;
  --s1: .25rem; --s2: .5rem; --s3: 1rem;
  --s4: 1.5rem; --s5: 2rem; --s6: 3rem; --s7: 4rem;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface: #111827;
    --surface-subtle: #1F2937;
    --surface-muted: #374151;
    --on-surface: #D1D5DB;
    --secondary: #9CA3AF;
    --border: #374151;
    --accent-from: #93C5FD;
    --accent-to: #60A5FA;
    --high: #FCA5A5;
    --medium: #FCD34D;
    --info: #9CA3AF;
    --ok: #34D399;
    --rule: #4B5563;
  }
}
:root[data-theme="dark"] {
  --surface: #111827;
  --surface-subtle: #1F2937;
  --surface-muted: #374151;
  --on-surface: #D1D5DB;
  --secondary: #9CA3AF;
  --border: #374151;
  --accent-from: #93C5FD;
  --accent-to: #60A5FA;
  --high: #FCA5A5;
  --medium: #FCD34D;
  --info: #9CA3AF;
  --ok: #34D399;
  --rule: #4B5563;
}
* { box-sizing: border-box; }
/* Our own display rules would otherwise beat the attribute, and a banner
   that is only nominally hidden shouts at every reader. */
[hidden] { display: none !important; }
body {
  margin: 0;
  background: var(--surface);
  color: var(--on-surface);
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, sans-serif;
  font-size: 15px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}

/* ——— The shell ———————————————————————————————————————————————
   A bar that stays, so the page has a place rather than a beginning. The
   gradient appears once, on the mark, and nowhere else: DESIGN.md reserves
   it and using it twice would spend it. */
.topbar { position: sticky; top: 0; z-index: 20; display: flex;
          align-items: center; gap: var(--s3); height: var(--topbar);
          padding: 0 var(--s4); background: var(--surface);
          border-bottom: 1px solid var(--border); }
.topbar .mark { display: flex; align-items: center; gap: .5rem;
                font-size: .9375rem; font-weight: 600; letter-spacing: -.01em;
                margin-right: auto; white-space: nowrap; }
.topbar .mark .dot { width: .5625rem; height: .5625rem; border-radius: 50%;
                     background: linear-gradient(135deg, var(--accent-from),
                                                 var(--accent-to)); }
.tabs { display: flex; gap: .125rem; overflow-x: auto; }
.tabs a { font-size: .875rem; color: var(--secondary); text-decoration: none;
          padding: .375rem .75rem; border-radius: 6px; white-space: nowrap; }
.tabs a:hover, .tabs a:focus { color: var(--on-surface);
                               background: var(--surface-subtle); }
.tabs a[aria-current="page"] { color: var(--on-surface); font-weight: 500;
                               background: var(--surface-muted); }
.wrap { max-width: var(--max); margin: 0 auto; padding: var(--s6) var(--s4) var(--s7); }
.frame { max-width: 96rem; margin: 0 auto; padding: var(--s4) var(--s4) var(--s5); }

/* ——— Type ————————————————————————————————————————————————————
   large = light, the one typographic signature of the design system. */
h1 { font-size: 2.75rem; font-weight: 300; letter-spacing: -.02em;
     line-height: 1.1; margin: 0 0 var(--s3); }
h2 { font-size: 1.75rem; font-weight: 300; letter-spacing: -.01em;
     line-height: 1.2; margin: 0 0 var(--s2); }
h3 { font-size: 1.0625rem; font-weight: 500; margin: 0 0 var(--s2); }
.eyebrow { font-size: .6875rem; font-weight: 500; letter-spacing: .08em;
           text-transform: uppercase; color: var(--secondary);
           margin: 0 0 .375rem; }
.lede { color: var(--secondary); font-size: 1.0625rem; font-weight: 300;
        line-height: 1.6; margin: 0 0 var(--s3); max-width: 46rem; }
.stamp { color: var(--secondary); font-size: .8125rem; margin: 0; }
section.block { margin: var(--s7) 0 0; }
section.block > .lede { font-size: .9375rem; margin-bottom: var(--s4); }

/* ——— The four counts ————————————————————————————————————————
   Counted off the very rows the table shows, never off a second source. The
   hairline grid is one background showing through 1px gaps, which is why the
   dividers cannot drift out of alignment with the cells. */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
         gap: 1px; background: var(--border); border: 1px solid var(--border);
         border-radius: 10px; overflow: hidden; margin: var(--s5) 0 0; }
.stats .stat { background: var(--surface); padding: var(--s4) var(--s3); }
.stats .n { display: block; font-size: 2.25rem; font-weight: 300;
            line-height: 1; letter-spacing: -.02em; }
.stats .k { display: block; margin-top: .5rem; font-size: .6875rem;
            font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
            color: var(--secondary); }
.stats .stat.flag .n { color: var(--high); }

#stale { border-left-color: var(--high); }
.banner {
  border: 1px solid var(--border);
  border-left: 3px solid var(--medium);
  background: var(--surface-subtle);
  padding: var(--s3) var(--s4);
  border-radius: 8px;
  margin: var(--s4) 0 0;
  font-size: .9375rem;
}
[data-probed="true"] .banner { border-left-color: var(--info); }
/* The bar of neighbouring pages. Deliberately plain: no tile, no dot, no
   badge. Anything shaped like a status would be a reading this page never
   took, since it has not opened a single one of them. rules/visual-output.md
   Gate 3. The sentence rides along on its own line at full width so it is
   read as part of the bar and not as a caption for the last link. */
.links { display: flex; flex-wrap: wrap; align-items: baseline;
         gap: .375rem 1.25rem; margin: var(--s4) 0 0; }
.links a { font-size: .875rem; font-weight: 500; color: var(--on-surface);
           text-decoration: none; border-bottom: 1px solid var(--border); }
.links a:hover, .links a:focus { border-bottom-color: var(--on-surface); }
.links .meta { flex-basis: 100%; }
.scroll { overflow-x: auto; }

/* ——— Tables ——————————————————————————————————————————————————
   Four columns at rest. Everything else a run carries moved into the panel
   underneath it, which is the same information one click away instead of six
   columns wide: a row that has to be read sideways is not readable. */
table { border-collapse: collapse; width: 100%; font-size: .875rem; }
thead th { text-align: left; font-size: .6875rem; font-weight: 500;
           letter-spacing: .06em; text-transform: uppercase;
           color: var(--secondary); padding: 0 var(--s3) .5rem;
           border-bottom: 1px solid var(--border); }
.runs tbody { border-bottom: 1px solid var(--border); }
.runs tr.run > td { padding: .875rem var(--s3); vertical-align: top; border: none; }
.runs tr.run:hover > td { background: var(--surface-subtle); }
.runs tr.why > td { padding: 0 var(--s3) var(--s4); border: none; }
/* The finding tables are one row per finding and stripe the ordinary way.
   Eighteen unstriped rows is its own readability bug, which is why the runs
   table losing its striping to a per group border does not take these with
   it: they are shaped differently and are read differently. */
.findings tbody tr:nth-child(even) { background: var(--surface-subtle); }
.findings th, .findings td { text-align: left; padding: .625rem var(--s3);
                             border-bottom: 1px solid var(--border);
                             vertical-align: top; }
/* nowrap is for the IDENTIFIER, which must not break mid-token. The cell also
   holds the purpose underneath, and a sentence inherits the opposite need: on
   2026-08-24 an eighty-character purpose was held on one line, the first column
   grew past this page's own measure, and the state column went off the edge and
   was cut mid-word. So the release is explicit, and the ceiling keeps one long
   sentence from taking the row even once it wraps. */
.id { font-weight: 500; white-space: nowrap; }
/* No ceiling here any more: the column now has a declared width, and a second
   limit inside it only reintroduces the wrap this was meant to end. */
.id .meta { white-space: normal; display: block; margin-top: .1875rem; }
/* Trailing the purpose, on the ragged edge it leaves. Their own line cost a
   line in every one of twenty-three rows; beside the name they pushed past
   the column and wrapped in about half of them, which is worse than either.
   Here they cost a line only when the sentence happens to end flush. */
.chips { white-space: normal; margin-left: .4375rem; }
.chip + .chip { margin-left: .3125rem; }
.chip { display: inline-block; font-size: .6875rem; color: var(--secondary);
        white-space: nowrap; background: var(--surface-muted);
        border-radius: 999px; padding: .0625rem .5rem; font-weight: 400; }
/* The strip of recorded runs. nowrap so the sequence stays a sequence: a
   history that wraps mid line reads as two histories, and the leftmost mark
   of the second line looks like a beginning. The marks are characters rather
   than drawn boxes so they inherit the reader's font size and survive a copy
   into a mail; help on the cursor because every mark carries a title. */
.recorded { white-space: nowrap; }
/* Set SMALL on purpose. `white-space: nowrap` plus one glyph per recorded run
   is a hard floor of about twenty-four glyphs, and at the old size that floor
   was 365px: wider than the day, on a column holding a row of identical dots.
   The floor is a third narrower now and the width it gave up went to the
   track. */
.strip { letter-spacing: .04em; font-size: .8125rem; line-height: 1; }
.strip .mark { cursor: help; }
.strip .mark-failed, .strip .mark-expired { color: var(--high); }
.strip .mark-skipped { color: var(--secondary); }
.meta { color: var(--secondary); font-size: .8125rem; }
.sev { font-size: .6875rem; font-weight: 500; text-transform: uppercase;
       letter-spacing: .06em; white-space: nowrap; display: block; }
.sev-high { color: var(--high); }
.sev-medium { color: var(--medium); }
.sev-info { color: var(--info); }
/* The verdict is the answer this table exists to give. It had no size of
   its own, so it read as small print between a severity above and a reason
   below, and no floor, so every column added since has taken width from it.
   Both are stated here rather than left to inherit. */
.state { font-weight: 600; white-space: nowrap; font-size: .9375rem;
         min-width: 8rem; display: inline-block; }
.verdict + .verdict { margin-top: .5rem; }
/* How many findings said the same thing. The multiplication sign as the
   CHARACTER, never an escape for it: this stylesheet and these strings are
   Python first, and a backslash escape here has produced a real control byte
   in the page three times already. */
.times { color: var(--secondary); font-size: .8125rem; margin-left: .375rem; }
/* The dossier: what the run IS, as opposed to how it went. Auto-fitting
   columns rather than a fixed count, so the same panel is a single column on
   a phone and four on a desk without a second stylesheet. */
.dossier { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
           gap: var(--s3) var(--s4); margin: 0 0 var(--s3); padding: var(--s3);
           border: 1px solid var(--border); border-radius: 8px;
           background: var(--surface-subtle); }
.dossier > div { min-width: 0; }
.dossier dt { font-size: .6875rem; font-weight: 500; letter-spacing: .06em;
              text-transform: uppercase; color: var(--secondary); }
.dossier dd { margin: .1875rem 0 0; font-size: .8125rem; word-break: break-word; }
.dossier dd.unit { white-space: nowrap; overflow-x: auto; word-break: normal; }
/* The reason now sits on a row of its own at the page's full measure, so
   it may finally use it. The lead-in repeats the state word: one run can
   carry several findings, and without it a reader cannot tell which
   sentence belongs to which verdict. */
tr.why .hint { display: block; max-width: 62rem; }
tr.why .lead { font-weight: 600; color: var(--on-surface); font-size: .8125rem; }
/* The separator is the CHARACTER, not a CSS escape for it. Written as a
   backslash escape, this stylesheet is a triple quoted Python string
   FIRST and CSS second: a backslash followed by two zeros is read as an
   octal escape, the page carries a real NUL byte, and `workload publish`
   dies inside subprocess with "embedded null byte", nowhere near here.
   Measured 2026-08-24, twice: the second time inside this very comment.
   The house rule is the fix: write the character. */
tr.why .lead::after { content: " · "; color: var(--secondary); font-weight: 400; }
.unreported { color: var(--secondary); font-style: italic; }
.hint { color: var(--secondary); font-size: .8125rem; }
button {
  font: inherit; font-size: .8125rem; cursor: pointer;
  background: var(--surface-subtle); color: var(--on-surface);
  border: 1px solid var(--border); border-radius: 6px; padding: .375rem .75rem;
}

/* ——— The day, as a column of the table ——————————————————————
   One track per row, in the widest column on the page, with a ruler in every
   section heading above them. It was a separate picture above the table until
   2026-08-27, which put every declaration on the page twice; it was then a
   270px strip in the narrowest usable column, which is a footnote about a day
   rather than a day. The width comes from --max and from the recorded strip
   giving some back: that strip has a hard floor of one glyph per recorded run
   and was quietly taking a third of the table for a row of identical dots. */
/* NOT sticky, and that is a measurement rather than a preference. The table
   sits in a container with `overflow-x: auto`, which makes it its own scroll
   container: a sticky head then sticks to THAT box and not to the window, so
   it was pinned 3.5rem into the table with the first section heading behind
   it. Removing the overflow instead would let a long history push the page
   sideways. The ruler is repeated per section instead, which needs no
   stickiness to stay in reach, and no reader depends on it alone: every track
   states its schedule in words directly underneath. */
thead th { background: var(--surface); }
.dayhead { font-weight: 400; letter-spacing: 0; text-transform: none;
           padding-bottom: 0; }
/* The ruler. It is drawn in EVERY section heading rather than once at the top
   of the table, because one ruler above twenty-five rows is a reference a
   reader loses on the first scroll and then cannot get back without leaving
   the row they came for. Three copies down one page cost three lines and mean
   the scale is always within a screen of the track it measures. */
.dayhead .scale { position: relative; height: 1.375rem; }
.dayhead .scale span { position: absolute; top: 0; transform: translateX(-50%);
                       font-size: .6875rem; color: var(--secondary);
                       font-variant-numeric: tabular-nums; }
/* Ticks under the labels, on the same twelve and a half percent the track is
   ruled on, so the two read as one instrument instead of a row of numbers
   above an unrelated bar. */
.dayhead .scale::after { content: ""; position: absolute; left: 0; right: 0;
                         bottom: 0; height: 5px;
                         background-image: repeating-linear-gradient(90deg,
                             var(--rule) 0 1px, transparent 1px 12.5%); }
.day { min-width: 20rem; }
.day .when { margin-top: .375rem; font-size: .75rem; color: var(--secondary); }
/* One day, drawn at a size a reader can actually read an hour off. The rules
   every three hours are a GRID and not a reading: they are what let a diamond
   be located at an o'clock instead of somewhere along a bar. Two weights,
   because twenty-four hours ruled evenly is a comb nobody can count: the
   heavier rule falls every six hours, so 06, 12 and 18 are found at a glance.
   The hours before 06 and after 18 stand on a ground of their own, for the
   same reason and asserting nothing about any run: it is the axis, shaded so
   the middle of the day can be found without counting ticks. Not "darker",
   here or in the note: the dark theme swaps which of the two is darker, and a
   page that names one of them is wrong for half its readers. Both are stated
   in the note under the table, because a shape nobody explains is decoration.

   The outline is an inset shadow and not a border: a border would move the
   padding box one pixel inward and every percent placed inside the track would
   then sit one pixel off the ruler drawn above it. */
.track { position: relative; height: 2rem; border-radius: 5px;
         box-shadow: inset 0 0 0 1px var(--border);
         background-color: var(--surface);
         background-image:
             repeating-linear-gradient(90deg,
                 transparent 0, transparent calc(25% - 1px),
                 var(--rule) calc(25% - 1px), var(--rule) 25%),
             repeating-linear-gradient(90deg,
                 transparent 0, transparent calc(12.5% - 1px),
                 var(--border) calc(12.5% - 1px), var(--border) 12.5%),
             linear-gradient(90deg, var(--surface-muted) 0 25%,
                 var(--surface) 25% 75%,
                 var(--surface-muted) 75% 100%); }
/* WHAT IS STILL TO COME, and only where a clock actually ran. Without the
   script `--now` is unset, the fallback puts the left edge at 100% and nothing
   is shaded: the page ships saying nothing about where the day has got to,
   which is the honest state of a document with no clock in it. With the script
   the rest of the day is set back, so a track stops looking the same at 03:00
   and at 23:00. Same provenance as the upright line, and accounted for in the
   same sentence under the table. */
.track::after { content: ""; position: absolute; top: 0; bottom: 0; right: 0;
                left: var(--now, 100%); z-index: 0; border-radius: 0 5px 5px 0;
                background: var(--surface-muted); opacity: .6; }
/* Every mark has a SHAPE as well as a colour: colour alone fails a reader with
   a colour vision deficiency, and this is the one place on the page where the
   difference between ran and did-not-run is a picture. They sit above the
   bands and above the now line, because a mark is the measurement and the
   other two are the ground it is measured against. */
.tick { position: absolute; top: 50%; z-index: 3;
        transform: translate(-50%, -50%);
        width: 13px; height: 13px; border-radius: 50%;
        border: 2px solid var(--info); background: var(--surface); }
.tick.missed { border-color: var(--high); border-width: 3px; }
.tick.trace { border-radius: 1px; background: var(--ok); border-color: var(--ok);
              width: 11px; height: 11px;
              transform: translate(-50%, -50%) rotate(45deg); }
.tick.trace-failed { border-radius: 1px; background: var(--high); border-color: var(--high);
                     width: 12px; height: 12px; }
.tick.due { border-style: dashed; background: var(--surface); }
.tick.unknown { border-style: dotted; opacity: .65; background: var(--surface); }
/* Not today. Faint and hollow, and never the same as `due`: on six days out of
   seven a weekly run would otherwise read as due this morning. */
.tick.elsewhen { border-style: dashed; opacity: .3; background: transparent; }
/* The three scales. All three ship; one is shown. `[hidden]` already wins
   globally, so nothing here sets a display that would fight it. */
.grid { display: grid; gap: 2px; }
.grid.week { grid-template-columns: repeat(7, 1fr); }
/* The month declares its column count INLINE, on both the ruler and the cells,
   because the two are separate grids stacked under one another and only line
   up if both are told the same number. Left to `auto-fit` the ruler sized its
   columns to the digits in them and the cells, which carry no text, to
   nothing: the scale then pointed at the wrong days, and plausibly. */
.cell { position: relative; height: 2rem; border-radius: 3px;
        display: flex; align-items: flex-start; justify-content: center;
        box-shadow: inset 0 0 0 1px var(--border); background: var(--surface); }
/* Due is an OUTLINE and a ground, never a hue on its own: the same rule the
   marks on the day follow. */
.cell.due { box-shadow: inset 0 0 0 1px var(--info);
            background: var(--surface-muted); }
/* And what actually ran is a SHAPE inside it, so the two facts never merge
   into one colour a reader has to decode. */
.cell.ran::after { content: ""; position: absolute; bottom: 4px; left: 50%;
                   width: 6px; height: 6px; margin-left: -3px;
                   transform: rotate(45deg); background: var(--ok); }
.cell .num { font-size: .625rem; line-height: 1.4; color: var(--secondary); }
.grid.month .cell { height: 1.75rem; }
.grid.month .num { font-size: .5rem; }
.grid.ruler .cell { height: 1.375rem; box-shadow: none; background: none;
                    align-items: center; }
/* Thirty-one identical boxes are a bar, not a month. The week boundary is the
   one rhythm a month has, and it is drawn where it actually falls rather than
   every seventh cell from the first. */
.grid.month .cell.wkstart { margin-left: 3px; }
/* A cadence has no o'clock to sit at, and until 2026-08-27 it was drawn as a
   stripe repeating every fourteen pixels. That is a rhythm, and it was the
   same rhythm for every five minutes and for every hour: roughly a hundred
   evenly spaced marks that a reader counts as firings. The page asserted a
   beat it had not measured. It is a rail now, present all day and claiming no
   moment, and the beat is a word under the track, where it came from.

   Both bands were then drawn so faintly that on the live page they were
   effectively invisible: a continuous band at two tenths opacity over a light
   ground is the ground. Eighteen of twenty-five runs on this instance are one
   of these two shapes, so what was invisible was most of the picture. */
.band { position: absolute; left: 0; right: 0; border-radius: 2px; z-index: 1; }
.band.cadence { top: 50%; height: 3px; transform: translateY(-50%);
                background: var(--info); opacity: .85; }
/* End caps, so a rail reads as running from one end of the day to the other
   rather than as a rule somebody drew through the middle of the track. */
.band.cadence::before, .band.cadence::after {
  content: ""; position: absolute; top: -5px; width: 3px; height: 13px;
  border-radius: 1px; background: var(--info); }
.band.cadence::before { left: 0; }
.band.cadence::after { right: 0; }
.band.continuous { top: 5px; bottom: 5px; background: var(--info); opacity: .45; }
/* Now, and only where every run on this page keeps the same time zone. The
   axis is the MACHINE's day, so a line taken from the reader's own offset
   would be right in one office and hours out in the next; the script computes
   the hour in the declared zone instead and draws nothing at all when the
   declarations disagree about which zone that is.

   It is script-only for the same reason the age in the header is: it is a fact
   only the reader's clock knows, and a server-rendered one would be frozen at
   the moment the page was written. The flat accent is the one colour here that
   is not a verdict, which is what this line needs: it is neither good nor bad,
   it is where the day has got to. */
.nowline { position: absolute; top: -3px; bottom: -3px; width: 2px;
           margin-left: -1px; z-index: 2; border-radius: 1px;
           background: var(--accent-from); pointer-events: none; }
.dayhead .nowmark { position: absolute; top: -1px; transform: translateX(-50%);
                    z-index: 2; font-size: .625rem; font-weight: 600;
                    color: var(--accent-from); background: var(--surface);
                    padding: 0 .25rem; border-radius: 3px; white-space: nowrap;
                    font-variant-numeric: tabular-nums; }
.day .note { font-size: .75rem; color: var(--secondary); font-style: italic; }
/* How long ago, in the reader's present. The absolute stamp is what SHIPS, so
   a reader without scripting gets an answer rather than an empty line; the
   clock turns it into a distance. */
.day .ago { margin-top: .125rem; font-size: .75rem; color: var(--secondary); }
.day .ago time { font-variant-numeric: tabular-nums; }
/* The names of the machine's own undeclared units, as a grid rather than as a
   table of one sentence repeated. Measured on the live page: thirty-two rows,
   each carrying the same sentence with the name already in the first cell,
   about eleven hundred pixels of it. Each name keeps its sentence on the
   cursor, so nothing was dropped, only stopped from being said again. */
.units { display: grid; list-style: none; margin: 0 0 var(--s4); padding: 0;
         gap: 0 var(--s4); font-size: .8125rem;
         grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); }
.units li { padding: .3125rem 0; border-bottom: 1px solid var(--border);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            cursor: help; }
/* A section of the table, not a row of it: it spans the whole width and
   carries no run of its own. */
tbody.grouphead th { text-align: left; background: var(--surface);
                     padding: var(--s5) var(--s3) .375rem;
                     border-bottom: 1px solid var(--border); font-weight: 400; }
tbody.grouphead:first-of-type th { padding-top: var(--s3); }
tbody.grouphead .eyebrow { margin: 0; }
.legend { display: flex; flex-wrap: wrap; gap: .375rem 1.5rem; font-size: .75rem;
          color: var(--secondary); margin: var(--s3) 0 0; padding: 0;
          list-style: none; }
.legend li { display: flex; align-items: center; gap: .5rem; }
.legend .sample { position: relative; display: inline-block; width: 24px;
                  height: 14px; border-radius: 3px;
                  background: var(--surface-subtle); }
footer { margin-top: var(--s7); padding-top: var(--s4);
         border-top: 1px solid var(--border); color: var(--secondary);
         font-size: .8125rem; }

/* ——— What needs a person ——————————————————————————————————————
   Above the table, because a page that opens with an inventory makes a reader
   assemble "is anything wrong" by eye out of twenty-five rows. The border is
   on the left and takes its colour from the worst thing in the list; the whole
   block is absent, and replaced by a sentence, when there is nothing in it. */
.open { margin: var(--s4) 0 0; padding: var(--s3) var(--s4);
        border: 1px solid var(--border); border-left: 3px solid var(--high);
        border-radius: 8px; background: var(--surface-subtle); }
.open .eyebrow { margin: 0 0 .5rem; }
.open ul { list-style: none; margin: 0; padding: 0; }
.open li + li { margin-top: var(--s3); padding-top: var(--s3);
                border-top: 1px solid var(--border); }
.open li > .sev { display: inline-block; margin-right: .5rem; }
.open li > a { font-weight: 600; font-size: .9375rem; color: var(--on-surface);
               text-decoration: none; border-bottom: 1px solid var(--border); }
.open li > a:hover, .open li > a:focus { border-bottom-color: var(--on-surface); }
.open .what { font-size: .875rem; margin-top: .1875rem; }
/* The skill's own instruction. It has always been computed, on every finding,
   and until 2026-08-27 no renderer had ever put one on a page. */
.open .todo { font-size: .8125rem; color: var(--secondary); margin-top: .125rem; }
.open .todo::before { content: "→ "; }

/* ——— Facets, disclosure, framed neighbours ————————————————————
   All three appear only where scripting runs or configuration asked for them:
   without either, the page is exactly the long readable document it was. */
.facets { margin: var(--s3) 0 var(--s4); padding: var(--s3);
          border: 1px solid var(--border); border-radius: 10px;
          background: var(--surface-subtle); }
.facets .row { display: flex; flex-wrap: wrap; align-items: center;
               gap: .375rem .625rem; margin: .3125rem 0; }
.facets .name { font-size: .6875rem; font-weight: 500; letter-spacing: .06em;
                text-transform: uppercase; color: var(--secondary);
                min-width: 5rem; }
.facets button { font: inherit; font-size: .8125rem; cursor: pointer;
                 padding: .1875rem .625rem; border-radius: 999px;
                 border: 1px solid var(--border); background: var(--surface);
                 color: var(--on-surface); }
.facets button:hover { border-color: var(--secondary); }
.facets button[aria-pressed="true"] { background: var(--on-surface);
                                      color: var(--surface);
                                      border-color: var(--on-surface); }
.facets button .n { color: var(--secondary); font-size: .75rem;
                    margin-left: .3125rem; }
.facets button[aria-pressed="true"] .n { color: var(--surface); opacity: .7; }
.facets .clear { border-style: dashed; background: transparent; }
.facets input { font: inherit; font-size: .8125rem; padding: .25rem .625rem;
                border: 1px solid var(--border); border-radius: 999px;
                background: var(--surface); color: var(--on-surface);
                min-width: 18rem; max-width: 100%; }
.facets input:focus { outline: 2px solid var(--on-surface); outline-offset: -1px; }
/* Sortable heads. The arrow is rendered by the script and only on the column
   actually sorting, so a page without scripting carries no affordance for a
   control it does not have. */
thead th[data-sort] { cursor: pointer; user-select: none; }
thead th[data-sort]:hover { color: var(--on-surface); }
thead th[aria-sort] { color: var(--on-surface); }
thead th .dir { margin-left: .25rem; }
.facets .meta { display: block; margin-top: .5rem; }
tr.run[role="button"] { cursor: pointer; }
/* The character, not an escape for it. Written as a backslash escape this
   stylesheet is a Python string FIRST: "\\25B8" is read as the octal escape
   \\25 followed by "B8", and the page carries a real control byte. The
   comment forty lines up says exactly this and was itself written after the
   mistake happened twice. This is the third time. */
tr.run[role="button"] td.id::before { content: "▸"; display: inline-block;
                                      width: 1em; color: var(--secondary);
                                      transition: transform .12s ease; }
tr.run[aria-expanded="true"] td.id::before { transform: rotate(90deg); }
tr.run[role="button"]:focus-visible { outline: 2px solid var(--on-surface);
                                      outline-offset: -2px; }
tbody[hidden] { display: none; }
.frame > .meta { margin: .25rem 0 var(--s3); max-width: 62rem; }
.frame iframe { width: 100%; height: 70vh; border: 1px solid var(--border);
                border-radius: 8px; background: var(--surface); }
/* With the shell live a neighbour gets the whole window instead of a
   letterbox in the middle of somebody else's page. That was the complaint,
   and it is the reason the frames became views rather than a footer. */
[data-tabs="on"] .frame iframe { height: calc(100vh - var(--topbar) - 8.5rem); }
@media (max-width: 60rem) {
  .wrap { padding: var(--s5) var(--s3) var(--s6); }
  h1 { font-size: 2.125rem; }
}
@media print {
  .topbar { position: static; }
  thead th { position: static; }
  tbody[hidden] { display: table-row-group; }
  .view[hidden] { display: block !important; }
  .facets, .frame iframe, .tabs { display: none; }
}
"""

_JS = """
/* Two pure functions and the wiring that uses them, in that order and kept
   apart on purpose: the functions are what the test suite executes in node, so
   the page's own arithmetic is measured rather than eyeballed in a diff. The
   wiring below runs only where a document exists. */

function ageMs(iso, nowMs) {
  var t = Date.parse(iso);
  return isNaN(t) ? null : nowMs - t;
}

/* How old this page is, in the reader's words. Empty when the moment cannot be
   read: an invented age would be worse than none. */
function ageText(iso, nowMs) {
  var ms = ageMs(iso, nowMs);
  if (ms === null) { return ''; }
  if (ms < -60000) { return 'the clocks disagree'; }
  if (ms < 60000) { return 'just now'; }
  if (ms < 3600000) { return Math.round(ms / 60000) + ' min ago'; }
  if (ms < 86400000) { return Math.round(ms / 3600000) + ' h ago'; }
  return Math.round(ms / 86400000) + ' d ago';
}

/* Null unless a refresh cadence was declared. Without one there is no line
   between a page made minutes ago and one made in March, and drawing it anyway
   would be a number nobody chose. */
function verdict(iso, nowMs, staleAfterMin) {
  if (staleAfterMin === null || staleAfterMin === undefined || !(staleAfterMin > 0)) {
    return null;
  }
  var ms = ageMs(iso, nowMs);
  if (ms === null) { return null; }
  return ms > staleAfterMin * 60000 ? 'stale' : 'current';
}

/* The moment a FETCHED copy of this page carries. Deliberately by string
   search and not by parsing: the page must not depend on a DOM parser being
   available, and the two markers it looks for are the exact ones the renderer
   writes. That coupling is real, so a test renders a page and feeds it back
   through here rather than through a hand-written sample. */
function stampIn(html) {
  var key = 'id="stamp" datetime="';
  var at = html ? html.indexOf(key) : -1;
  if (at < 0) { return null; }
  var from = at + key.length;
  var to = html.indexOf('"', from);
  return to < 0 ? null : html.slice(from, to);
}

/* Whether a fetched copy is genuinely newer than the one being read. False
   whenever either moment cannot be read, because reloading on an unreadable
   answer would throw away a page that is still saying something true. */
function isNewer(mineIso, theirsIso) {
  var mine = Date.parse(mineIso);
  var theirs = Date.parse(theirsIso);
  if (isNaN(mine) || isNaN(theirs)) { return false; }
  return theirs > mine;
}

/* The filter predicate, kept out of the wiring for the same reason as the two
   above it: this is the arithmetic, and the suite runs it in node instead of
   reading it in a diff.

   `have` maps a facet to the values a run carries, `chosen` maps a facet to the
   values a reader picked. Within a facet the values are OR (a reader asking for
   agents and daemons wants both), across facets they are AND (agents ON THIS
   host). An empty or absent choice for a facet is not a filter at all, which is
   what makes "show all" the same code path as "nothing picked yet" rather than
   a second one that can disagree with it. */
function facetMatch(have, chosen) {
  for (var facet in chosen) {
    if (!Object.prototype.hasOwnProperty.call(chosen, facet)) { continue; }
    var want = chosen[facet];
    if (!want || !want.length) { continue; }
    var mine = have[facet] || [];
    var hit = false;
    for (var i = 0; i < want.length; i += 1) {
      if (mine.indexOf(want[i]) !== -1) { hit = true; break; }
    }
    if (!hit) { return false; }
  }
  return true;
}

/* Where a wall clock reading falls on a 24 hour axis, as a share of the day.
   Null on anything it cannot read, because a line drawn at a guessed hour is
   worse than no line: it looks exactly like a measured one. */
function nowPct(hhmm) {
  var m = /^([0-9]{1,2}):([0-9]{2})$/.exec(String(hhmm === 0 ? '' : (hhmm || '')));
  if (!m) { return null; }
  var h = Number(m[1]);
  var min = Number(m[2]);
  if (h > 24 || min > 59) { return null; }
  if (h === 24) { h = 0; }
  return (h * 60 + min) / 14.4;
}

/* The wall clock in the MACHINE's zone, not the reader's. Intl does the whole
   job, so no offset is computed here and none is guessed: the reader may sit
   anywhere and the answer is still the hour the machine is keeping. Empty on
   an unknown zone, which is what makes an unreadable declaration produce no
   line rather than a line in the wrong place. */
function clockIn(zone, when) {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: false
    }).format(when);
  } catch (e) { return ''; }
}

/* Whether one run answers a typed query. Pure and beside `facetMatch` for the
   same reason: this is the arithmetic, and the suite runs it in node rather
   than reading it in a diff.

   Every word has to be found, so two words narrow instead of widen: a reader
   typing two things means both, and an OR here makes the second word ADD rows,
   which reads as a broken filter. An empty query is not a filter at all, which
   is what makes "cleared" the same code path as "never typed". */
function searchMatch(haystack, query) {
  var words = String(query || '').toLowerCase().split(/\\s+/);
  var text = String(haystack || '').toLowerCase();
  for (var i = 0; i < words.length; i += 1) {
    if (!words[i]) { continue; }
    if (text.indexOf(words[i]) === -1) { return false; }
  }
  return true;
}

if (typeof document !== 'undefined') {
  (function () {
    var root = document.documentElement;
    try {
      var saved = localStorage.getItem('workload-theme');
      if (saved) { root.setAttribute('data-theme', saved); }
    } catch (e) { /* a private window throws on read; the OS default is fine */ }

    var when = document.getElementById('stamp');
    var iso = when && when.getAttribute('datetime');
    var age = document.getElementById('age');
    var old = document.getElementById('stale');
    var limit = root.getAttribute('data-stale-after-min');

    /* RECOMPUTED, not computed once. `Date.now()` used to be read a single
       time, at load. A tab left open then said `just now` for as long as it
       stayed open, and never revealed its stale banner: at three in the
       morning it still claimed to be the present. That is the exact failure
       this page was built for, moved one step along, and worse than the
       original, because a page nobody refreshed at least kept quiet while this
       one asserts freshness out loud. Half a minute is fine: the smallest
       thing it has to say is `1 min ago`. */
    function tell() {
      var now = Date.now();
      var said = ageText(iso, now);
      if (age && said) { age.textContent = ' (' + said + ')'; }
      if (old && verdict(iso, now, limit === null ? null : Number(limit)) === 'stale') {
        old.removeAttribute('hidden');
      }
    }
    tell();
    setInterval(tell, 30000);

    /* And a live view, but only where somebody declared a cadence for it. Same
       rule as the staleness verdict: a rate nobody chose would be invented.

       It asks first and reloads second, and it reloads ONLY on an answer that
       is genuinely newer. A plain reload on a timer would blank the page into
       a browser error the moment the server is unreachable, which destroys a
       reading that is still true and still aging honestly. On any failure
       nothing happens at all, and `tell` keeps counting up, so an outage shows
       up as a page that says how old it is instead of a page that is gone. */
    var poll = Number(root.getAttribute('data-poll-sec'));
    if (poll > 0 && typeof fetch === 'function') {
      setInterval(function () {
        fetch(location.href, { cache: 'no-store' }).then(function (answer) {
          return answer && answer.ok ? answer.text() : null;
        }).then(function (text) {
          if (text && isNewer(iso, stampIn(text))) { location.reload(); }
        }).catch(function () { /* unreachable is not a reason to lose the page */ });
      }, poll * 1000);
    }

    var button = document.getElementById('theme');
    if (!button) { return; }
    button.addEventListener('click', function () {
      var dark = root.getAttribute('data-theme') === 'dark'
        || (!root.getAttribute('data-theme')
            && window.matchMedia('(prefers-color-scheme: dark)').matches);
      var next = dark ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('workload-theme', next); } catch (e) { /* ditto */ }
    });
  })();

  /* Disclosure and facets, both PROGRESSIVE. The page ships expanded and
     unfiltered, so a reader without scripting gets the long document that was
     here before rather than a table whose reasons are all hidden and whose
     filter bar does nothing. Everything below only ever takes away. */
  (function () {
    /* The suite's stub document carries only what the wiring above needs. A
       guard here rather than a shim there: this block is plumbing, and its
       arithmetic lives in facetMatch, which the suite calls directly. */
    if (!document.querySelector) { return; }
    var table = document.querySelector('table.runs');
    var bodies = table ? Array.prototype.slice.call(table.tBodies) : [];
    /* Only the runs. The section headings are tbodies too, and toggling or
       counting them would put the day's three headings into a count of runs. */
    var groups = bodies.filter(function (t) { return t.getAttribute('data-id'); });
    var heads = bodies.filter(function (t) { return t.className === 'grouphead'; });
    if (!groups.length) { return; }

    /* 1. Collapse. The reason row is what a reader had to scroll for; it stays
          one click away instead of one scroll away, and the run row says which
          state it is in rather than leaving the arrow to carry it alone. */
    function toggle(group, open) {
      var head = group.querySelector('tr.run');
      var why = group.querySelector('tr.why');
      if (!head || !why) { return; }
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      why.hidden = !open;
    }
    groups.forEach(function (group) {
      toggle(group, false);
      var head = group.querySelector('tr.run');
      if (!head) { return; }
      head.addEventListener('click', function (ev) {
        /* A link inside the row is a link, not a handle for the panel. */
        if (ev.target.closest('a')) { return; }
        toggle(group, head.getAttribute('aria-expanded') !== 'true');
      });
      head.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter' && ev.key !== ' ') { return; }
        ev.preventDefault();
        toggle(group, head.getAttribute('aria-expanded') !== 'true');
      });
    });

    /* 2. Facets. The bar is rendered hidden and revealed here, for the same
          reason: a control that cannot act must not be on the page. */
    var bar = document.getElementById('facets');
    if (!bar) { return; }
    bar.hidden = false;
    var chosen = {};

    /* Aus den gerenderten Knöpfen, nie aus einer zweiten Liste. Eine Facette
       ohne Knopf kann niemand wählen, also braucht sie hier auch keinen Eintrag;
       und eine Facette MIT Knopf ist damit garantiert bekannt. Vorher stand die
       Liste hier als Literal, und ein Knopf, den sie nicht kannte, hätte beim
       Druck jede Zeile versteckt. */
    var FACETS = [];
    Array.prototype.forEach.call(
      bar.querySelectorAll('[data-facet]'), function (b) {
        var f = b.getAttribute('data-facet');
        if (f && FACETS.indexOf(f) === -1) { FACETS.push(f); }
      });
    function matches(group) {
      var have = {};
      FACETS.forEach(function (facet) {
        have[facet] = (group.getAttribute('data-' + facet) || '').split(' ');
      });
      return facetMatch(have, chosen);
    }

    var count = document.getElementById('shown');
    var box = document.getElementById('q');
    function apply() {
      var visible = {};
      var n = 0;
      var query = box ? box.value : '';
      groups.forEach(function (group) {
        /* AND with the facets, never OR. A search that widened a filtered set
           would let a reader believe they had seen everything matching both. */
        var ok = matches(group)
          && searchMatch(group.getAttribute('data-search'), query);
        group.hidden = !ok;
        if (ok) { visible[group.getAttribute('data-id')] = true; n += 1; }
      });
      /* A section heading follows its rows. A heading reading "On a cadence
         (10)" above nothing is a count of runs the reader just filtered away,
         which is the one number on this page that must never disagree with
         what is under it.

         The axis needs no such care any more: it is a column of these very
         rows, so hiding a row takes its day with it. That was a whole class of
         defect and it went away with the second list. */
      heads.forEach(function (head) {
        var band = head.getAttribute('data-band');
        var mine = 0;
        groups.forEach(function (group) {
          if (!group.hidden && group.getAttribute('data-band') === band) {
            mine += 1;
          }
        });
        head.hidden = mine === 0;
        /* Its count follows its rows, exactly like the page total. Taking the
           heading away when its LAST row goes is only half the fix: with three
           of eight rows left it kept saying eight, which is a number above the
           very rows that contradict it. */
        var said = head.querySelector('.n');
        if (said) {
          var total = Number(said.getAttribute('data-total'));
          said.textContent = (mine === total) ? String(total)
                                              : (mine + ' of ' + total);
        }
      });
      if (count) {
        var total = groups.length;
        count.textContent = (n === total) ? String(total) : (n + ' of ' + total);
      }
    }

    Array.prototype.forEach.call(bar.querySelectorAll('button[data-facet]'),
      function (button) {
        button.addEventListener('click', function () {
          var facet = button.getAttribute('data-facet');
          var value = button.getAttribute('data-value');
          chosen[facet] = chosen[facet] || [];
          var at = chosen[facet].indexOf(value);
          if (at === -1) { chosen[facet].push(value); }
          else { chosen[facet].splice(at, 1); }
          button.setAttribute('aria-pressed', at === -1 ? 'true' : 'false');
          apply();
        });
      });
    /* Die Abkürzung im Banner ist KEIN zweiter Filter, sie drückt die Pille.
       Ein Codeweg, damit der Zustand der Pille und das, was die Tabelle zeigt,
       nicht auseinanderlaufen können. Findet sie keine Pille, tut sie nichts
       und sagt es, statt eine Auswahl vorzutäuschen, die niemand sieht. */
    var shortcut = document.querySelector('#attention button[data-facet]');
    if (shortcut) {
      shortcut.addEventListener('click', function () {
        var pill = bar.querySelector(
          'button[data-facet="' + shortcut.getAttribute('data-facet')
          + '"][data-value="' + shortcut.getAttribute('data-value') + '"]');
        if (!pill) { return; }
        pill.click();
        shortcut.setAttribute('aria-pressed', pill.getAttribute('aria-pressed'));
      });
    }

    var clear = bar.querySelector('button.clear');
    if (clear) {
      clear.addEventListener('click', function () {
        chosen = {};
        if (box) { box.value = ''; }
        Array.prototype.forEach.call(bar.querySelectorAll('button[data-facet]'),
          function (b) { b.setAttribute('aria-pressed', 'false'); });
        if (shortcut) { shortcut.setAttribute('aria-pressed', 'false'); }
        apply();
      });
    }
    if (box) {
      box.addEventListener('input', apply);
      /* Escape clears, because a search box that can only be emptied by
         selecting its text is one a reader leaves filled by accident. */
      box.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && box.value) { box.value = ''; apply(); }
      });
    }

    /* 3. Open every row at once. The dossier is one click away per run, which
          is right for reading one and wrong for comparing twenty. */
    var expander = document.getElementById('expand');
    if (expander) {
      expander.addEventListener('click', function () {
        var open = expander.getAttribute('aria-pressed') !== 'true';
        expander.setAttribute('aria-pressed', open ? 'true' : 'false');
        expander.textContent = open ? 'close every row' : 'open every row';
        groups.forEach(function (group) { toggle(group, open); });
      });
    }

    /* 4. A link into the table opens the row it lands on. Without this a link
          from "needs a person" scrolls to a collapsed row, which looks exactly
          like a link that went to the wrong place. */
    function reveal() {
      var id = (location.hash || '').replace(/^#/, '');
      if (!id) { return; }
      var row = document.getElementById(id);
      var group = row && row.closest ? row.closest('tbody[data-id]') : null;
      if (group) { toggle(group, true); }
    }
    reveal();
    window.addEventListener('hashchange', reveal);
    Array.prototype.forEach.call(document.querySelectorAll('.open a[href^="#"]'),
      function (a) { a.addEventListener('click', function () { setTimeout(reveal, 0); }); });

    /* 5. Sorting, WITHIN each section and never across them. The sections say
          what a run IS, so a sort that dissolved them would answer a different
          question than the one the heading above each group asks. A third
          click restores the order the page was built in, because a table with
          no way back to its own default is one a reader leaves sorted wrong.

          The keys are rendered by the renderer, never derived here: which of
          two verdicts is worse is a decision of that module, and a second copy
          of it in this one drifts from the first the day a severity is added. */
    /* `sortHeads` and not `heads`. There is already a `heads` in this scope,
       holding the SECTION headings, and a second `var` of that name in the
       same function silently rebinds it: `apply()` then iterated the table's
       four column headers, hid all four on every filter, and stopped
       correcting the section counts, which is precisely the defect the counts
       were made elements to prevent. Measured in a live browser on 2026-08-27,
       twenty minutes after writing it. */
    var sortHeads = Array.prototype.slice.call(
      table ? table.querySelectorAll('thead th[data-sort]') : []);
    var sections = [];
    var current = null;
    bodies.forEach(function (t) {
      if (t.className === 'grouphead') {
        current = { head: t, rows: [] };
        sections.push(current);
      } else if (current && t.getAttribute('data-id')) {
        current.rows.push(t);
      }
    });
    sections.forEach(function (section) {
      section.order = section.rows.slice();
    });

    function keyOf(group, name) {
      var raw = group.getAttribute('data-sort-' + name);
      if (name === 'when' || name === 'state') { return Number(raw); }
      return String(raw === null ? '' : raw);
    }

    function arrange(name, dir) {
      sections.forEach(function (section) {
        var rows = section.order.slice();
        if (name) {
          rows.sort(function (a, b) {
            var x = keyOf(a, name);
            var y = keyOf(b, name);
            /* A run with nothing recorded has no place on that scale, so it
               goes to the end in BOTH directions rather than pretending to be
               the oldest or the newest thing on the page. */
            if (x === '' && y !== '') { return 1; }
            if (y === '' && x !== '') { return -1; }
            if (x < y) { return dir === 'descending' ? 1 : -1; }
            if (x > y) { return dir === 'descending' ? -1 : 1; }
            return 0;
          });
        }
        /* A CURSOR, not a fixed anchor. `section.head.nextSibling` taken once
           is itself one of the rows about to be moved: the moment it is, every
           later insertion happens relative to wherever that row landed, and
           the section comes back in an order that is neither the sort nor the
           default. Measured in a live browser on 2026-08-27: after three
           clicks on one column, "back to default" returned six of seven rows
           correctly and put the seventh last. */
        var at = section.head;
        rows.forEach(function (row) {
          at.parentNode.insertBefore(row, at.nextSibling);
          at = row;
        });
      });
    }

    var sorted = { name: '', dir: '' };
    sortHeads.forEach(function (head) {
      head.setAttribute('tabindex', '0');
      head.setAttribute('role', 'button');
      function turn() {
        var name = head.getAttribute('data-sort');
        if (sorted.name !== name) { sorted = { name: name, dir: 'ascending' }; }
        else if (sorted.dir === 'ascending') { sorted.dir = 'descending'; }
        else { sorted = { name: '', dir: '' }; }
        sortHeads.forEach(function (other) {
          other.removeAttribute('aria-sort');
          var arrow = other.querySelector('.dir');
          if (arrow) { arrow.parentNode.removeChild(arrow); }
        });
        if (sorted.name) {
          head.setAttribute('aria-sort', sorted.dir);
          var mark = document.createElement('span');
          mark.className = 'dir';
          mark.textContent = sorted.dir === 'ascending' ? '\u2191' : '\u2193';
          head.appendChild(mark);
        }
        arrange(sorted.name, sorted.dir);
      }
      head.addEventListener('click', turn);
      head.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter' && ev.key !== ' ') { return; }
        ev.preventDefault();
        turn();
      });
    });
  })();

  /* Now, as one upright line through every track and a caret on every ruler.
     Script-only and deliberately so: it is a fact only the reader's clock
     knows, exactly like the age in the header, and a server-rendered one would
     be frozen at the moment the page was written while looking live. Drawn
     only where `data-zone` is set, which the renderer does only when every
     declaration on the page agrees about the zone; where they do not, the page
     already carries a sentence saying why there is no line. */
  (function () {
    if (!document.querySelectorAll || !document.createElement) { return; }
    var zone = document.documentElement.getAttribute('data-zone');
    if (!zone) { return; }
    var tracks = Array.prototype.slice.call(document.querySelectorAll('.track'));
    var scales = Array.prototype.slice.call(
      document.querySelectorAll('.dayhead .scale'));
    if (!tracks.length) { return; }
    var lines = tracks.map(function (track) {
      var line = document.createElement('span');
      line.className = 'nowline';
      line.hidden = true;
      track.appendChild(line);
      return line;
    });
    var carets = scales.map(function (scale) {
      var caret = document.createElement('span');
      caret.className = 'nowmark';
      caret.hidden = true;
      scale.appendChild(caret);
      return caret;
    });
    var note = document.getElementById('nownote');
    /* Recomputed on a timer for the same reason the age is: a tab left open
       overnight would otherwise keep a line at yesterday afternoon and go on
       looking like a live reading. A minute is the smallest step this can
       show, since the axis is 1440 minutes wide. */
    /* THE SCALE. Three are rendered and one is shown, so the switch only ever
       takes something away that is already on the page: a reader with no
       scripting keeps the day, which is the scale that needs no choosing.
       The row is revealed here for the same reason the facet bar is, and the
       now line is placed again afterwards because a track that was hidden
       measured zero and its hour labels never got out of the caret's way. */
    var picks = [].slice.call(document.querySelectorAll('[data-scale-pick]'));
    if (picks.length) {
      var scaleRow = picks[0].parentNode;
      if (scaleRow) { scaleRow.hidden = false; }
      picks.forEach(function (button) {
        button.addEventListener('click', function () {
          var which = button.getAttribute('data-scale-pick');
          [].forEach.call(document.querySelectorAll('.lens'), function (lens) {
            lens.hidden = lens.getAttribute('data-scale') !== which;
          });
          picks.forEach(function (other) {
            other.setAttribute(
              'aria-pressed',
              other.getAttribute('data-scale-pick') === which ? 'true' : 'false');
          });
          place();
        });
      });
    }

    /* The day this page was drawn for against the day the reader is having.
       They part every night, and a calendar that says nothing then is read as
       today's. Same clock as the now line: the machine's zone, never the
       reader's offset. */
    var drawn = document.getElementById('drawnfor');
    var moved = document.getElementById('daymoved');
    if (drawn && moved) {
      var here = new Date();
      var iso = '';
      try {
        iso = new Intl.DateTimeFormat('en-CA', zone ? { timeZone: zone } : {})
          .format(here);
      } catch (e) { iso = ''; }
      if (iso && iso !== drawn.getAttribute('data-day')) {
        moved.textContent = ' \u00b7 your clock says ' + iso
          + ', so the marks below belong to the day above';
      }
    }

    function place() {
      var text = clockIn(zone, new Date());
      var pct = nowPct(text);
      if (pct === null) { return; }
      lines.forEach(function (line) {
        line.style.left = pct + '%';
        line.hidden = false;
      });
      carets.forEach(function (caret) {
        caret.style.left = pct + '%';
        caret.textContent = text;
        caret.hidden = false;
      });
      /* The hour label the caret lands on gets out of the way. A solid
         background covers only the caret's own box, so at 16:03 the ruler read
         "1 16:03": the left half of the 15 survived and the pair looks like a
         single number. The tick under the label still marks the hour, so
         hiding the digits loses nothing.

         MEASURED, not estimated from a percentage. A threshold in percent has
         to be guessed against a label width in pixels and a column width that
         changes with the window, and the first guess was 4%, which was too
         small by half a digit at exactly the width this page is read at.

         Reset first, then measure: a hidden element reports a zero rectangle,
         so a loop that measures before clearing leaves every label it once hid
         hidden for the rest of the day. */
      scales.forEach(function (scale) {
        var caret = scale.querySelector('.nowmark');
        var labels = Array.prototype.slice.call(scale.querySelectorAll('span'))
          .filter(function (el) { return el !== caret; });
        labels.forEach(function (label) { label.hidden = false; });
        if (!caret || typeof caret.getBoundingClientRect !== 'function') { return; }
        var box = caret.getBoundingClientRect();
        if (!box.width) { return; }
        labels.forEach(function (label) {
          var mine = label.getBoundingClientRect();
          label.hidden = !(mine.right < box.left - 1 || mine.left > box.right + 1);
        });
      });
      /* ONE property for twenty-five tracks. The stylesheet defaults it to
         100%, so without this line nothing is shaded and the page says nothing
         about where the day has got to. */
      document.documentElement.style.setProperty('--now', pct + '%');
      if (note) { note.hidden = false; }
    }
    place();
    setInterval(place, 60000);
  })();

  /* Every absolute stamp on the page, turned into a distance. The stamp is
     what SHIPS, so a reader without scripting gets an answer instead of an
     empty line, and the exact moment stays on the cursor. Same arithmetic as
     the age in the header, deliberately: two ways of saying how old something
     is on one page will disagree the day one of them is fixed. */
  (function () {
    if (!document.querySelectorAll) { return; }
    var stamps = Array.prototype.slice.call(document.querySelectorAll('time.since'));
    if (!stamps.length) { return; }
    stamps.forEach(function (el) {
      if (!el.getAttribute('title')) { el.setAttribute('title', el.textContent); }
    });
    function age() {
      var now = Date.now();
      stamps.forEach(function (el) {
        var said = ageText(el.getAttribute('datetime'), now);
        if (said) { el.textContent = said; }
      });
    }
    age();
    setInterval(age, 30000);
  })();

  /* 3. Views, and progressive for the same reason as the two above it. The
        page ships with every section on it, one after another, so a reader
        without scripting gets the whole document and the bar at the top is a
        set of jump links into it. With scripting the bar becomes a switch and
        only the chosen view is on the page, which is what lets a framed
        neighbour have the whole window instead of a letterbox in the middle
        of this one. */
  (function () {
    if (!document.querySelector) { return; }
    var nav = document.querySelector('nav.tabs');
    if (!nav) { return; }
    var links = Array.prototype.slice.call(nav.querySelectorAll('a[data-view]'));
    var views = Array.prototype.slice.call(
      document.querySelectorAll('main.views > section.view'));
    /* One view is not a set of views. With nothing to switch to, the page
       stays the single document it already is rather than growing a control
       that can only re-select what is showing. */
    if (links.length < 2 || views.length < 2) { return; }
    document.documentElement.setAttribute('data-tabs', 'on');

    function show(id) {
      var known = false;
      views.forEach(function (view) { if (view.id === id) { known = true; } });
      /* Nothing is hidden until the target is known to exist. A hash aimed at
         a row inside a view, or at a view a later render dropped, must leave
         the page exactly as it was instead of blanking every section on it. */
      if (!known) { return false; }
      views.forEach(function (view) { view.hidden = view.id !== id; });
      links.forEach(function (a) {
        if (a.getAttribute('data-view') === id) {
          a.setAttribute('aria-current', 'page');
        } else { a.removeAttribute('aria-current'); }
      });
      try { localStorage.setItem('workload-view', id); } catch (e) { /* ditto */ }
      return true;
    }

    function fromHash() { return (location.hash || '').replace(/^#/, ''); }

    var start = fromHash();
    if (!start) {
      try { start = localStorage.getItem('workload-view') || ''; } catch (e) { start = ''; }
    }
    if (!start || !show(start)) { show(views[0].id); }

    nav.addEventListener('click', function (ev) {
      var a = ev.target && ev.target.closest ? ev.target.closest('a[data-view]') : null;
      if (!a) { return; }
      var id = a.getAttribute('data-view');
      if (!show(id)) { return; }
      ev.preventDefault();
      /* replaceState rather than assigning the hash: the address stays
         shareable without pushing a history entry per tab, and it fires no
         hashchange, so the view is switched once and not twice. */
      if (window.history && history.replaceState) {
        history.replaceState(null, '', '#' + id);
      } else { location.hash = id; }
      window.scrollTo(0, 0);
    });
    window.addEventListener('hashchange', function () {
      var id = fromHash();
      if (id) { show(id); }
    });
  })();
}
"""


@dataclass(frozen=True)
class Row:
    """One declaration and everything said about it. Built before rendering."""

    workload_id: str
    title: str
    purpose: str
    host: str
    kind: str
    runtime: str
    owner: str
    when: str
    retired: bool
    #: Whose sphere this run belongs to, or the word for "not decided".
    persona: str = ""
    #: What the machine calls it, asked of the backend, empty where a runtime
    #: names nothing.
    unit: str = ""
    #: The program this run calls, and whether it is this repository's own
    #: file, a copy of one, or a file that exists on one disk. Both come from
    #: the run that read the machine: the comparison needs a digest from over
    #: there and a file from over here, and a renderer has neither.
    program: str = ""
    program_where: str = ""
    #: What the run MAY DO, one line per level, from `model.rights_summary`.
    #: The same derivation the terminal prints: two summaries of one block
    #: drift, and the one that drifts is the one nobody runs.
    rights: tuple = ()
    #: Where the guard captures what this run SAID, one path per appointment.
    #: Named and never opened: whether a file is there is a question for a
    #: terminal, and this page answers none it did not measure.
    log: str = ""
    #: The last runs the machine wrote down, oldest first, as
    #: `(stamp, rc, verdict, state_key)`. Empty where nothing was read.
    strip: tuple = ()
    #: The recipient GROUPS a declaration names, as slugs. Never the people:
    #: a person slug is a name, and this page is readable by every device on
    #: the network it is served from.
    recipients: tuple = ()
    #: How many people the declaration names, counted rather than listed.
    people: int = 0
    findings: tuple = ()


def _esc(value) -> str:
    """Every value from a declaration or a machine goes through here."""
    return html_mod.escape("" if value is None else str(value), quote=True)


def _when(w) -> str:
    """The schedule as one short phrase, or why there is none."""
    kind = getattr(w.placement, "kind", "")
    if kind in model.CONTINUOUS_KINDS:
        return "continuous"
    s = getattr(w, "schedule", None)
    if s is None:
        return "-"
    # The appointments list first: a declaration that uses it carries no rrule
    # and no delivery_at, so the shorthand branch below answered "-" for a run
    # that fires twice a day. Measured on the published page on 2026-08-24.
    appointments = tuple(getattr(s, "appointments", ()) or ())
    if len(appointments) > 1:
        return "; ".join(
            f"{a.rrule} at {a.at}" if a.rrule and a.at else (a.rrule or a.at or "?")
            for a in appointments)
    if getattr(s, "rrule", None):
        at = f" at {s.delivery_at}" if getattr(s, "delivery_at", None) else ""
        return f"{s.rrule}{at}"
    if getattr(s, "every_sec", None):
        return f"every {s.every_sec}s"
    if getattr(s, "watch_paths", None):
        return f"{len(s.watch_paths)} path(s) watched"
    if getattr(s, "at", None):
        return f"once at {s.at}"
    return "-"


#: What the bar of neighbouring pages says about them, which is nothing.
#:
#: A tile with a colour, a tick or an age on it would be a measurement this
#: page never took: it has not opened any of those pages, it cannot know when
#: one was last written, and a picture is believed faster than a sentence and
#: is almost never diffed. That is rules/visual-output.md Gate 3, and the
#: cheapest way to obey it here is to say the quiet part out loud, because a
#: reader who sees a link on a dashboard assumes the dashboard vouches for it.
LINKS_NOTE = ("Links, not readings: this page has not opened any of them, so it "
              "says nothing about whether they are current or even there.")


def _links_html(links) -> str:
    """The bar of neighbouring pages, or nothing at all.

    `links` is a sequence of (label, href) pairs and comes from configuration,
    never from this file: the skill is core, and a host name or a path here
    would be one instance's data shipped to every other Bridge that pulls it.
    No configuration therefore means no bar, which is also the honest answer
    for a Bridge that publishes one page.
    """
    items = []
    for entry in links or ():
        label, href = str(entry[0]).strip(), str(entry[1]).strip()
        if not label or not href:
            continue
        items.append(f'<a href="{_esc(href)}">{_esc(label)}</a>')
    if not items:
        return ""
    return ('<nav class="links" aria-label="Other pages">' + "".join(items)
            + f'<span class="meta">{LINKS_NOTE}</span></nav>')


def _probed(header: str) -> bool:
    """Did anything ask a live source. Read off the sentence reconcile wrote.

    Deliberately a READ of that sentence rather than a second computation: two
    procedures answering the same question is how they come to disagree, and
    the sentence is the one a human sees.
    """
    text = (header or "").lower()
    if "0 of" in text and "probed" in text:
        return False
    return "probed" in text


def rows(rep, workloads) -> tuple:
    """Declarations first, with their findings attached. Never findings first."""
    by_id = {}
    for f in getattr(rep, "findings", ()) or ():
        by_id.setdefault(getattr(f, "workload_id", ""), []).append(f)
    program = getattr(rep, "programs", None) or {}
    out = []
    for w in workloads:
        found = sorted(by_id.get(w.id, ()),
                       key=lambda f: _SEVERITY_ORDER.get(_sev(f), 3))
        out.append(Row(
            workload_id=w.id,
            title=w.display_title,
            purpose=getattr(w, "purpose", ""),
            host=getattr(w.placement, "host", ""),
            kind=getattr(w.placement, "kind", ""),
            runtime=getattr(w.placement, "runtime", ""),
            owner=getattr(w.placement, "owner", ""),
            when=_when(w),
            persona=_persona(w),
            unit=_unit_name(w),
            log=_log_paths(w, getattr(rep, "state_dir", "")),
            program=program.get(w.id, ("", ""))[0],
            program_where=program.get(w.id, ("", ""))[1],
            rights=tuple(model.rights_summary(getattr(w, "raw", None))
                         if getattr(w, "raw", None) else ()),
            strip=tuple((getattr(rep, "history", None) or {}).get(w.id, ())),
            recipients=_recipient_groups(w),
            people=_recipient_people(w),
            retired=bool(getattr(w, "is_retired", False)),
            findings=tuple(found),
        ))
    return tuple(out)


#: What one recorded run looks like on the strip. Shape, never colour: the
#: page is read on a phone, in a dark room and on a projector, and a reader
#: who cannot tell two hues apart still counts crosses. Every one of them is
#: named in the legend under the table, because a shape nobody explains is a
#: decoration.
STRIP_SHAPES = {
    "ok": "●",        # filled circle: it ran and said nothing was wrong
    "failed": "✗",    # cross: the program said no
    "expired": "◑",   # half filled: a deadline cut it off part way
    "skipped": "–",   # dash: it declined to start, the last one still ran
}

#: What a verdict nobody in this table knows renders as. Not silence: a guard
#: that learns a fifth word must show up as an unknown mark rather than
#: disappear into the four this page happens to know.
STRIP_UNKNOWN = "?"

#: How a run that never ends is described above its own strip. Its guard
#: writes a line when the CHILD returns, and for this kind that is the moment
#: it died. Drawing those as runs would turn four crashes into four healthy
#: looking firings, and a daemon that has been up for weeks into an empty
#: row that reads as "nothing ever happened".
CONTINUOUS_STRIP_NOTE = "ends of runs, not runs: this kind only writes a line when it stops"


def reconcile_strip_max() -> int:
    """The cap the history was actually built with, ASKED of the module that
    applies it.

    A second number written into this sentence is a second derivation of the
    same fact, and the two drift the day somebody raises one of them. The page
    would then promise a span it does not show, which is worse than showing no
    number: a reader counts the marks and believes the sentence.
    """
    from engine import reconcile as reconcile_mod

    return int(reconcile_mod.STRIP_MAX)


def _recipient_groups(w) -> tuple:
    """The recipient GROUPS a declaration names, as slugs, in order.

    Groups and not people. A person is named in a declaration by a slug, and a
    slug of a person IS a name; this page is served over a network and read by
    whatever is on it. The role behind the slug would have to be looked up in
    the recipient files, which this engine deliberately never reads, and the
    roles there are not unique anyway.

    What the group answers is the question a reader actually has: which circle
    hears about this run. That it was DELIVERED is a different claim, and
    nothing on this page makes it.
    """
    seen = []
    for recipient in (getattr(getattr(w, "response", None), "recipients", None) or ()):
        slug = getattr(recipient, "mandant", "") or ""
        if slug and slug not in seen:
            seen.append(slug)
    return tuple(seen)


def _recipient_people(w) -> int:
    """How many people a declaration names. Counted, never listed."""
    return sum(1 for r in (getattr(getattr(w, "response", None), "recipients", None) or ())
               if getattr(r, "person", ""))


def _strip_html(row: Row) -> str:
    """The recorded runs of one declaration, oldest on the left.

    Every mark carries its own stamp, return value and verdict in a title, so
    the strip is scannable at a glance and readable in detail without a second
    page. The stamp is printed exactly as the machine wrote it, in UTC: the
    renderer reads no clock, and a local time computed here would be the
    renderer's local time and not the reader's.

    A run with two appointments produces ONE strip out of two files, so each
    mark also names the state key it came from. "The morning one failed" is a
    different sentence from "it failed".
    """
    continuous = row.kind in _CONTINUOUS_KINDS
    if not row.strip:
        if continuous:
            # For this kind an empty strip is the GOOD case, and an empty cell
            # reads as the opposite. It means the run has not stopped since the
            # trace was last cleared, which is the only thing its guard writes.
            return ('<span class="unreported">nothing recorded: this kind '
                    "writes a line when it stops</span>")
        return '<span class="unreported">nothing recorded</span>'
    marks = []
    for entry in row.strip:
        stamp = entry[0] if len(entry) > 0 else ""
        rc = entry[1] if len(entry) > 1 else None
        verdict = entry[2] if len(entry) > 2 else ""
        key = entry[3] if len(entry) > 3 else ""
        shape = STRIP_SHAPES.get(verdict, STRIP_UNKNOWN)
        detail = f"{stamp} rc={rc if rc is not None else 'unknown'} {verdict or 'no verdict'}"
        if key and key != row.workload_id:
            detail = f"{detail} ({key})"
        marks.append(f'<span class="mark mark-{_esc(verdict or "unknown")}" '
                     f'title="{_esc(detail)}">{shape}</span>')
    strip = f'<span class="strip">{"".join(marks)}</span>'
    if continuous:
        strip += f'<div class="meta">{_esc(CONTINUOUS_STRIP_NOTE)}</div>'
    return strip


def _recipients_html(row: Row) -> str:
    """Who was DECLARED, said in a way that cannot be read as delivery.

    The two are separate facts and they fail independently. A declaration names
    its recipients and nothing on the execution path reads them today, so a
    line that merely printed them next to a green mark would be this page
    claiming a delivery it never measured. The sentence therefore says which
    half it is, every time, rather than relying on a reader to remember.
    """
    if not row.recipients:
        return ""
    groups = ", ".join(_esc(g) for g in row.recipients)
    people = (f", {row.people} person(s) named and not listed here"
              if row.people else "")
    return ('<div class="hint"><span class="lead">declared</span>'
            f"reaches the group {groups}{people}. Declared, not delivered: "
            "nothing on this page measured whether a message arrived.</div>")


#: What an undeclared persona is called on the page. Absent and `_shared` are
#: DIFFERENT answers, and an empty cell reads as the second one, so the third
#: state gets a word of its own.
UNDECIDED_PERSONA = "undecided"

#: What a runtime that names nothing renders as. Not an empty cell: empty reads
#: as "the name is missing", and here there is deliberately none to have.
NO_UNIT = '<span class="unreported">no unit on the machine</span>'


#: How the two reserved answers read to somebody who did not write the schema.
PERSONA_WORDS = {
    "_shared": "shared",
    "_infrastructure": "infrastructure",
}


def _persona(w) -> str:
    """Whose run this is. Three states, never two.

    Added to every declaration on 2026-08-23 and shown by no view until
    2026-08-24, which is how a label nobody can see stays correct and useless.
    """
    value = str(getattr(w, "persona_ref", "") or "")
    if not value:
        return UNDECIDED_PERSONA
    return PERSONA_WORDS.get(value, value)


def _unit_name(w) -> str:
    """What the machine calls this run, ASKED of the backend that names it.

    Never rebuilt here. A second derivation of a name is exactly how a migrated
    run was filed as foreign software on 2026-08-24: four hand kept prefix
    lists, already disagreeing with each other. An unknown runtime is not a
    reason to guess, so it answers with nothing.
    """
    from .backends import BACKENDS, base as backend_base

    backend = BACKENDS.get(str(getattr(w.placement, "runtime", "")))
    if backend is None:
        return ""
    # EVERY unit, because a run with several appointments has several, and the
    # backend refuses (rightly) to answer with one of them. Measured on the
    # published page on 2026-08-24: the row said "no unit on the machine" while
    # both units were loaded and had just delivered. That sentence is reserved
    # for a runtime that names nothing at all, and a reserved word used for
    # something else stops meaning anything.
    appointments = backend_base.appointments_of(w)
    try:
        if len(appointments) > 1:
            names = [str(backend.unit_name(w, a) or "") for a in appointments]
            return "\n".join(n for n in names if n)
        return str(backend.unit_name(w) or "")
    except Exception:
        return ""


def _log_paths(w, state_dir: str) -> str:
    """Where this run's own output is captured, one path per appointment.

    Derived from two facts the page already has: the directory the report read
    the traces out of, and the state key the guard names its files after. NOT
    from the id, which is the trap the trace fell into first: a run with two
    appointments writes `<id>.<appointment>.out` and no file is called
    `<id>.out`, so printing the bare id would name a path that does not exist
    for exactly the runs whose logs are hardest to find.

    Empty without a configured directory. A path invented here would read
    exactly like one that was given.
    """
    from .backends import base as backend_base

    directory = str(state_dir or "").rstrip("/")
    if not directory:
        return ""
    keys = []
    for appointment in (backend_base.appointments_of(w) or (None,)):
        key = model.state_key(w, appointment)
        if key:
            keys.append(f"{directory}/{key}.out")
    return "\n".join(keys)


def _sev(f) -> str:
    value = getattr(f, "severity", "")
    return str(getattr(value, "value", value))


def _state(f) -> str:
    value = getattr(f, "state", "")
    return str(getattr(value, "value", value) or "")


def elsewhere(rep, workloads, machine_units=()) -> tuple:
    """What no declaration claims: `(on the machine, in the inventory, counted)`.

    Kept separate from the declarations, and then collapsed the way the terminal
    renderer collapses it. Never dropped: the number is itself a signal, and one
    that changes between two renders is the arrival of something nobody
    declared.

    `machine_units` is which of them to LIST instead of counting, as label
    prefixes out of the caller's configuration. Measured on one machine on
    2026-08-27: 1834 of its units belong to the operating system and about a
    hundred and forty to its owner. A page listing all of them is unreadable
    and a page counting all of them says nothing about the ones somebody put
    there themselves, so which is which is taken FROM configuration rather than
    guessed at from a name. Empty keeps everything counted, which is the honest
    answer for a bridge that has not said.
    """
    declared = {w.id for w in workloads}
    prefixes = tuple(str(p) for p in (machine_units or ()) if str(p))
    listed, inventory, counted = [], [], 0
    for finding in (getattr(rep, "findings", ()) or ()):
        name = getattr(finding, "workload_id", "")
        if name in declared:
            continue
        state = _state(finding)
        if state in COUNTED_ONLY_VALUES:
            if prefixes and name.startswith(prefixes):
                listed.append(finding)
            else:
                counted += 1
        elif state in INVENTORY_VALUES:
            inventory.append(finding)
        else:
            listed.append(finding)
    return tuple(listed), tuple(inventory), counted


def render(rep, workloads, *, generated_at: str, stale_after_min=None,
           hosts=(), poll_sec=None, links=(), panels=(), overview_label="",
           machine_units=(), group_by: str = "band") -> str:
    """One self-contained page. `generated_at` is passed in, never taken.

    A renderer that reads its own clock produces different bytes on every run,
    which makes a diff meaningless and a golden impossible.

    `stale_after_min` is the other half of that. On a terminal an age is free:
    you just ran the command. A page on a web server is read hours later, looks
    exactly the same, and is believed. The renderer cannot know when it will be
    read, so it states no freshness at all; it publishes the moment in a form a
    machine can parse and lets the reader's own clock decide. A threshold is
    honoured only when the caller declares one, because without a refresh
    cadence there is no line to draw and inventing one is a number nobody chose.

    `hosts` is which machines were actually reconciled. It is not a filter and
    never removes a row: it is what lets a silence about a run placed somewhere
    else be explained instead of reported as an unexplained one. Empty means no
    machine was excluded, so there is nothing to explain.

    `links` is the bar of neighbouring pages, as (label, href) pairs out of the
    caller's configuration. Empty renders nothing, and nothing is the normal
    case: this page has never opened any of them, so the bar navigates and
    states nothing else. See `LINKS_NOTE`.

    `machine_units` is which of the machine's undeclared units to list rather
    than count, as label prefixes. See `elsewhere`: on a machine carrying two
    thousand of them, listing all and counting all are equally useless, and
    which ones belong to the reader is not something this skill may decide by
    looking at a name.

    `overview_label` names the first tab. Every other tab is named by the
    configuration that asked for it, so without this one the shell would carry
    exactly one word the caller cannot choose, in whatever language this file
    happens to be written in. Empty keeps the default.

    `panels` frames neighbouring pages instead of linking them, same shape and
    same source, and each one becomes a VIEW of its own under the shared bar at
    the top. A frame shows the neighbour's own rendering under the neighbour's
    own stamp, so no figure is adopted and nothing is drawn twice; see
    `PANELS_NOTE` and `_panels_html` for why it is a view and not a footer.
    """
    asked = tuple(str(h) for h in (hosts or ()) if str(h))
    declared = rows(rep, list(workloads))
    other, inventory, unclaimed = elsewhere(rep, list(workloads), machine_units)
    probed = _probed(getattr(rep, "header", ""))
    views = _views(panels)
    # One zone or none. The upright "now" line is drawn by the script from
    # THIS, never from the reader's own offset: the axis is the machine's day.
    zones = day_zones(list(workloads))
    zone = zones[0] if len(zones) == 1 else ""
    # WHICH DAY this page is drawn for. Taken from the moment the caller passed
    # in and moved into the declarations' own zone, because the axis is the
    # machine's day and `generated_at` carries the publisher's offset. Not from
    # a clock here: a renderer that reads one produces different bytes on every
    # run. The page NAMES the day it drew, and the script says so when the
    # reader's own day has moved on, because a calendar that silently belongs
    # to yesterday is the one mistake this whole surface exists to avoid.
    on = _drawn_for(generated_at, zone)

    body = [
        "<!doctype html>",
        f'<html lang="en" data-probed="{"true" if probed else "false"}"'
        + (f' data-zone="{_esc(zone)}"' if zone else "")
        + (f' data-stale-after-min="{int(stale_after_min)}"'
           if stale_after_min else "")
        # Absent unless declared, exactly like the staleness limit above: with
        # no cadence the page still ages honestly, it just never asks for a
        # newer copy.
        + (f' data-poll-sec="{int(poll_sec)}"' if poll_sec else "") + ">",
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Workloads</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        # The bar that stays. It carries the mark, the views and the one
        # control this page has; a reader who has scrolled into the table can
        # still reach another view without going back to the top for it.
        '<header class="topbar"><span class="mark"><span class="dot"></span>'
        "Workloads</span>" + _tabs_html(views, overview_label or OVERVIEW_LABEL)
        + '<button id="theme" type="button">theme</button></header>',
        '<main class="views">',
        f'<section class="view" id="{OVERVIEW_ID}"><div class="wrap">',
        "<h1>Workloads</h1>",
        '<p class="lede">One declaration per run. The declaration is the source '
        "of truth; the unit on the machine is an artifact rebuilt from it.</p>",
        # The absolute moment stays in the text, so a reader with scripting
        # off still sees a date; the attribute is the half a clock can read.
        f'<p class="stamp">rendered <time id="stamp" datetime="{_esc(generated_at)}">'
        f'{_esc(generated_at)}</time><span id="age"></span></p>',
    ]
    # WHICH DAY the calendar below belongs to. A grid of hours belongs to no
    # day and a grid of numbers to no month, and this page is read hours after
    # it was written: without the sentence, yesterday's calendar and today's
    # are the same picture. The script adds the reader's own day when the two
    # have parted, which is the case the sentence exists for.
    if on is not None:
        body.append(
            f'<p class="stamp" id="drawnfor" data-day="{on.isoformat()}">'
            f'drawn for {on.strftime("%A %d %B %Y")}'
            + (f" in {_esc(zone)}" if zone else "")
            + '<span id="daymoved"></span></p>')

    # Above the banners, because navigation belongs at the top of a page and
    # below the moment it was written, because that moment is about THIS page
    # and the bar is about other ones. The bar in the shell above switches
    # views; this one leaves for a page nothing here frames.
    bar = _links_html(links)
    if bar:
        body.append(bar)

    # In service and history are two questions. A board that opens with the
    # runs somebody switched off makes a reader count rows to learn how much
    # runs here and get the wrong number: one migrated service showed as four.
    in_service = [row for row in declared if not row.retired]
    history = [row for row in declared if row.retired]

    # The counts first, because the question somebody opens this page for is
    # whether anything needs them, and that answer should not have to be
    # assembled by eye out of twenty-three rows.
    if declared:
        body.append(_stats_html(in_service, history))

    header = getattr(rep, "header", "") or ""
    if header:
        body.append(f'<p class="banner">{_esc(header)}</p>')
    if not probed:
        body.append(
            '<p class="banner"><strong>Nothing on this page was asked of a live '
            "source.</strong> These are the declarations and what discovery "
            "found, not proof that anything is running.</p>")

    # Rendered only where a cadence was declared, so "no threshold, no
    # verdict" is structural rather than a promise the script keeps. The
    # wording avoids naming a moment: the reader's clock unhides it, and
    # only that clock knows how long ago this was.
    if stale_after_min:
        body.append(
            '<p class="banner" id="stale" hidden><strong>This page is older '
            "than the interval it is refreshed on.</strong> Whatever stopped "
            "may be the refresh rather than the runs, so read every row below "
            "as history until the moment above moves.</p>")
    else:
        # No cadence still means no verdict, and that rule is not being
        # weakened here. What is added is the FACT that there is no cadence,
        # which needs no threshold and invents nothing.
        #
        # Measured on 2026-08-24: this page was published once by hand and
        # nothing refreshed it. Eight hours later its reader opened it, read
        # the count under "In service", and took it for the present. The age
        # was on the page the whole time, in small grey type, in brackets. It
        # lost to a headline number that reads as an inventory. Saying the
        # quiet part out loud costs one sentence.
        body.append(
            '<p class="banner" id="norefresh"><strong>Nothing refreshes this '
            "page.</strong> It was written once, at the moment above, and no "
            "cadence was declared for it. Every count and every state below "
            "is what was true then, not what is true now.</p>")

    # BEFORE the controls and before the table, because the question somebody
    # opens an operations page with is "does anything here need me", and an
    # inventory is not an answer to it. Every sentence in it is already on the
    # page further down; what is new is that the hint each finding carries,
    # which is this skill's own instruction, reaches a reader at all.
    if declared:
        body.append(_open_html(in_service))

    # And the two facts that make a silence readable. See `_machines_html`.
    machines = _machines_html(rep, asked)
    if machines:
        body.append(machines)

    # Above the calendar and the table, because it governs both and a control
    # below the thing it controls is found last.
    facets = _facets_html(in_service)
    if facets:
        body.append(facets)

    # ONE section, and one row per run inside it. The day used to be an axis of
    # its own above this table, which put every declaration on the page twice
    # with half of what is known about it in each place.
    by_lane = {lane.workload_id: lane
               for lane in lanes(rep, list(workloads), on=on)}
    # Carried, never derived. Two runs belong to one system because both say so;
    # guessing it from a shared name prefix is wrong on the real data, where a
    # puller and the agent it feeds shared no prefix in two cases out of three.
    systems = {w.id: getattr(w, "system", None) for w in workloads}

    body.append('<section class="block"><p class="eyebrow">Declarations</p>')
    # The count is an element, not a literal, because a filter changes how many
    # rows a reader can see and a heading that keeps saying the whole number
    # while showing three rows is the same lie as a stale page.
    body.append(f'<h2>In service (<span id="shown">{len(in_service)}</span>)</h2>')
    body.append('<p class="lede">One row per run: what it is, where it sits in '
                "the machine's own day, how its last runs went, and the "
                "verdict. A mark never relies on colour alone. Open a row for "
                "the rest.</p>")
    # Declared widths, because four automatic columns share a page by content
    # and two of these hold one short token each: the identifier column was
    # squeezed to a quarter of the measure and wrapped its purpose over four
    # lines while the others floated in white. Hints rather than a fixed
    # layout, so a history longer than its column widens it instead of being
    # clipped, which would drop recorded runs without saying so.
    body.append('<div class="scroll"><table class="runs">'
                '<colgroup><col style="width:26%"><col style="width:36%">'
                '<col style="width:22%"><col style="width:16%"></colgroup>'
                '<thead><tr><th data-sort="id">id</th>'
                '<th data-sort="when">when it runs</th>'
                '<th data-sort="recorded">recorded</th>'
                '<th data-sort="state">state</th>'
                "</tr></thead>")
    for key, title, here, with_scale in _sections(in_service, by_lane,
                                                  systems, group_by):
        # By the clock inside each section, not by name: see `_order_key`.
        here.sort(key=lambda row: _order_key(by_lane.get(row.workload_id),
                                             row.workload_id))
        body.append(_group_head_html(key, title, len(here), on,
                                     with_scale=with_scale))
        for row in here:
            body.append(_row_html(row, asked, by_lane.get(row.workload_id), on,
                                  section=key))
    if not in_service:
        body.append('<tbody><tr><td colspan="4" class="meta">no declaration is '
                    "in service here yet</td></tr></tbody>")
    body.append("</table></div>")
    body.append(_legend_html([by_lane[row.workload_id] for row in in_service
                              if row.workload_id in by_lane], on))
    # A shape nobody explains is a decoration. The words are the guard's own
    # four verdicts, not this page's summary of them.
    if in_service:
        # The ground the marks are drawn on, accounted for where it is drawn.
        # A shading and a rule nobody explains are decoration, and this page
        # may not carry decoration a reader can mistake for data.
        body.append('<p class="meta">the day: every track is one whole day, 00 '
                    "to 24, ruled every three hours and more heavily every "
                    "six. The hours before 06 and after 18 stand on a ground "
                    "of their own so the middle of the day is found without "
                    "counting ticks. That shading says nothing about any "
                    "run.</p>")
        if zone:
            body.append(
                '<p class="meta" id="nownote" hidden>the upright line is now, '
                f"in {_esc(zone)}, which is the zone these declarations state, "
                "and the ground behind it is the part of the day that has not "
                "happened yet. Your browser computes both and keeps them "
                "moving, so they are the only things here that are not as old "
                "as the page.</p>")
        elif len(zones) > 1:
            body.append(
                '<p class="meta">no line marks now: these declarations state '
                f"{len(zones)} different time zones ({_esc(', '.join(zones))}), "
                "and one upright line across all of them would be the right "
                "moment for at most one.</p>")
        else:
            body.append(
                '<p class="meta">no line marks now: no declaration here states '
                "a time zone, and this axis is the machine's day rather than "
                "the reader's.</p>")
    legend = " · ".join(f"{shape} {word}" for word, shape in STRIP_SHAPES.items())
    body.append(f'<p class="meta">recorded: what the machine wrote down, '
                f"oldest on the left, at most {reconcile_strip_max()} per "
                f"declaration. {legend} · {STRIP_UNKNOWN} a verdict this page "
                "does not know. Hover a mark for its stamp and return value. "
                "Times in the marks are UTC, as the machine wrote them.</p>")

    # Said once, under the table, rather than per row: it is one property of
    # every path above, and thirty repetitions of it would be thirty lines
    # nobody reads. Only when there is a path to say it about.
    if any(row.log for row in in_service):
        body.append('<p class="meta">log: where the guard captures what a run '
                    "said, one file per appointment, beside the trace these "
                    "marks come from. This page names the paths and did not "
                    "open them: whether a file is there, and what is in it, is "
                    "a question for a terminal.</p>")

    # Counted, never dropped: a declaration must not be quietly lost by being
    # retired, and the names are what let a reader recognise the ones they
    # retired themselves.
    if history:
        names = ", ".join(_esc(row.workload_id) for row in history[:8])
        more = f" and {len(history) - 8} more" if len(history) > 8 else ""
        body.append(f'<p class="meta">{len(history)} retired declaration(s), kept '
                    f"as history and not shown above: {names}{more}.</p>")
    body.append("</section>")

    # Two headings out of one bucket. Both are entries in the same file that
    # name nothing on the machine, and that is where the likeness ends: one is
    # a record nobody maintained, the other is a decision somebody wrote down.
    # Measured on the live page on 2026-08-27, nine of sixteen rows were the
    # second kind, filed under a heading that said they had drifted and advised
    # deleting them.
    decided = [f for f in inventory if _state(f) == DECIDED_VALUE]
    drifted = [f for f in inventory if _state(f) != DECIDED_VALUE]
    if drifted:
        body.append('<section class="block">'
                    '<p class="eyebrow">Drift</p>'
                    f"<h2>Inventory entries that name nothing ({len(drifted)})</h2>")
        body.append('<p class="lede">These live in <code>infra/remotes/&lt;host&gt;'
                    ".yaml</code> and are not runs. Each names something that "
                    "neither a declaration nor the machine knows, so the file has "
                    "drifted away from both.</p>")
        body.append(_finding_table(drifted))
        body.append("</section>")

    if decided:
        body.append('<section class="block">'
                    '<p class="eyebrow">Decided</p>'
                    f"<h2>Absent on purpose ({len(decided)})</h2>")
        body.append('<p class="lede">Also entries in <code>infra/remotes/'
                    "&lt;host&gt;.yaml</code> that name nothing the machine "
                    "runs, and each of them says so itself, with a date and a "
                    "reason. Nothing to do here: the entry is the record of "
                    "the decision, and the reason is the answer to the "
                    "question a reader arrives with. This run did not check "
                    "whether the reason still holds.</p>")
        body.append(_finding_table(decided))
        body.append("</section>")

    if other or unclaimed:
        body.append('<section class="block">'
                    '<p class="eyebrow">Context</p>'
                    # Both numbers, because they are two different facts and
                    # a single total is read as the size of the list under it.
                    # Nine hundred and seventy four over thirty two rows is the
                    # same mismatch the section headings inside the table had.
                    f"<h2>On the machine, undeclared ({len(other)} named, "
                    f"{unclaimed} counted)</h2>"
                    if other and unclaimed else
                    f"<h2>On the machine, undeclared ({len(other) + unclaimed})</h2>")
        body.append('<p class="lede">What this run found on the machine that no '
                    "declaration claims. Context, not the subject: this skill "
                    "never touches any of them, and not one of them has a "
                    "deadline, an owner or a guard here. They are on the page "
                    "so it shows the whole machine and not only the managed "
                    "part of it. <code>workload adopt &lt;unit&gt;</code> is "
                    "how one of them stops being context: it writes a "
                    "declaration from what the machine already runs, and from "
                    "then on this page answers for it.</p>")
        if other:
            body.append(_units_grid_html(other))
        if unclaimed:
            body.append(
                f'<p class="banner">And {unclaimed} further unit(s) that no '
                "declaration claims, counted rather than listed. Most of them "
                "belong to the operating system; the number is the signal, and "
                "a run of <code>reconcile --verbose</code> names them.</p>")
        body.append("</section>")

    body.append(
        "<footer>Generated by the <code>workload</code> skill. Colours and type "
        "follow the repository's DESIGN.md; nothing is loaded from anywhere.</footer>")
    body.append("</div></section>")
    body.append(_panels_html(views))
    body.append("</main>")

    body.append(f"<script>{_JS}</script>")
    body.append("</body></html>")
    return "\n".join(body) + "\n"


#: Which kinds are a continuous presence rather than an appointment.
#:
#: ASKED of the model, not restated. It stood here as its own literal tuple
#: with the same two words, which is one list carried twice: the day a third
#: continuous kind is added, the model refuses its deadline and the page keeps
#: drawing it as an appointment, and nothing anywhere says the two disagree.
#: Exactly the shape of mistake this skill was written to catch.
_CONTINUOUS_KINDS = model.CONTINUOUS_KINDS

#: Weekday numbers as `weekdays_of` returns them (launchd: 0 is Sunday).
_WEEKDAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

#: Every shape the calendar can draw, and the sentence that explains it. One
#: list, so a mark can never appear on the axis without a reader being told
#: what it means: the legend is generated from the same tuple the lanes use.
SHAPES = (
    ("missed", "hollow ring: an appointment that passed and left no trace, the gap"),
    ("due", "dashed ring: the next appointment, and nothing says it is late"),
    ("unknown", "dotted ring: an appointment nothing here can judge, so this says "
                "nothing either way"),
    ("elsewhen", "faint ring: an appointment of this run that does not fall on "
                 "the day drawn, kept so a weekly job is not an empty lane on "
                 "the six days it does not fire"),
    ("trace", "diamond: the last run the machine's own trace records"),
    ("trace-failed", "filled square: that run came back with an error"),
)

# The words follow the drawing, and the drawing changed on 2026-08-27: a
# cadence used to be a stripe repeating every fourteen pixels, identical for
# every five minutes and for every hour, and a reader counted those marks as
# firings. It is a thin rail now, present all day and claiming no moment.
BANDS = (
    ("cadence", "a rail with a cap at each end: a cadence, running from one end "
                "of the day to the other at no particular o'clock"),
    ("continuous", "filled band: meant to be up the whole time"),
)


@dataclass(frozen=True)
class Lane:
    """One declaration on the 24 hour axis, or the reason it is not on it."""

    workload_id: str
    purpose: str
    label: str = ""
    #: Every declared appointment of this run, in declaration order. A scalar
    #: here placed the first one and dropped the rest WITHOUT SAYING SO, so a
    #: run answering twice a day drew exactly like a run answering once and the
    #: picture contradicted the unit files. Gate 3: anything that cannot be
    #: placed says so, and nothing is quietly left out.
    appointments: tuple = ()
    at_pct: float | None = None
    #: Where this run sorts inside its own section: the first appointment as a
    #: share of the day, or the cadence in seconds. Alphabetical order put a
    #: 05:40 job under a 10:00 one and a 3600s cadence above a 300s one, so the
    #: only section on the page that IS a calendar did not read as one. None
    #: where a run has no order of its own; those keep the name for a key,
    #: which is at least stable between renders.
    order: float | None = None
    shape: str = ""
    band: str = ""
    days: str = ""
    note: str = ""
    #: The last run the machine's trace records, placed on the same axis. A
    #: second mark rather than a property of the first, because "the schedule is
    #: kept" and "something ran" are different claims with different sources.
    trace_pct: float | None = None
    trace_shape: str = ""
    trace_label: str = ""
    #: The moment of that trace, as the host wrote it. The label above is a
    #: SENTENCE and cannot be aged by a clock; this is the machine readable
    #: half, so the page can say "3 min ago" in the reader's own present
    #: instead of only printing an hour that has to be compared by hand.
    trace_at: str = ""
    #: The seven weekdays, Sunday first, as `weekdays_of` numbers them: True
    #: where this run fires. A run with no weekday constraint fires on all
    #: seven, which is a fact and not a default.
    week: tuple = ()
    #: The days of the drawn month this run is due on, as day numbers. Empty
    #: where nothing could be placed, or where the page was drawn without a
    #: date to place it in.
    month: tuple = ()
    #: The days the machine actually WROTE A LINE on, as `YYYY-MM-DD` in the
    #: declarations' own zone. Read from the recorded strip, which is capped,
    #: so its absence on an older day says nothing. That cap is stated in the
    #: legend rather than implied here.
    ran: frozenset = frozenset()


@dataclass(frozen=True)
class Mark:
    """One appointment, placed. `at_pct` is a share of the day, not a time."""

    at_pct: float
    shape: str
    label: str
    days: str = ""
    note: str = ""
    #: The weekdays this appointment fires on, as `weekdays_of` returns them
    #: (0 is Sunday). EMPTY MEANS EVERY DAY, which is the same convention that
    #: function uses, and the reason the field is asked through `fires_on`
    #: rather than read directly: an empty tuple read as "never" would empty
    #: the calendar of every daily run.
    weekdays: tuple = ()

    def fires_on(self, weekday: int | None) -> bool:
        """Whether this appointment happens on that weekday. Unknown day: yes.

        A page drawn without a date cannot filter by one, and drawing nothing
        would be a stronger claim than drawing everything.
        """
        if weekday is None or not self.weekdays:
            return True
        return weekday in self.weekdays


def _and_list(parts) -> str:
    """`a` · `a and b` · `a, b and c`. An ordinary English list.

    Six appointments joined by "and" six times is not a schedule a reader
    finishes: measured on the live page, one run read "06:00 and 09:00 and
    12:00 and 15:00 and 18:00 and 21:00" and the eye simply left.
    """
    parts = [str(p) for p in parts if str(p)]
    if len(parts) < 3:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _appointment_shape(workload_id: str, findings) -> tuple:
    """(shape, hint) for the ring at a declared time. Never given the traces.

    Whether a schedule is being KEPT is a verdict `reconcile` already takes,
    holding the cadence, the clock skew and the machine's uptime. Deciding it
    here from a trace stamp would be a second verdict, and the two would part
    company on the day it mattered. It cost a real lie the first time: the only
    trace of a 07:20 job came from a verification run at 15:54, and a mark that
    asked "is there a trace at all" put that answer on the 07:20 appointment.
    """
    states = {_state(f) for f in (findings or ())
              if getattr(f, "workload_id", "") == workload_id}
    if model.WorkloadState.overdue.value in states:
        return "missed", "an expected run left no trace"
    if states & {model.WorkloadState.unknown.value,
                 model.WorkloadState.not_provisioned.value,
                 model.WorkloadState.absent.value}:
        return "unknown", "nothing here can judge this schedule"
    return "due", "nothing says this schedule is behind"


def _trace_mark(workload_id: str, rep, zone) -> tuple:
    """`(percent, shape, label, stamp)` for the last run, or the reason there is none.

    The STAMP comes back even where the mark cannot be placed. Those are two
    different failures: a page that cannot draw a run on the axis can still say
    how long ago it ran, and dropping the moment with the position throws away
    the more useful of the two.

    The stamp is UTC because that is how the host wrote it, and the axis is the
    machine's own day. The offset therefore comes from the zone the declaration
    states, which `backends.base.ensure_local_timezone` has already checked
    against the host. Without one the mark is not placed: guessing the offset
    puts every diamond hours out, and silently.
    """
    run = (getattr(rep, "runs", None) or {}).get(workload_id)
    if not run:
        return None, "", "", ""
    when, rc = run
    shape = "trace" if rc in (0, None) else "trace-failed"
    if not zone:
        return None, "", (f"last run {when}, not placed on the axis: the "
                          "declaration states no time zone, and the stamp is "
                          "UTC"), when
    try:
        from datetime import datetime, timezone as _tz
        from zoneinfo import ZoneInfo
        moment = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
        local = moment.astimezone(ZoneInfo(str(zone)))
    except Exception as exc:                                   # noqa: BLE001
        return None, "", f"last run {when}, not placed on the axis: {exc}", when
    minutes = local.hour * 60 + local.minute
    return (round(minutes / 14.4, 4), shape,
            f"last run {local.strftime('%H:%M')} local ({when})", when)


def _month_days(week: tuple, on) -> tuple:
    """Which day numbers of `on`'s month a run with these weekdays is due on.

    Derived from the weekday set and a calendar, never from a recurrence
    engine: the set itself came out of `weekdays_of`, which refuses everything
    outside the translated subset, so a month drawn from it inherits that
    refusal instead of inventing a rule of its own.
    """
    import calendar
    from datetime import date

    if on is None or not any(week or ()):
        return ()
    total = calendar.monthrange(on.year, on.month)[1]
    return tuple(
        day for day in range(1, total + 1)
        # `weekday()` counts Monday as 0; `weekdays_of` counts Sunday as 0.
        if week[(date(on.year, on.month, day).weekday() + 1) % 7])


def _ran_days(workload_id: str, rep, zone) -> frozenset:
    """The days the machine wrote a line on, in the declarations' own zone.

    From the recorded strip, which is where the stamps already are. It is
    CAPPED at a fixed number of runs per declaration, so the absence of a day
    older than the cap says nothing at all; the legend says so, because a
    calendar that quietly stops filling in days looks exactly like a machine
    that quietly stopped running.
    """
    from datetime import datetime, timezone as _tz

    strip = (getattr(rep, "history", None) or {}).get(workload_id, ())
    if not strip or not zone:
        return frozenset()
    try:
        from zoneinfo import ZoneInfo

        here = ZoneInfo(str(zone))
    except Exception:
        return frozenset()
    days = set()
    for entry in strip:
        stamp = entry[0] if isinstance(entry, (list, tuple)) and entry else ""
        try:
            moment = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            continue
        days.add(moment.replace(tzinfo=_tz.utc).astimezone(here).date().isoformat())
    return frozenset(days)


def lanes(rep, workloads, on=None) -> tuple:
    """One lane per declaration in service, placed the way the unit file is.

    The hour comes from `backends.base.start_of`, the same function the unit is
    rendered from, so the drawing and the machine cannot disagree about when a
    job fires. Everything it refuses to place is refused here too, by its own
    sentence: an empty lane reads as a job with nothing scheduled, which is a
    different statement from one that cannot be drawn.

    `on` is the DATE the page is drawn for, and it is passed in for the same
    reason `generated_at` is: a renderer that reads its own clock produces
    different bytes on every run. Without it the week and the month stay empty
    and the day scale filters nothing, which is the honest answer for a page
    that was not told which day it is.
    """
    out = []
    findings = getattr(rep, "findings", ()) or ()
    for w in workloads:
        if w.is_retired:
            continue
        kind = w.placement.kind
        shape, hint = _appointment_shape(w.id, findings)
        zone = getattr(w.schedule, "timezone", None) if w.schedule else None
        trace_pct, trace_shape, trace_label, trace_at = _trace_mark(w.id, rep, zone)
        # EVERY DAY, and stated rather than defaulted: a run with no weekday
        # constraint is due on all seven, and so is anything that keeps a beat
        # or is simply up. A week drawn empty for those would read as "never".
        every_day = (True,) * 7
        common = {"workload_id": w.id, "purpose": w.display_title,
                  "trace_pct": trace_pct, "trace_shape": trace_shape,
                  "trace_label": trace_label, "trace_at": trace_at,
                  "ran": _ran_days(w.id, rep, zone)}
        if kind in _CONTINUOUS_KINDS:
            out.append(Lane(**common, band="continuous", label="continuously",
                            note=trace_label or hint,
                            week=every_day, month=_month_days(every_day, on)))
            continue
        if kind == "interval":
            every = getattr(w.schedule, "every_sec", None)
            out.append(Lane(**common, band="cadence",
                            order=float(every) if every else None,
                            label=f"every {int(every)}s" if every else "on a cadence",
                            note=trace_label or hint,
                            week=every_day, month=_month_days(every_day, on)))
            continue
        if kind == "watch":
            out.append(Lane(**common, band="cadence" if getattr(w.schedule, "every_sec", None) else "",
                            label="on a path change",
                            note="fires when a path changes, so it has no place on a clock"))
            continue
        # BOTH calls, under one refusal. `weekdays_of` refuses independently of
        # `starts_of`: a recurrence the second accepts can still be one this
        # backend cannot express in weekdays, and guarding only the first let
        # that refusal escape the renderer as an exception. One such
        # declaration then took the WHOLE PAGE down instead of costing itself a
        # sentence, which is the opposite of what this block is for. Found on
        # the fixture corpus on 2026-08-27, by rendering all of it at once.
        try:
            placed = backend_base.starts_of(w)
            marks = []
            for appointment, hour, minute, shift in placed:
                days = backend_base.weekdays_of(w, shift, appointment)
                marks.append(Mark(
                    at_pct=round((hour * 60 + minute) / 14.4, 4),
                    shape=shape,
                    label=f"{hour:02d}:{minute:02d}",
                    days=" ".join(_WEEKDAY_NAMES[d % 7] for d in days) if days else "",
                    weekdays=tuple(sorted({d % 7 for d in days})),
                    note="; ".join(p for p in (appointment.name, hint, trace_label) if p)))
        except errors.WorkloadError as refusal:
            out.append(Lane(**common, note=f"cannot be placed on the axis: {refusal}"))
            continue
        if not placed:
            out.append(Lane(**common,
                            note="cannot be placed on the axis: no appointment"))
            continue
        # The scalar fields stay, carrying the FIRST mark, so a reader written
        # before this change keeps working on the ordinary single-appointment
        # run instead of silently seeing nothing.
        # The UNION over the appointments: a run whose morning fires on
        # weekdays and whose evening fires on Sundays is due on both, and a
        # week showing only the first would be a drawing of half a schedule.
        week = tuple(any(m.fires_on(day) for m in marks) for day in range(7))
        out.append(Lane(
            **common, shape=shape, appointments=tuple(marks),
            at_pct=marks[0].at_pct, order=marks[0].at_pct,
            label=_and_list([m.label for m in marks]),
            days=marks[0].days, week=week, month=_month_days(week, on),
            note="; ".join(p for p in (hint, trace_label) if p)))
    return tuple(out)


#: The four shapes a day can have, in the order a reader wants them: the runs
#: that sit at an o'clock first, because that is what a calendar is for; then
#: the ones that keep a beat without one; then the ones that are simply up;
#: then the ones nothing could place, which are named rather than dropped.
#:
#: They are SECTIONS OF THE TABLE now, not a second list beside it. Until
#: 2026-08-27 the day was drawn above the runs as its own axis, so every
#: declaration appeared twice on one page: once as a lane and once as a row,
#: each carrying half of what is known about it. The reader's question was the
#: right one, why is everything here twice, and merging them removes a whole
#: class of defect with it: a lane can no longer be left standing for a row a
#: filter took away, because they are the same element.
LANE_GROUPS = (
    ("", "At an o'clock"),
    ("cadence", "On a cadence, at no particular o'clock"),
    ("continuous", "Meant to be up the whole time"),
    ("unplaced", "Not on the day"),
)

#: The axes the table can be grouped by. `band` answers WHEN a run fires,
#: `system` answers WHAT it is a part of. Both are real operating questions and
#: neither answers the other, which is why this is a choice at render time and
#: not a migration: a fleet of pullers reads best by clock, a fleet of
#: agent-plus-tunnel-plus-puller stacks reads best by system.
#:
#: `band` is the default and its output is byte for byte the page this drew
#: before a second axis existed. An axis that quietly changed the old page
#: would make every reader re-learn a page they already knew.
GROUP_BY = ("band", "system")

#: The two sections at the end of the system axis, and they are two on purpose.
#: `_standalone` is a run somebody looked at and found to stand alone, so the
#: advice under it is "nothing to do". The other is a run nobody classified,
#: where the advice is "decide". Folding them together hides the second behind
#: the first, and the second is the only one that asks for anything.
SYSTEM_ALONE = "_standalone"
SYSTEM_UNDECIDED = "_undecided"

SYSTEM_TAIL = (
    (SYSTEM_ALONE, "On their own"),
    (SYSTEM_UNDECIDED, "No system named yet"),
)


def _sections(rows, by_lane, systems, axis):
    """Every section of the table as (key, title, rows, with_scale), in order.

    The key is what BOTH the heading and its rows carry as `data-band`, and
    that is not a leftover name: the script pairs a heading with its rows by
    comparing exactly that attribute, so a heading whose key differs from its
    rows' hides itself the moment anything is filtered. Handing both out of one
    place is what makes the two impossible to disagree about.

    `with_scale` travels per section instead of being re-derived from the key.
    On the band axis exactly one section holds runs that are not on the day; on
    the system axis any section can, and an hour ruler over rows that hold a
    sentence instead of a position invites the reading that they are somewhere
    on it.

    Empty sections are not returned. A heading with no rows under it is a count
    of runs the reader cannot see.
    """
    if axis not in GROUP_BY:
        raise ValueError(f"unknown grouping axis {axis!r}: expected one of "
                         f"{', '.join(GROUP_BY)}")

    def placeable(here):
        return any(_band_of(by_lane.get(row.workload_id)) != "unplaced"
                   for row in here)

    out = []
    if axis == "band":
        for band, title in LANE_GROUPS:
            here = [row for row in rows
                    if _band_of(by_lane.get(row.workload_id)) == band]
            if here:
                out.append((band or "clock", title, here, band != "unplaced"))
        return out

    # The system axis. Named systems in NAME order and never in size order: a
    # page somebody reads every morning must not reshuffle itself the day a
    # system grows a fourth member.
    named = sorted({(systems.get(row.workload_id) or "")
                    for row in rows} - {"", SYSTEM_ALONE})
    for name in named:
        here = [row for row in rows if systems.get(row.workload_id) == name]
        if here:
            out.append((name, name, here, placeable(here)))
    for key, title in SYSTEM_TAIL:
        want = SYSTEM_ALONE if key == SYSTEM_ALONE else None
        here = [row for row in rows
                if (systems.get(row.workload_id) or None) == want]
        if here:
            out.append((key, title, here, placeable(here)))
    return out


def _marks_html(lane, on=None) -> str:
    """Every mark this lane carries, or empty where it carries none.

    ONE function, asked by the track that draws them AND by the grouping that
    files the row, so the picture and the heading above it cannot come to
    different answers about whether a run is on the day at all.

    `on` is the DAY DRAWN, and it decides how an appointment that does not
    happen on it is marked. Measured on the live page on 2026-08-27, a
    Thursday: a run that fires on Sundays carried a ring at 10:00 whose hover
    read "nothing says this schedule is behind", identical in every respect to
    a run that really was due that morning. The row's text cell said "10:00
    Sun", so the page was not silent; the DRAWING asserted an appointment
    today, and the drawing is the reason the axis exists. The verdict logic
    never had this wrong, because `previous_due` reads the same weekday set:
    the judgement knew, the picture did not.

    It is drawn rather than dropped. A Sunday run with an empty Thursday reads
    as a run with nothing scheduled at all, which is the other wrong answer.
    """
    if lane is None:
        return ""
    weekday = None if on is None else (on.weekday() + 1) % 7
    out = ""
    if lane.band:
        out += f'<span class="band {lane.band}"></span>'
    for mark in (lane.appointments or ()):
        here = mark.fires_on(weekday)
        shape = mark.shape if here else "elsewhen"
        note = mark.note if here else (
            f"not on this day: it fires on {mark.days}" if mark.days
            else "not on this day")
        out += (f'<span class="tick {shape}" style="left:{mark.at_pct}%" '
                f'title="{_esc(mark.label)}: {_esc(note)}"></span>')
    if lane.trace_pct is not None and lane.trace_shape:
        out += (f'<span class="tick {lane.trace_shape}" '
                f'style="left:{lane.trace_pct}%" '
                f'title="{_esc(lane.trace_label)}"></span>')
    return out


def _band_of(lane) -> str:
    """Which section of the table a run belongs in."""
    if lane is None:
        return "unplaced"
    if lane.band in ("cadence", "continuous"):
        return lane.band
    return "" if _marks_html(lane) else "unplaced"


def _row_section(section, lane) -> str:
    """The section key a ROW carries, which must equal its heading's.

    The script pairs a heading with its rows by comparing this exact value, so
    the two are computed from one place and never twice. `section` is what the
    caller already decided in `_sections`; the fallback keeps a direct caller
    on the band axis instead of making it invent a key.
    """
    return section if section is not None else (_band_of(lane) or "clock")


def _drawn_for(generated_at: str, zone: str):
    """The date this page draws, in the declarations' zone, or None.

    None is a real answer and not a failure: a page drawn without a usable
    moment filters nothing and shows no week and no month, which is honest,
    where a guessed date would put marks on days nobody measured.
    """
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(str(generated_at))
    except (TypeError, ValueError):
        return None
    if zone and moment.tzinfo is not None:
        try:
            from zoneinfo import ZoneInfo

            moment = moment.astimezone(ZoneInfo(str(zone)))
        except Exception:
            pass
    return moment.date()


def day_zones(workloads) -> tuple:
    """Every time zone the declarations on this page state, sorted.

    The axis is the MACHINE's day and each appointment is placed in the zone
    its own declaration names, which is right for a mark and not enough for
    anything drawn ACROSS the tracks. A single upright line at "now" is one
    moment: on a page whose runs keep two zones it is the wrong moment for at
    least one of them, and silently. So the caller draws it only on agreement,
    and where there is none the page says so rather than picking a zone.
    """
    out = set()
    for w in workloads:
        if getattr(w, "is_retired", False):
            continue
        schedule = getattr(w, "schedule", None)
        zone = str(getattr(schedule, "timezone", "") or "") if schedule else ""
        if zone:
            out.add(zone)
    return tuple(sorted(out))


def _order_key(lane, workload_id: str) -> tuple:
    """Where a run sits inside its own section.

    Alphabetical was the order until 2026-08-27, and it made the one section
    that IS a calendar unreadable as one: a 05:40 job sat below a 10:00 one and
    a 3600s cadence above a 300s one, so the marks scattered down the column
    instead of walking across it. A run with no order of its own keeps the
    name, which is at least the same on every render.
    """
    order = getattr(lane, "order", None) if lane is not None else None
    return (order is None, order if order is not None else 0.0, workload_id)


def _units_grid_html(findings) -> str:
    """Names in a grid, grouped by verdict, instead of a table of one sentence.

    Measured on the live page: thirty-two rows, each carrying "<name> runs on
    <host> and no declaration claims it" with the name already in the cell
    beside it. About eleven hundred pixels of a single sentence, which is how a
    section meant as context ends up longer than the subject of the page.

    Nothing is dropped: each name keeps its own sentence on the cursor, and the
    verdict is a heading over its own group rather than a column repeating it.
    Sorted by name, because thirty names in the order a service manager happens
    to return them is a list you can only read by starting at the top.
    """
    by_state = {}
    for finding in findings:
        by_state.setdefault(_state(finding), []).append(finding)
    out = ""
    for state in sorted(by_state):
        group = sorted(by_state[state],
                       key=lambda f: getattr(f, "workload_id", ""))
        out += (f'<p class="eyebrow">{_esc(state)} ({len(group)})</p>'
                '<ul class="units">')
        out += "".join(
            f'<li title="{_esc(getattr(f, "detail", ""))}">'
            f'{_esc(getattr(f, "workload_id", ""))}</li>' for f in group)
        out += "</ul>"
    return out


def _day_scale_html() -> str:
    """The hour ruler, drawn into every SECTION heading of the table.

    Once at the top of the table it was a reference the reader lost on the
    first scroll and could only get back by leaving the row they came for; the
    head cannot be pinned there, because the table is its own scroll container
    and a sticky head sticks to that box rather than to the window. Per SECTION
    it is three or four copies on this page instead of one, always within a
    screen of the tracks it measures, and it costs a line each.

    Per ROW it would be the same ruler drawn twenty-five times, which is the
    other end of the same mistake.
    """
    scale = "".join(f'<span style="left:{h / 0.24:.4f}%">{h:02d}</span>'
                    for h in range(0, 24, 3))
    return f'<div class="scale">{scale}</div>'


def _week_scale_html() -> str:
    """The seven weekday names, over the cells they label."""
    names = "".join(f'<span class="cell"><span class="num">'
                    f"{_WEEKDAY_NAMES[i]}</span></span>" for i in _WEEK_ORDER)
    return f'<div class="grid week ruler">{names}</div>'


def _month_scale_html(on) -> str:
    """The day numbers of the drawn month, over the cells they label.

    Empty without a date: a ruler counting to thirty-one over a month nobody
    named would be a scale for no particular month.
    """
    import calendar

    if on is None:
        return ""
    total = calendar.monthrange(on.year, on.month)[1]
    import datetime as _dt

    cells = "".join(
        '<span class="cell{}"><span class="num">{}</span></span>'.format(
            " wkstart" if _dt.date(on.year, on.month, d).weekday() == 0 else "", d)
        for d in range(1, total + 1))
    return (f'<div class="grid month ruler" '
            f'style="grid-template-columns: repeat({total}, 1fr)">{cells}</div>')


#: The week, Monday first, indexed into the Sunday-first tuple `weekdays_of`
#: produces. Two conventions meet here and exactly one place converts.
_WEEK_ORDER = (1, 2, 3, 4, 5, 6, 0)


def _week_dates(on):
    """The seven dates of the week `on` falls in, Monday first."""
    from datetime import timedelta

    if on is None:
        return ()
    monday = on - timedelta(days=on.weekday())
    return tuple(monday + timedelta(days=i) for i in range(7))


def _cell_html(*, label: str, due: bool, ran: bool, day: str, note: str,
               starts_week: bool = False) -> str:
    """One day of a week or a month.

    Two independent facts on one cell, and never merged: DUE comes from the
    declaration and RAN from what the machine wrote down. A cell that showed
    only their conjunction would make a run that was never scheduled and one
    that was scheduled and missed look the same.
    """
    classes = ("cell" + (" due" if due else "") + (" ran" if ran else "")
               + (" wkstart" if starts_week else ""))
    said = []
    if due:
        said.append(note or "due")
    else:
        said.append("not due")
    said.append("the machine wrote a line" if ran else "nothing recorded")
    return (f'<span class="{classes}" data-day="{_esc(day)}" '
            f'title="{_esc(day)}: {_esc(", ".join(said))}">'
            + (f'<span class="num">{_esc(label)}</span>' if label else "")
            + "</span>")


def _week_html(lane, on) -> str:
    """Seven days, Monday first. The scale a weekly run is legible on.

    A weekly job on a 24 hour axis is a ring at an hour, and the day it belongs
    to lives in a text cell beside the picture. Here it is the picture.
    """
    if lane is None or on is None or not lane.week:
        return ""
    dates = _week_dates(on)
    out = ""
    for slot, index in enumerate(_WEEK_ORDER):
        day = dates[slot].isoformat()
        # The DATE, not the weekday name: the ruler above already carries the
        # names, and a cell repeating its own column heading spends the only
        # line it has on a word the reader has just read. The number says
        # which Monday, which is the half a week view cannot otherwise give.
        out += _cell_html(
            label=str(dates[slot].day),
            due=bool(lane.week[index]),
            ran=day in lane.ran,
            day=day,
            note=lane.label)
    return f'<div class="grid week">{out}</div>'


def _month_html(lane, on) -> str:
    """The drawn month, one cell per day. The scale a monthly rhythm shows on.

    The month is the one `on` falls in and is NAMED above the table, because a
    grid of bare numbers belongs to no month at all and a page is read days
    after it was written.
    """
    import calendar
    from datetime import date

    if lane is None or on is None or not lane.week:
        return ""
    total = calendar.monthrange(on.year, on.month)[1]
    due = set(lane.month or ())
    out = ""
    for number in range(1, total + 1):
        when = date(on.year, on.month, number)
        # NO number in the cell: the ruler over this grid carries them, and a
        # cell twelve pixels wide spends its only line repeating the label a
        # reader has just read. The week boundary is marked instead, because
        # thirty-one identical boxes are a bar, not a month.
        out += _cell_html(label="", due=number in due,
                          ran=when.isoformat() in lane.ran,
                          day=when.isoformat(), note=lane.label,
                          starts_week=when.weekday() == 0)
    return (f'<div class="grid month" '
            f'style="grid-template-columns: repeat({total}, 1fr)">{out}</div>')


def _track_html(lane, on=None) -> str:
    """One run's own day, week and month, and underneath it the schedule in words.

    The words come from the LANE and not from `Row.when`, which holds the same
    fact in the form the declaration wrote it. Two renderings of one schedule
    side by side is how they come to disagree; the declared form is one click
    down in the dossier, where it is the precise answer rather than a second
    opinion about the readable one.
    """
    if lane is None:
        return f'<span class="unreported">{NOT_PLACED}</span>'
    marks = _marks_html(lane, on)
    when = _esc(lane.label) + (f" {_esc(lane.days)}" if lane.days else "")
    body = (f'<div class="track">{marks}</div>' if marks
            else f'<div class="note">{_esc(lane.note)}</div>')
    # THREE SCALES, all three rendered and one shown. Rendered rather than
    # built by the script, because what ships is what the run measured: a
    # scale that only exists once somebody clicks is a scale nobody can read
    # with scripting off, and this page has to stand alone as one file.
    week, month = _week_html(lane, on), _month_html(lane, on)
    if week or month:
        body = (f'<div class="lens" data-scale="day">{body}</div>'
                + (f'<div class="lens" data-scale="week" hidden>{week}</div>'
                   if week else "")
                + (f'<div class="lens" data-scale="month" hidden>{month}</div>'
                   if month else ""))
    out = body + (f'<div class="when">{when}</div>' if when.strip() else "")
    # HOW LONG AGO, and only where there is a moment to age. The strip of
    # recorded runs is the history and the diamond is the position; neither
    # answers the question a reader actually opens this page with, which is
    # whether the last one was minutes or days ago. The absolute stamp is what
    # ships, so a reader without scripting still gets an answer; the clock
    # turns it into a distance, exactly like the age in the header.
    if lane.trace_at:
        out += (f'<div class="ago">last trace <time class="since" '
                f'datetime="{_esc(lane.trace_at)}">{_esc(lane.trace_at)}</time>'
                "</div>")
    return out


#: What a run nothing could place says instead of showing an empty cell. A
#: blank there reads as "runs at no time", which is a different claim.
NOT_PLACED = "nothing placed it on the day"


def _group_head_html(section: str, title: str, count: int, on=None, *,
                     with_scale: bool = True) -> str:
    """A section heading inside the table, spanning it.

    It carries the band as data so the script can take it away with its last
    row: a heading reading "On a cadence (10)" above nothing is the one number
    on this page that contradicts what is under it.

    And its count is an ELEMENT, not a literal, for the half of that failure
    which survived taking the heading away. Measured on the live page: a filter
    left three rows standing under a heading that went on saying eight, because
    the heading only disappeared when its LAST row went. A heading with rows
    under it and the wrong number over them is the same lie as a stale page,
    which is why the page total is an element too.
    """
    # And the ruler, in the day column of the heading, for every section whose
    # rows actually carry a track. Not in the section for the runs nothing
    # could place: an hour scale over cells that hold a sentence instead of a
    # day invites the reading that they are somewhere on it.
    scale = "" if not with_scale else (
        f'<div class="lens" data-scale="day">{_day_scale_html()}</div>'
        f'<div class="lens" data-scale="week" hidden>{_week_scale_html()}</div>'
        f'<div class="lens" data-scale="month" hidden>'
        f"{_month_scale_html(on)}</div>")
    return (f'<tbody class="grouphead" data-band="{_esc(section)}">'
            f'<tr><th><span class="eyebrow">{_esc(title)} '
            f'(<span class="n" data-total="{count}">{count}</span>)'
            f'</span></th><th class="dayhead">{scale}</th>'
            '<th colspan="2"></th></tr></tbody>')


#: The two marks a week and a month carry, which are cells rather than ticks
#: and therefore cannot share the tuple above: their sample is a box, not a
#: dot. Listed only where one of those scales is on the page.
CELLS = (
    ("due", "a boxed day on the week and the month: a day this run is due on, "
            "from the same weekday set the unit file is rendered from"),
    ("ran", "a small diamond inside such a day: the machine wrote a line then. "
            "It reaches back only as far as the recorded strip, which is "
            "capped, so an empty day further back says nothing either way"),
)


def _legend_html(lanes_shown, on=None) -> str:
    """Built from the marks actually drawn, never from the full vocabulary.

    A shape nobody explains is a decoration, and a legend listing shapes that
    are not on the page teaches a reader to look for marks that are not there.

    `on` is here because one shape is decided at DRAWING time and not on the
    mark: an appointment is `elsewhen` because of the day the page was drawn
    for, so a legend built from the marks alone would leave the faintest mark
    on the page as the only unexplained one.
    """
    weekday = None if on is None else (on.weekday() + 1) % 7
    marks = [mark for lane in lanes_shown for mark in (lane.appointments or ())]
    shown = {mark.shape for mark in marks if mark.shape}
    if any(not mark.fires_on(weekday) for mark in marks):
        shown.add("elsewhen")
    shown |= {lane.trace_shape for lane in lanes_shown if lane.trace_shape}
    banded = {lane.band for lane in lanes_shown if lane.band}
    legend = "".join(
        f'<li><span class="sample"><span class="tick {name}" style="left:50%"></span>'
        f"</span>{_esc(text)}</li>"
        for name, text in SHAPES if name in shown)
    legend += "".join(
        f'<li><span class="sample"><span class="band {name}"></span></span>{_esc(text)}</li>'
        for name, text in BANDS if name in banded)
    if any(getattr(lane, "week", ()) for lane in lanes_shown):
        legend += "".join(
            f'<li><span class="sample"><span class="cell {name}"></span></span>'
            f"{_esc(text)}</li>" for name, text in CELLS)
    return f'<ul class="legend">{legend}</ul>' if legend else ""


PANELS_NOTE = (
    "Framed as it stands, by its own producer, carrying its own moment. This "
    "run neither rendered nor measured it, and nothing from it is repeated "
    "here as a number of this page.")


def _facets_html(rows) -> str:
    """The filter bar, built from the runs that are here and from nothing else.

    A facet is drawn only where it has MORE THAN ONE value. A row of buttons
    offering the single answer every run gives is not a filter, it is furniture
    that teaches a reader the bar is useless. Measured on this instance: `host`,
    `runtime` and `owner` each had exactly one value, so three of the five
    facets would have been furniture on the day this was written, and all three
    appear by themselves the day a second machine or a second runtime arrives.

    Rendered `hidden`. The script reveals it, because a control that cannot act
    must not be on the page: without scripting the table is complete and
    unfiltered, which is the honest state of an unfiltered document.

    The counts are of the runs in service, so a reader can see the size of a
    slice before choosing it and is not left clicking to find out that a facet
    is empty.
    """
    if not rows:
        return ""
    out = []
    every = facet_counts(rows)
    for key, label in FACETS:
        counts = every[key]
        if len(counts) < 2:
            continue
        buttons = "".join(
            f'<button type="button" data-facet="{_esc(key)}" '
            f'data-value="{_esc(value)}" aria-pressed="false">{_esc(value)}'
            f'<span class="n">{counts[value]}</span></button>'
            for value in sorted(counts))
        out.append(f'<div class="row"><span class="name">{_esc(label)}</span>'
                   f"{buttons}</div>")
    # The search stays even where every facet turned out to be furniture. A
    # pill can only offer the words this skill happens to file a run under; the
    # word a reader actually remembers is usually in the purpose, and there was
    # no way to look for it at all. It is also the only control that works on a
    # page where every run shares one kind and one sphere.
    find = ('<div class="row"><span class="name">find</span>'
            '<input id="q" type="search" autocomplete="off" '
            'placeholder="name, purpose, unit, schedule"></div>')
    tail = ('<div class="row"><span class="name"></span>'
            '<button type="button" class="clear">show all</button>'
            '<button type="button" id="expand" aria-pressed="false">'
            "open every row</button></div>")
    # THE SCALE. A day answers "when today", a week answers "which days", and a
    # month answers "how often". The same three questions the neighbouring
    # operations calendar was built around, and the reason it existed: a weekly
    # run on a 24 hour axis is a ring at an hour, with the day it belongs to in
    # a text cell beside the picture.
    scale = ('<div class="row" hidden><span class="name">scale</span>'
             + "".join(
                 f'<button type="button" data-scale-pick="{key}" '
                 f'aria-pressed="{"true" if key == "day" else "false"}">'
                 f"{word}</button>"
                 for key, word in (("day", "day"), ("week", "week"),
                                   ("month", "month")))
             + "</div>")
    return ('<div class="facets" id="facets" hidden>'
            '<p class="eyebrow">Show only</p>' + "".join(out) + find + scale + tail
            + '<span class="meta">A hidden run is out of sight, not out of the '
            "counts above it: nothing here is recomputed. A run's day is a "
            "column of its own row, so it goes with it.</span></div>")



def facet_counts(rows) -> dict:
    """Every facet of `FACETS` as {value: runs carrying it}, unfiltered.

    The arithmetic behind the filter bar, apart from the bar. The page draws
    only the facets with more than one value; a machine reader gets them all,
    and both read the same counts because both call this.
    """
    every = {}
    for key, _label in FACETS:
        counts = {}
        for row in rows:
            if key == "state":
                values = sorted({_state(f) for f in row.findings}) or [UNREPORTED]
            elif key == "attention":
                values = [_attention_of(row)]
            else:
                values = [str(getattr(row, key, "") or "")]
            for value in values:
                if value:
                    counts[value] = counts.get(value, 0) + 1
        every[key] = counts
    return every

#: The first view: this run's own material. A constant rather than a literal
#: repeated in three places, because the nav, the section and the script all
#: have to agree on it, and the day they disagree the shell opens on nothing.
OVERVIEW_ID = "view-overview"
OVERVIEW_LABEL = "Overview"


def _view_id(label, taken) -> str:
    """A readable, unique id, so a tab can be linked to and not just clicked."""
    slug = re_mod.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")[:40]
    stem = f"view-{slug}" if slug else "view"
    candidate, n = stem, 2
    while candidate in taken:
        candidate, n = f"{stem}-{n}", n + 1
    taken.add(candidate)
    return candidate


def _views(panels) -> tuple:
    """`(id, label, src)` per framed neighbour, computed ONCE.

    The nav and the sections are two renderings of the same list and must carry
    the same identifiers. Deriving them twice from the same input would agree
    today and drift the day one side learns a rule the other does not, so the
    list is built here and handed to both.
    """
    taken, out = {OVERVIEW_ID}, []
    for entry in panels or ():
        label, src = entry[0], entry[1]
        if not (label and src):
            continue
        out.append((_view_id(label, taken), str(label), str(src)))
    return tuple(out)


def _tabs_html(views, overview_label=OVERVIEW_LABEL) -> str:
    """The bar of views. Anchors, so without scripting they are jump links to
    sections that are all on the page anyway, and with it they switch views."""
    if not views:
        return ""
    items = [f'<a href="#{OVERVIEW_ID}" data-view="{OVERVIEW_ID}" '
             f'aria-current="page">{_esc(overview_label)}</a>']
    items += [f'<a href="#{vid}" data-view="{vid}">{_esc(label)}</a>'
              for vid, label, _ in views]
    return f'<nav class="tabs" aria-label="Views">{"".join(items)}</nav>'


def _panels_html(views) -> str:
    """Neighbouring pages framed, one view each.

    Why a frame and not the numbers. This skill draws its own material and
    adopts no figure another producer computed, because a page must not assert
    what no probe in its own run verified, and a second renderer of the same
    number drifts from the first the day one of them is fixed. A frame breaks
    neither rule: nothing is parsed, nothing is re-derived, and what the reader
    sees is the neighbour's own page carrying the neighbour's own stamp. The
    boundary that matters is adoption, not adjacency.

    Why a view and no longer a footer. Framed at the foot of this page a
    neighbour got a letterbox in the middle of somebody else's document: its
    own header, its own navigation and its own scrollbar squeezed into a strip,
    under headings in another voice. Two designs sharing one column read as
    neither. As a view it gets the whole window under one shared bar, which is
    the only way a page somebody else rendered can sit beside this one and
    still look like one place.

    The target is a URL from configuration, so no host and no path of one
    instance is shipped to every other. A relative one keeps working when the
    machine is renamed; an absolute one is the caller's choice and its risk.
    """
    out = []
    for vid, label, src in views:
        out.append(
            f'<section class="view" id="{vid}" aria-label="{_esc(label)}">'
            f'<div class="frame"><h2>{_esc(label)}</h2>'
            f'<p class="meta">{PANELS_NOTE} '
            f'<a href="{_esc(src)}">Open it on its own</a>.</p>'
            f'<iframe src="{_esc(src)}" loading="lazy" '
            f'title="{_esc(label)}"></iframe></div></section>')
    return "".join(out)


def stat_counts(in_service, history) -> dict:
    """The four counts at the top of the page, as numbers. See `_stats_html`."""
    return {
        "in_service": len(in_service),
        "with_findings": sum(1 for row in in_service
                             if any(_sev(f) in ("high", "medium") for f in row.findings)),
        "not_reported": sum(1 for row in in_service if not row.findings),
        "retired": len(history),
    }


def _stats_html(in_service, history) -> str:
    """Four counts, every one of them counted off the rows below.

    Not a second source and not a new claim: the same findings the table shows,
    grouped by the severity the report itself assigned. A summary that reaches
    for a figure the table does not carry is how a headline and its own detail
    come to disagree.
    """
    counts = stat_counts(in_service, history)
    flagged = counts["with_findings"]
    cells = ((counts["in_service"], "in service", False),
             (flagged, "carrying a finding", flagged > 0),
             (counts["not_reported"], UNREPORTED, False),
             (counts["retired"], "retired", False))
    stats = "".join(
        f'<div class="stat{" flag" if flag else ""}"><span class="n">{n}</span>'
        f'<span class="k">{_esc(word)}</span></div>'
        for n, word, flag in cells)
    return f'<div class="stats">{stats}</div>'


def _finding_table(findings) -> str:
    """One table shape for everything that is not a declaration."""
    rows = "".join(
        f'<tr><td class="id">{_esc(getattr(f, "workload_id", ""))}</td>'
        f'<td class="state">{_esc(_state(f))}</td>'
        f'<td class="meta">{_esc(getattr(f, "detail", ""))}</td></tr>'
        for f in findings)
    return ('<div class="scroll"><table class="findings"><thead><tr>'
            "<th>name</th><th>state</th><th>detail</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>")


def _units_html(unit: str) -> str:
    """One line per unit name, as MARKUP.

    A newline between two names is whitespace to HTML, and this cell carries
    `white-space: nowrap` so identifiers do not break mid-token; the two labels
    would therefore run into one another as a single unreadable word.
    """
    names = [n for n in str(unit or "").split("\n") if n.strip()]
    if not names:
        return NO_UNIT
    return "<br>".join(_esc(n) for n in names)


#: Worst first, and stated HERE rather than in the script: which of two
#: verdicts is worse is a decision of this module, and a second copy of it in
#: JavaScript would drift from this one the day a severity is added.
_RANK = {"high": 0, "medium": 1, "info": 2}


#: Which severities put a run in front of a reader. `info` is the ordinary
#: state of a healthy machine and would drown the two that are not.
NEEDS_A_PERSON = ("high", "medium")

#: Was ein Lauf in der Aufmerksamkeits-Facette trägt. Zwei Werte, weil es zwei
#: Antworten gibt und nicht drei: entweder will dieser Lauf etwas von einem
#: Menschen, oder er berichtet.
ATTENTION_OPEN = "needs-a-person"
ATTENTION_INFO = "information"


def _attention_of(row) -> str:
    """Ob dieser Lauf einen Menschen braucht, aus seinen eigenen Befunden.

    Abgeleitet und nie getragen: die Schwere steht schon in jedem Befund, und
    ein zweites Feld daneben wäre eine zweite Wahrheit, die am Tag der ersten
    Abweichung die falsche ist.
    """
    return (ATTENTION_OPEN
            if any(_sev(f) in NEEDS_A_PERSON for f in row.findings)
            else ATTENTION_INFO)


#: Die Facetten der Filterleiste, in Anzeigereihenfolge. Aufmerksamkeit steht
#: VORNE, weil sie die Frage beantwortet, mit der jemand eine Betriebsseite
#: öffnet; alles danach schneidet einen Bestand.
#:
#: Diese Liste stand bis 2026-09-04 ein zweites Mal als Literal im Skript
#: (`var FACETS = ['kind', ...]`). Zwei Listen für einen Vertrag laufen
#: auseinander, und die stille Richtung ist die schlimmere: eine Facette, die
#: nur die Python-Seite kennt, rendert einen Knopf, den das Skript nicht kennt,
#: und ein Druck darauf versteckt JEDE Zeile. Das Skript liest die Liste jetzt
#: aus den gerenderten Knöpfen, es gibt also nur noch diese eine.
FACETS = (("attention", "attention"), ("kind", "kind"), ("persona", "sphere"),
          ("host", "host"), ("runtime", "runtime"), ("state", "state"))


def _ident(workload_id: str) -> str:
    """The anchor a run answers to. ONE derivation, because two would drift.

    The row builds an id from the declaration's name and the open list links to
    it; computed in both places, the day an identifier contains a character one
    of them escapes differently, the link points at nothing and nothing says so.
    """
    return re_mod.sub(r"[^A-Za-z0-9_-]", "-", str(workload_id))


def _open_html(rows) -> str:
    """What on this page needs a person, above everything else on it.

    The page opened with four counts and a table, which is an inventory: a
    reader had to work out "is anything wrong here" by eye, over twenty-five
    rows. The neighbouring operations page opens with the answer instead, and
    the material for it was already here and being thrown away: every finding
    carries a HINT, this skill's own sentence about what to do next, and no
    renderer had ever put one on a page.

    An empty list is a SENTENCE and not an empty section, and the sentence says
    what it is a statement about: nothing measured here needs a person, which
    is not a promise about anything that was not measured.
    """
    open_ones = [(row, f) for row in rows for f in row.findings
                 if _sev(f) in NEEDS_A_PERSON]
    if not open_ones:
        return ('<p class="banner" id="allclear"><strong>Nothing here needs a '
                "person.</strong> No run on this page carries a finding above "
                "information. That is a statement about what was measured, "
                "never a promise about what was not.</p>")
    runs = len({row.workload_id for row, _ in open_ones})
    # EINE Zeile statt einer zweiten Liste. Bis 2026-09-04 stand hier jeder
    # Befund ausgeschrieben, ein zweites Mal: derselbe Satz noch einmal im
    # Dossier seiner eigenen Zeile. Fünfundzwanzig Einträge über einer Tabelle,
    # die dieselben fünfundzwanzig trägt, sind keine Zusammenfassung, sondern
    # eine zweite Fassung, die am Tag der ersten Abweichung die falsche ist.
    #
    # Was der Block richtig gemacht hat, bleibt: die Seite öffnet mit der
    # ANTWORT auf "braucht hier etwas mich", nicht mit einem Bestand. Nur ist
    # die Antwort eine Zahl und ein Weg dorthin, und der Weg ist der Filter,
    # den die Leiste ohnehin trägt. Ohne Skript bleibt der Satz stehen und die
    # Tabelle ist vollständig, was der ehrliche Zustand eines ungefilterten
    # Dokuments ist.
    # Der Knopf nur, wenn die Facette AUCH eine Pille bekommt. Sie wird erst ab
    # zwei Werten gezeichnet, und auf einer Seite, auf der jeder Lauf einen
    # Menschen braucht, gibt es keine zweite Antwort. Ein Knopf ohne Pille wäre
    # ein Steuerelement, das nichts tut, und genau davor warnt die Filterleiste
    # in ihrem eigenen Kopf.
    filterable = len({_attention_of(r) for r in rows}) > 1
    shortcut = (f'<button type="button" class="pick" data-facet="attention" '
                f'data-value="{ATTENTION_OPEN}" aria-pressed="false">'
                "show only those</button>") if filterable else ""
    plural = "" if runs == 1 else "s"
    return ('<p class="banner" id="attention"><strong>'
            f"{len(open_ones)} finding{'' if len(open_ones) == 1 else 's'} on "
            f"{runs} run{plural} need{'s' if runs == 1 else ''} a person.</strong> "
            "Each one sits in its own row below, with the step this skill "
            f"advises. {shortcut}</p>")


def _machines_html(rep, asked=()) -> str:
    """When each machine came up, and how far the evidence reaches back.

    Both are what make a silence readable. "Nothing ran at 06:00" is perfectly
    true and reads as an alarm on a box that came up at 09:00; `reconcile`
    already holds that verdict back, and a reader needs the same fact to judge
    everything a verdict does not cover. Taken from the neighbouring operations
    page, which has carried "Maschine laeuft seit" and "Beleglage ab" in its
    header from the start.

    A machine that would not say is NAMED as such. Leaving it out would make a
    page about a silent machine look exactly like a page about one that has
    been up for a month.
    """
    booted = dict(getattr(rep, "booted", None) or {})
    stamps = sorted(run[0] for runs in (getattr(rep, "history", None) or {}).values()
                    for run in (runs or ()) if run and run[0])
    parts = [f'{_esc(host)} came up <time class="since" '
             f'datetime="{_esc(booted[host])}">{_esc(booted[host])}</time>'
             for host in sorted(booted)]
    silent = sorted(h for h in (asked or ()) if h and h not in booted)
    if silent:
        parts.append(f"{_esc(', '.join(silent))} did not say when it came up, "
                     "so an appointment without a trace cannot be told apart "
                     "here from one that fell while the machine was off")
    if stamps:
        parts.append('the oldest run recorded on this page is from '
                     f'<time class="since" datetime="{_esc(stamps[0])}">'
                     f"{_esc(stamps[0])}</time>, and nothing before that is "
                     "evidence of anything")
    return f'<p class="meta">{" · ".join(parts)}</p>' if parts else ""


def _row_html(row: Row, asked=(), lane=None, on=None, *, section=None) -> str:
    """One run as a pair of rows: the run, then its dossier and its reasons.

    ONE row per run, and it carries the run's own day. Until 2026-08-27 the day
    was an axis above the table, so each declaration was on the page twice, as
    a lane and as a row, each holding half of what is known about it. A reader
    had to match them by name to answer a single question about one run.

    Four columns at rest, not ten. What a run IS (unit, host, runtime, owner,
    sphere) does not change between readings and does not belong in a column
    every other run has to make room for; what a run DID does. So the identity
    moved one click down into a definition list, and the row kept the
    identifier, the day, the recorded history and the verdict. That is also the
    answer to the ask this panel exists for: the detail arrives where the eye
    already is, instead of being scrolled to and read a second time.

    The verdict is a word and belongs in a column; the reason is a sentence and
    does not. Before 2026-08-24 both shared one cell, and the single-token
    columns between them took their width unconditionally, so the sentence had
    roughly a tenth of the page and the verdict had whatever was left of that.

    The pair is wrapped in its own <tbody> by the caller, which is what keeps a
    reason from being separated from the verdict it explains.
    """
    if row.findings:
        # COUNTED, not repeated. A run with six appointments carries six
        # findings, and stacking six identical verdicts made one row three
        # hundred pixels tall while saying one thing six times. The count is
        # stated rather than dropped, because six healthy appointments and one
        # are different facts, and every finding is still listed one by one in
        # the reasons underneath.
        tally = {}
        for f in row.findings:
            key = (_sev(f), _state(f))
            tally[key] = tally.get(key, 0) + 1
        verdicts = "".join(
            f'<div class="verdict"><span class="sev sev-{_esc(sev)}">'
            f"{_esc(sev)}</span>"
            f'<span class="state">{_esc(state)}</span>'
            + (f'<span class="times">×{n}</span>' if n > 1 else "")
            + "</div>"
            for (sev, state), n in tally.items())
        # Each reason names its own state. A run can carry several findings,
        # and once the sentences leave the cell that held their state word,
        # nothing else maps a sentence back to a verdict.
        # Der HINWEIS gehört hierhin, seit die Liste über der Tabelle weg ist.
        # Er ist die einzige Stelle, an der dieser Skill sagt, was als nächstes
        # zu tun ist, und er stand vorher NUR in jener Liste: wer sie ersatzlos
        # streicht, wirft die Handlungsanweisung weg und lässt den Befund stehen.
        reasons = "".join(
            f'<div class="hint"><span class="lead">{_esc(_state(f))}</span>'
            f'{_esc(getattr(f, "detail", ""))}'
            + (f'<div class="todo">{_esc(getattr(f, "hint", ""))}</div>'
               if getattr(f, "hint", "") else "")
            + "</div>"
            for f in row.findings)
    else:
        verdicts = f'<span class="unreported">{UNREPORTED}</span>'
        # A silence whose cause the page holds must not be reported as a
        # mystery. `not reported` that always reads the same teaches a reader
        # to skip it, and the next one is a run that stopped.
        if asked and row.host and row.host not in asked:
            reasons = ('<div class="hint">this declaration is placed on '
                       f'<strong>{_esc(row.host)}</strong>, and this page '
                       f"reconciled {_esc(', '.join(asked))}. Nothing here "
                       "measured it, so its silence says nothing about its "
                       "health.</div>")
        else:
            reasons = ('<div class="hint">no finding was produced for this '
                       "declaration, which is not the same as a healthy "
                       "one</div>")
    retired = ' <span class="meta">(retired)</span>' if row.retired else ""
    # The facet values travel on the element the filter hides, which is the
    # whole <tbody>: hiding the run row alone would leave its reasons behind as
    # an orphan paragraph belonging to nothing.
    #
    # `state` is a LIST, space separated, because a run can carry several
    # findings and collapsing them to the worst one would make a filter for the
    # milder verdict miss a run that genuinely has it.
    states = " ".join(sorted({_state(f) for f in row.findings})) or UNREPORTED
    ident = _ident(row.workload_id)
    # Two chips, not five. They are the two facets a reader filters by, so they
    # are the two worth carrying beside the name; every other term is in the
    # dossier, where a label sits next to it and says what it is.
    chips = (f'<span class="chips"><span class="chip">{_esc(row.kind)}</span>'
             f'<span class="chip">{_esc(row.persona)}</span></span>')
    dossier = "".join(
        f'<div><dt>{_esc(label)}</dt>'
        f'<dd class="{_esc(label)}">{value}</dd></div>'
        for label, value in (
            ("unit", _units_html(row.unit)),
            ("host", _esc(row.host)),
            ("kind", _esc(row.kind)),
            ("runtime", _esc(row.runtime)),
            ("owner", _esc(row.owner)),
            ("sphere", _esc(row.persona)),
            ("when", _esc(row.when)),
            ("log", _units_html(row.log) if row.log else ""),
            # The HEALTHY answer is printed too, and on purpose: a column of
            # "in this repository" is what makes the one row that says
            # something else legible. A line only for the exception reads as a
            # page with nothing to say about the rest.
            ("program", (f'<code>{_esc(row.program)}</code>'
                         f'<span class="meta">{_esc(row.program_where)}</span>')
             if row.program else ""),
            # Only for the runs that declare something. A "rights: none" line on
            # fifty rows would train the eye to skip the one row that reaches a
            # person, and that row is the reason this line exists at all.
            ("rights", "<br>".join(_esc(line) for line in row.rights)
             if row.rights and "not declared" not in row.rights[0] else ""),
        ) if value)
    # The band travels on the row so the script can take a section heading away
    # with its last row. Not a facet: it is what the row IS, and the reader
    # filters by kind, which is a different question with different answers.
    # What a reader can look for, in one lowercased haystack. The facet pills
    # can only offer the words this skill files a run under; the word somebody
    # actually remembers is usually in the purpose, and until 2026-08-27 there
    # was no way to search for it at all.
    haystack = " ".join(str(part).lower() for part in (
        row.workload_id, row.purpose, row.kind, row.persona, row.host,
        row.runtime, row.owner, row.when, str(row.unit or "").replace("\n", " "),
    ) if part)
    # The sort keys. Rendered rather than derived in the script, because a
    # second derivation of "which of these is worse" drifts from the first: the
    # severity order is a decision of this module, and the script may only read
    # it. `when` restores the order the sections were built in.
    worst = min((_RANK.get(_sev(f), 9) for f in row.findings), default=9)
    placed = None if lane is None else getattr(lane, "order", None)
    return (
        f'<tbody data-id="{_esc(row.workload_id)}" data-kind="{_esc(row.kind)}"'
        f' data-persona="{_esc(row.persona)}" data-host="{_esc(row.host)}"'
        f' data-runtime="{_esc(row.runtime)}" data-state="{_esc(states)}"'
        f' data-attention="{_esc(_attention_of(row))}"'
        f' data-search="{_esc(haystack)}"'
        f' data-sort-id="{_esc(row.workload_id.lower())}"'
        f' data-sort-when="{placed if placed is not None else 999999}"'
        f' data-sort-recorded="{_esc(getattr(lane, "trace_at", "") or "")}"'
        f' data-sort-state="{worst}"'
        f' data-band="{_esc(_row_section(section, lane))}">'
        f'<tr class="run" id="run-{ident}" tabindex="0" role="button"'
        f' aria-expanded="true" aria-controls="why-{ident}">'
        f'<td class="id">{_esc(row.workload_id)}{retired}'
        f'<div class="meta">{_esc(row.purpose)}{chips}</div></td>'
        f'<td class="day">{_track_html(lane, on)}</td>'
        f'<td class="recorded">{_strip_html(row)}</td>'
        f"<td>{verdicts}</td>"
        "</tr>"
        f'<tr class="why" id="why-{ident}"><td colspan="4">'
        f'<dl class="dossier">{dossier}</dl>{reasons}'
        f"{_recipients_html(row)}"
        "</td></tr></tbody>")


#: The version of the document `data` returns. Raised only when a key changes
#: meaning or disappears; a new key is not a new version.
DATA_SCHEMA = 1

#: What a run with no finding says in the machine readable document. The same
#: words the page prints, because "nothing was said" is not "in sync", and a
#: second reader must not learn the one the page refuses to say.
NO_SEVERITY = "none"

#: The facets the document carries, by the name a reader of the document uses.
#: `persona` is what the page calls `sphere`, so the document says sphere.
DATA_FACETS = (("attention", "attention"), ("kind", "kind"), ("persona", "sphere"),
               ("host", "host"), ("runtime", "runtime"), ("state", "state"))


def _system_key(systems, workload_id: str) -> str:
    """The section key a run sits under on the system axis. See `_sections`."""
    value = systems.get(workload_id) or ""
    return value if value else SYSTEM_UNDECIDED


def _worst(findings):
    """The loudest finding, by the same order the table sorts by, or None."""
    return min(findings, key=lambda f: _RANK.get(_sev(f), 9), default=None)


def _day_data(lane, on) -> dict:
    """One lane as data: the same marks `_marks_html` draws, as numbers."""
    if lane is None:
        return {"marks": [], "trace_pct": None, "trace_at": "", "trace_label": "",
                "note": "", "band": "", "placed": False}
    weekday = None if on is None else (on.weekday() + 1) % 7
    marks = []
    for mark in (lane.appointments or ()):
        here = mark.fires_on(weekday)
        marks.append({"at_pct": mark.at_pct, "label": mark.label,
                      "shape": mark.shape if here else "elsewhen",
                      "days": mark.days, "today": here})
    return {"marks": marks,
            "trace_pct": lane.trace_pct if lane.trace_shape else None,
            "trace_at": lane.trace_at, "trace_label": lane.trace_label,
            "trace_failed": lane.trace_shape == "trace-failed",
            "note": lane.note, "band": lane.band,
            "placed": _band_of(lane) != "unplaced"}


def data(rep, workloads, *, generated_at: str, hosts=(), machine_units=()) -> dict:
    """The page's content as one JSON-ready document, for a reader that draws
    its own.

    Built from the SAME stages `render` uses: `rows`, `lanes`, `elsewhere`,
    `_sections`, `stat_counts` and `facet_counts`. Nothing here decides a
    verdict, a count or a position of its own; a second derivation is how two
    surfaces of one report come to disagree.

    Recipient groups are carried and people are only counted, as on the page.
    """
    loads = list(workloads)
    asked = tuple(str(h) for h in (hosts or ()) if str(h))
    declared = rows(rep, loads)
    other, inventory, unclaimed = elsewhere(rep, loads, machine_units)
    zones = day_zones(loads)
    zone = zones[0] if len(zones) == 1 else ""
    on = _drawn_for(generated_at, zone)
    by_lane = {lane.workload_id: lane for lane in lanes(rep, loads, on=on)}
    systems = {w.id: getattr(w, "system", None) for w in loads}
    in_service = [row for row in declared if not row.retired]
    history = [row for row in declared if row.retired]
    counts = facet_counts(in_service) if in_service else {k: {} for k, _ in FACETS}

    runs = []
    for row in declared:
        lane = by_lane.get(row.workload_id)
        worst = _worst(row.findings)
        runs.append({
            "id": row.workload_id, "title": row.title, "purpose": row.purpose,
            "system": _system_key(systems, row.workload_id),
            "kind": row.kind, "sphere": row.persona, "host": row.host,
            "runtime": row.runtime, "owner": row.owner, "when": row.when,
            "unit": row.unit, "log": row.log,
            "program": row.program, "program_where": row.program_where,
            "retired": row.retired,
            "state": _state(worst) if worst is not None else UNREPORTED,
            "severity": _sev(worst) if worst is not None else NO_SEVERITY,
            "attention": _attention_of(row),
            "findings": [{"state": _state(f), "severity": _sev(f),
                          "detail": str(getattr(f, "detail", "") or ""),
                          "hint": str(getattr(f, "hint", "") or "")}
                         for f in row.findings],
            "strip": [{"at": e[0] if len(e) > 0 else "",
                       "rc": e[1] if len(e) > 1 else None,
                       "verdict": (e[2] if len(e) > 2 else "") or "",
                       "key": e[3] if len(e) > 3 else ""}
                      for e in row.strip],
            "continuous": row.kind in _CONTINUOUS_KINDS,
            "day": _day_data(lane, on),
            "week": list(lane.week) if lane is not None else [],
            "month_due": list(lane.month) if lane is not None else [],
            "ran_days": sorted(lane.ran) if lane is not None else [],
            "recipient_groups": list(row.recipients),
            "people": row.people,
            "rights": list(row.rights),
        })

    decided = [f for f in inventory if _state(f) == DECIDED_VALUE]
    drifted = [f for f in inventory if _state(f) != DECIDED_VALUE]
    return {
        "schema": DATA_SCHEMA,
        "host": ",".join(asked),
        "hosts": list(asked),
        "generated_at": str(generated_at),
        "zone": zone,
        "drawn_for": on.isoformat() if on is not None else "",
        "header": str(getattr(rep, "header", "") or ""),
        "probed": _probed(getattr(rep, "header", "")),
        "strip_max": reconcile_strip_max(),
        "continuous_strip_note": CONTINUOUS_STRIP_NOTE,
        "stats": stat_counts(in_service, history),
        "facets": {name: dict(sorted(counts[key].items()))
                   for key, name in DATA_FACETS},
        "systems": [{"id": key, "title": title, "count": len(here)}
                    for key, title, here, _scale in
                    _sections(in_service, by_lane, systems, "system")],
        "runs": runs,
        "elsewhere": {
            "inventory_stale": [getattr(f, "workload_id", "") for f in drifted],
            "intentionally_absent": [getattr(f, "workload_id", "") for f in decided],
            "undeclared": {"named": [getattr(f, "workload_id", "") for f in other],
                           "counted": unclaimed},
        },
    }
