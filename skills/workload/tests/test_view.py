"""view: the page a human reads, and the four ways such a page lies.

A rendered dashboard is the easiest place in this whole skill to state
something nobody measured. It has no return code, nobody diffs it, and a green
tick on it reads as proof to the person looking at it. So the cases here are
mostly about what it must NOT say.
"""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from tests.conftest import CORPUS, DERIVED, MachineGuard, mod

model = mod("engine.model")
report_mod = mod("engine.report")
view = mod("engine.view")

STAMP = "2026-08-23T16:30:00+02:00"


class ViewBase(MachineGuard):

    def load(self, name):
        for folder in (CORPUS, DERIVED):
            path = folder / f"{name}.yaml"
            if path.exists():
                return model.load_declaration(path)
        raise AssertionError(name)

    def finding(self, workload_id, state, severity, detail, hint=""):
        return report_mod.Finding(workload_id=workload_id, state=state,
                                  severity=severity, detail=detail, hint=hint,
                                  source="machine")

    def page(self, *, findings=(), header="", workloads=None, history=None,
             runs=None, links=(), panels=(), overview_label="", machine_units=(),
             state_dir="", group_by="band"):
        rep = report_mod.Report(findings=list(findings), header=header,
                                history=dict(history or {}), runs=dict(runs or {}),
                                state_dir=state_dir)
        loads = workloads if workloads is not None else [self.load("calendar-export")]
        return view.render(rep, loads, generated_at=STAMP, links=links,
                           panels=panels, overview_label=overview_label,
                           machine_units=machine_units, group_by=group_by)


    def run_block(self, html, workload_id):
        """One run's own <tbody>: its row, its day and its dossier together.

        Since the day became a column of the table there is exactly one place
        on the page that belongs to a run, which is what these tests measure
        against. A search over the whole page would find the legend's sample
        marks as readily as the run's own.
        """
        found = re.search(r'<tbody data-id="%s".*?</tbody>' % re.escape(workload_id),
                          html, re.S)
        self.assertIsNotNone(found, f"{workload_id} has no block of its own")
        return found.group(0)

    def js(self, calls, *, stamp=STAMP):
        """Run the page's own script in node and return its answers.

        Asserting that the source *contains* a guard would be the exact failure
        this suite keeps finding: a test whose name promises a property its body
        does not measure. So the functions are executed.
        """
        import json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path as _Path
        node = shutil.which("node")
        if not node:
            self.skipTest("no node on this machine, so the page's script is not measured here")
        harness = "\n".join([
            view._JS,
            "const out = [];",
            *[f"out.push({c});" for c in calls],
            "console.log(JSON.stringify(out));",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / "page.js"
            path.write_text(harness, encoding="utf-8")
            done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.rc if hasattr(done, "rc") else done.returncode, 0,
                         f"the page's own script does not run: {done.stderr}")
        return json.loads(done.stdout)


class TheDocumentIsSelfContained(ViewBase):

    def test_it_declares_its_encoding(self):
        # Without this the first umlaut in a purpose renders as mojibake, and
        # this instance writes German. Project-wide rule, not a preference.
        self.assertIn('<meta charset="utf-8">', self.page().lower())

    def test_it_loads_nothing_from_anywhere(self):
        html = self.page()
        for offender in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.",
                         "http://", "https://"):
            with self.subTest(offender=offender):
                self.assertNotIn(offender, html,
                                 "a dashboard that fetches anything logs the "
                                 "reader's address somewhere else and stops "
                                 "working the moment the machine is offline")

    def test_it_carries_both_themes(self):
        html = self.page()
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn(":root", html)
        self.assertIn("data-theme", html,
                      "the system default has to be overridable, or the reader "
                      "is stuck with whatever the OS decided")


class ItNeverPaintsWhatNobodyMeasured(ViewBase):
    """The one property that matters more than the layout.

    `reconcile` already says in words whether a live source was asked. A page
    that drops that sentence and shows the same rows either way turns "these are
    the declarations" into "these are running", and nobody reading it can tell
    the difference.
    """

    UNPROBED = ("4 declaration(s) reconciled on 1 host(s), 0 of 4 probed: "
                "nothing here was asked of a live source, so this is the "
                "declarations and the discovery only")

    def test_the_header_sentence_survives_verbatim(self):
        html = self.page(header=self.UNPROBED)
        self.assertIn("0 of 4 probed", html)
        self.assertIn("nothing here was asked of a live source", html,
                      "the sentence reconcile chose is the honest one; a page "
                      "that summarises it away is where the claim gets made")

    def test_an_unprobed_page_is_marked_as_such(self):
        html = self.page(header=self.UNPROBED)
        self.assertIn("data-probed=\"false\"", html,
                      "the page has to carry the distinction in its structure, "
                      "not only in a sentence somebody may not read")

    def test_a_probed_page_says_so(self):
        html = self.page(header="2 declaration(s) reconciled on 1 host(s), 2 of 2 probed")
        self.assertIn("data-probed=\"true\"", html)


class EveryDeclarationAppearsWithItsState(ViewBase):

    def test_a_declaration_with_no_finding_is_still_listed(self):
        # The case that would otherwise vanish: a workload nobody said anything
        # about is not absent, it is unreported, and a page that only renders
        # findings would silently drop it.
        html = self.page(findings=())
        self.assertIn("calendar-export", html)
        # In the VERDICT CELL, not anywhere on the page. Since 2026-08-27 the
        # same word is also the fallback value of the `state` filter facet
        # (data-state="not reported"), so a search over the whole document finds
        # it even when the cell has been blanked. Measured: the mutation
        # `the-page-may-drop-a-declaration-nobody-reported-on` survived the
        # broad assertion the day the attribute was added.
        self.assertRegex(html, r'<span class="unreported">not reported</span>',
                         "a declaration with no finding has to say that it has "
                         "none, or its absence reads as health")

    def test_a_state_and_its_severity_are_both_shown(self):
        html = self.page(findings=[self.finding(
            "calendar-export", model.WorkloadState.overdue, model.Severity.high,
            "calendar-export last wrote a line 606s ago and its declared cadence is 60s")])
        self.assertIn("overdue", html)
        self.assertIn("606s", html)
        self.assertIn("high", html)

    def test_the_machine_noise_is_separated_from_the_declarations(self):
        # A real host answers with over a thousand units nobody declared. Mixed
        # into the same list they bury the six lines that matter. The unclaimed
        # ones are counted rather than listed (see the collapse cases below), so
        # this uses a state the terminal renderer lists too.
        html = self.page(findings=[self.finding(
            "com.example.someone-elses", model.WorkloadState.inventory_stale,
            model.Severity.info, "the inventory lists it and nothing else knows it")])
        self.assertIn("inventory_stale", html)
        body = html.split("com.example.someone-elses")[0]
        self.assertIn("calendar-export", body,
                      "the declared runs come first; what the machine happens "
                      "to carry is context, not the subject")


class DataIsNeverMarkup(ViewBase):
    """A declaration is a file a human writes, so its text is untrusted input."""

    def test_a_purpose_that_looks_like_markup_arrives_as_text(self):
        w = self.load("calendar-export")
        object.__setattr__(w, "purpose", '<script>alert("x")</script> & <b>bold</b>')
        html = self.page(workloads=[w])
        self.assertNotIn("<script>alert", html,
                         "a purpose reached the page as markup: anything a "
                         "declaration says would then run in the reader's browser")
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_a_finding_detail_is_escaped_too(self):
        html = self.page(findings=[self.finding(
            "calendar-export", model.WorkloadState.drifted, model.Severity.high,
            'the unit carries <img src=x onerror="boom">')])
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img", html)


class TheTimestampComesFromTheCaller(ViewBase):

    def test_the_page_says_when_it_was_made(self):
        self.assertIn(STAMP, self.page(),
                      "a dashboard with no date is read as current for ever")

    def test_the_renderer_reads_no_clock_of_its_own(self):
        # Passed in, never taken, so the same inputs render the same bytes and
        # a golden or a diff means something.
        source = view.SOURCE_TEXT if hasattr(view, "SOURCE_TEXT") else None
        if source is None:
            from pathlib import Path
            from tests.conftest import SKILL_DIR
            from tests.conftest import SKILL_DIR
        source = (SKILL_DIR / "engine" / "view.py").read_text(encoding="utf-8")
        for clock in ("datetime.now(", "time.time(", "date.today("):
            self.assertNotIn(clock, source,
                             "the renderer took its own timestamp, so its output "
                             "differs on every run and cannot be compared")


class FreshnessIsTheReadersVerdict(ViewBase):
    """A terminal and a web page are not the same surface.

    On a terminal `rendered 16:30` is harmless: you just ran the command, so you
    know the age. A page on a web server is read hours or days later, looks
    identical, and is believed. The renderer cannot know when it will be read,
    so it must not take a freshness verdict at all. It hands the reader a
    machine readable moment and lets the reader's own clock decide.
    """

    def root_tag(self, page: str) -> str:
        """The <html ...> element alone. An attribute is set there or nowhere."""
        return page[page.index("<html"):page.index(">", page.index("<html")) + 1]

    def test_the_moment_is_machine_readable(self):
        page = self.page()
        self.assertIn(f'datetime="{STAMP}"', page,
                      "a date only a human can read cannot be compared to the "
                      "reader's clock, so the page can never tell them it is old")

    def test_the_page_still_names_its_moment_without_scripting(self):
        # Progressive enhancement, not dependence: with scripting off the
        # absolute stamp is still in the text. A page whose date lives only in
        # an attribute shows no date at all to a reader who blocks scripts.
        page = self.page()
        body = page.split("<script>")[0]
        self.assertIn(STAMP, body)

    def test_the_renderer_takes_no_freshness_verdict(self):
        # Words the renderer is not entitled to. It does not know when the page
        # will be read, so any of these is a claim about a moment it cannot see.
        # Whole words: "refresh" and "refreshed" are ordinary vocabulary here and
        # a substring match on them would forbid describing the cadence at all.
        page = self.page().lower()
        for word in ("up to date", "currently", "as of now", "live now", "fresh"):
            self.assertIsNone(
                re.search(rf"\b{re.escape(word)}\b", page),
                f"the renderer stated {word!r}, which is a verdict "
                "about the reader's clock, not about its own inputs")

    def test_no_threshold_is_invented_when_none_was_declared(self):
        # On the root element, where the script reads it. The attribute NAME
        # necessarily appears further down inside the script that looks for it;
        # what must be absent is the value.
        self.assertNotIn("data-stale-after-min", self.root_tag(self.page()),
                         "a page with no declared refresh cadence must report "
                         "its age and take no verdict")

    def test_a_declared_cadence_reaches_the_page_as_data(self):
        rep = report_mod.Report(findings=[], header="")
        page = view.render(rep, [self.load("calendar-export")],
                           generated_at=STAMP, stale_after_min=60)
        self.assertIn('data-stale-after-min="60"', self.root_tag(page))
        self.assertIn('id="stale"', page,
                      "the threshold arrived but there is nothing for the "
                      "reader's clock to unhide")

    # ── the script, actually executed ───────────────────────────────────────

    def test_an_age_is_named_in_words_a_human_reads(self):
        base = "Date.parse('%s')" % STAMP
        answers = self.js([
            f"ageText('{STAMP}', {base} + 30*60000)",
            f"ageText('{STAMP}', {base} + 5*3600000)",
            f"ageText('{STAMP}', {base} + 3*86400000)",
        ])
        self.assertIn("30", answers[0])
        self.assertIn("5", answers[1])
        self.assertIn("3", answers[2])

    def test_a_stamp_from_the_future_is_never_reported_as_an_age(self):
        base = "Date.parse('%s')" % STAMP
        answers = self.js([f"ageText('{STAMP}', {base} - 3*3600000)"])
        self.assertNotIn("-", answers[0],
                         "a negative age was printed. The reader's clock and the "
                         "renderer's disagree, and that is what to say")
        self.assertIn("clock", answers[0].lower())

    def test_an_unparseable_moment_produces_no_age_at_all(self):
        answers = self.js(["ageText('gestern nachmittag', 1000)"])
        self.assertEqual(answers[0], "",
                         "an age was invented from a moment that could not be read")

    def test_no_verdict_without_a_declared_cadence(self):
        base = "Date.parse('%s')" % STAMP
        answers = self.js([f"verdict('{STAMP}', {base} + 99*86400000, null)"])
        self.assertIsNone(answers[0],
                          "a page 99 days old was judged against a threshold "
                          "nobody declared")

    def test_past_the_declared_cadence_the_page_says_so(self):
        base = "Date.parse('%s')" % STAMP
        answers = self.js([
            f"verdict('{STAMP}', {base} + 10*60000, 60)",
            f"verdict('{STAMP}', {base} + 120*60000, 60)",
        ])
        self.assertEqual(answers[0], "current")
        self.assertEqual(answers[1], "stale")


class ThePageCollapsesWhatTheReportCollapses(ViewBase):
    """The page repeats the report; it does not out-shout it.

    `reconcile` on a real machine ends on ONE line: "1167 unit(s) on the machine
    that no declaration claims, pass --verbose to list them". The page rendered
    all 1167, so the same run was a summary in the terminal and a wall in the
    browser, and the four declarations the reader came for sat above two hundred
    kilobytes of Apple's own daemons. Which states collapse is decided once, in
    `report`, and read from there: a second list here would drift the first time
    one of them changed.
    """

    def unclaimed(self, count):
        return [self.finding(f"com.vendor.thing{i}", "unmanaged", "info",
                             "on the machine, claimed by no declaration")
                for i in range(count)]

    def test_a_wall_of_unclaimed_units_is_counted_and_not_listed(self):
        page = self.page(findings=self.unclaimed(40))
        self.assertNotIn("com.vendor.thing39", page,
                         "the page listed what the terminal collapses, so the "
                         "same run reads as a summary in one place and a wall "
                         "in the other")
        # Not just "40 appears somewhere": the heading carries that number too,
        # so a page that drops the rows AND the explanation still passes such a
        # check while showing a count of forty above an empty table, which reads
        # as a rendering failure rather than as a summary.
        self.assertIn("counted rather than listed", page,
                      "the rows went away and nothing says where to; a number "
                      "that changes between two renders is the arrival of "
                      "something nobody declared, and it has to be legible")
        self.assertIn("40 further unit", page)

    def test_the_rule_comes_from_the_report_and_is_not_a_second_list(self):
        from engine import report as report_mod
        self.assertEqual({s.value for s in report_mod.COUNTED_ONLY},
                         set(view.COUNTED_ONLY_VALUES),
                         "the page keeps its own idea of what to collapse")

    def test_a_state_the_terminal_lists_is_still_listed_here(self):
        # The counterweight. Collapsing must not swallow the findings that name
        # a machine's own inventory drifting away from its declarations.
        page = self.page(findings=[
            self.finding("share-tunnel", "inventory_stale", "info",
                         "the inventory lists it, neither a declaration nor the "
                         "machine knows it")])
        self.assertIn("share-tunnel", page)


class OnlyWhatIsInServiceIsOnTheBoard(ViewBase):
    """One run was migrated and the page showed twenty two rows.

    Three of them were probe fixtures this skill retired itself while the test
    system was being built, and eighteen were entries in a machine's inventory
    file that name nothing. Both are real, neither is "what runs here", and a
    board that opens with them buries the one line that was the point. Nothing
    is dropped: what leaves the table leaves a counted sentence behind.
    """

    def retired(self):
        import dataclasses
        return dataclasses.replace(
            self.load("calendar-export"),
            retired=model.Retired(at="2026-08-01",
                                  reason="superseded by the test system"))

    def test_a_retired_declaration_is_not_a_row(self):
        page = self.page(workloads=[self.load("calendar-export"), self.retired()])
        # By its heading, not by position: the calendar was later put above this
        # table, and a test that counted <h2> elements went on passing while
        # measuring a different section entirely.
        table = page[page.index("<h2>In service"):]
        table = table[:table.index("</table>")]
        self.assertNotIn("(retired)", table,
                         "history sits in the board's first table, where a reader "
                         "counts rows to learn how much runs here")
        # The count is an element since 2026-08-27, because a filter changes how
        # many rows a reader can see and the script rewrites it. The heading must
        # still SHIP the in-service number, which is what this measures.
        self.assertRegex(page, r'<h2>In service \(<span id="shown">1</span>\)</h2>',
                         "the heading counts what is in service, so it must not "
                         "count what was switched off")

    def test_but_it_is_still_counted_in_a_sentence(self):
        page = self.page(workloads=[self.retired()])
        self.assertIn("retired", page.lower(),
                      "it vanished entirely, so a declaration can be quietly "
                      "lost by retiring it")

    def test_an_inventory_entry_is_not_filed_under_the_machine(self):
        # `inventory_stale` is about infra/remotes/<host>.yaml naming something
        # nothing knows. Filing it under "on the machine" says the opposite of
        # what the finding says.
        page = self.page(findings=[self.finding(
            "share-tunnel", "inventory_stale", "info",
            "the inventory lists it, neither a declaration nor the machine knows it")])
        before = page.split("share-tunnel")[0]
        self.assertNotIn("On the machine", before.split("<h2>")[-1],
                         "an entry that exists ONLY in a file was filed under "
                         "what the machine carries")
        self.assertIn("inventory", before.lower())


class WhenDoesWhatRun(ViewBase):
    """The question a table does not answer, on a 24 hour axis.

    Two rules make the drawing honest rather than decorative, and both are the
    same rule: read the one place, never derive a second opinion.

    **The time comes from `base.start_of`**, the function the unit file itself
    is built from. A drawing that computes its own hour can disagree with the
    machine, and it is the drawing people will believe.

    **The shape comes from the state `reconcile` already decided**, which was
    computed with the cadence, the clock skew and the machine's uptime in hand.
    A picture that re-derives "did it run" from a trace stamp would be a second
    verdict, and the two would part company on the day it mattered.

    The vocabulary is the one the sibling calendar under /betrieb/ already uses,
    so the two read as one tool: filled means it ran, hollow means the
    appointment passed without a trace, and colour never carries a meaning on
    its own.
    """

    def page_for(self, workload, findings=(), runs=None):
        rep = report_mod.Report(findings=list(findings), header="probed",
                                runs=dict(runs or {}))
        return view.render(rep, [workload], generated_at=STAMP)

    def test_a_daily_run_sits_at_its_own_hour_on_the_axis(self):
        w = self.load("calendar-export")
        import dataclasses
        w = dataclasses.replace(
            w, placement=dataclasses.replace(w.placement, kind="recurring"),
            schedule=dataclasses.replace(w.schedule, rrule="FREQ=DAILY",
                                         delivery_at="07:20", every_sec=None,
                                         duration_estimate_min=0))
        page = self.page_for(w)
        # 07:20 of 24 hours. Written as a percentage so the axis stays fluid.
        self.assertIn("30.5", page,
                      "the marker is not at 07:20 of the axis; a calendar whose "
                      "positions are decorative is worse than none")
        self.assertIn("07:20", page)

    def test_the_hour_comes_from_the_same_function_the_unit_file_uses(self):
        # Not a re-implementation living next to it. `start_of` subtracts the
        # declared duration and carries the day shift; a second copy here would
        # place a job that crosses midnight on the wrong day.
        from tests.conftest import SKILL_DIR
        source = (SKILL_DIR / "engine" / "view.py").read_text(encoding="utf-8")
        self.assertIn("start_of", source,
                      "the view works out its own fire time, so the picture and "
                      "the unit file can disagree")

    def marks_at(self, page, pct):
        """Every shape drawn at one position on the axis."""
        import re
        return set(re.findall(rf'class="tick (\S+)" style="left:{pct}', page))

    def test_the_ring_at_an_appointment_says_whether_the_schedule_is_kept(self):
        import dataclasses
        w = self.load("calendar-export")
        w = dataclasses.replace(
            w, placement=dataclasses.replace(w.placement, kind="recurring"),
            schedule=dataclasses.replace(w.schedule, rrule="FREQ=DAILY",
                                         delivery_at="07:20", every_sec=None,
                                         duration_estimate_min=0))
        quiet = self.page_for(w, findings=[self.finding(w.id, "in_sync", "info", "ok")])
        missed = self.page_for(w, findings=[self.finding(w.id, "overdue", "high",
                                                         "no trace since yesterday")])
        self.assertEqual(self.marks_at(quiet, "30.5"), {"due"})
        self.assertEqual(self.marks_at(missed, "30.5"), {"missed"},
                         "an appointment reconcile calls overdue is the gap, and "
                         "the gap is the whole reason to look at this page")

    def test_a_cadence_job_is_a_band_and_not_a_pretended_appointment(self):
        # An interval job has no o'clock. Drawing one would invent an
        # appointment nobody declared, and the reader would wait for it.
        page = self.page_for(self.load("calendar-export"))
        self.assertIn("band", page)
        self.assertNotIn("tick ran", page)

    def test_a_run_that_cannot_be_placed_says_so_instead_of_leaving_a_gap(self):
        import dataclasses
        w = self.load("calendar-export")
        w = dataclasses.replace(
            w, placement=dataclasses.replace(w.placement, kind="recurring"),
            schedule=dataclasses.replace(w.schedule, rrule="FREQ=MONTHLY",
                                         delivery_at=None, every_sec=None))
        page = self.page_for(w)
        self.assertIn("cannot be placed", page,
                      "an empty lane reads as a job with nothing scheduled, "
                      "which is a different statement from 'not drawable here'")

    def test_every_shape_on_the_page_is_in_the_legend(self):
        # Colour never carries a meaning alone here, so the shapes have to be
        # readable, and a shape nobody explains is decoration. The first version
        # of this used an interval fixture, which draws a band and no tick at
        # all: the loop had nothing to iterate and the case passed over an empty
        # legend.
        import dataclasses
        import re
        w = self.load("calendar-export")
        w = dataclasses.replace(
            w, placement=dataclasses.replace(w.placement, kind="recurring"),
            schedule=dataclasses.replace(w.schedule, rrule="FREQ=DAILY",
                                         delivery_at="07:20", every_sec=None,
                                         duration_estimate_min=0))
        page = self.page_for(w)
        body = page[page.index("<body"):]
        legend = body[body.index('class="legend"'):]
        shapes = set(re.findall(r'class="tick (\w+)"', body[:body.index('class="legend"')]))
        self.assertTrue(shapes, "no mark was drawn, so this case measures nothing")
        for shape in shapes:
            # The SAMPLE, not the word. The legend gained entries for the week
            # and the month on 2026-08-27, and their samples carry `class="cell
            # due"` and `class="cell ran"`: a bare substring check for "due"
            # then passed on a legend that explained no tick at all, which the
            # mutation battery caught the same evening.
            self.assertIn(f'class="tick {shape}"', legend,
                          f"the shape {shape!r} appears and is never explained")


class ATraceIsNotAnAppointmentKept(ViewBase):
    """The first version of the calendar drew a lie, on the first real machine.

    `issue-radar` fires at 07:20 and had never done so: its only trace came from
    the verification run at 15:54 during the migration. The mark asked "is there
    a trace at all" and put the answer on the 07:20 appointment, so the page
    said the appointment had been kept. It had not.

    They are two questions and they get two marks on the same lane. The ring at
    the appointment says whether the SCHEDULE is being kept, and only
    `reconcile` may answer that, because it holds the cadence, the clock skew
    and the machine's uptime. The diamond says when something last actually ran,
    and only the machine's own trace may answer that. Neither is derived from
    the other, and matching them up would need a run history this skill does not
    keep and a tolerance nobody has chosen.
    """

    def daily(self, **schedule):
        import dataclasses
        w = self.load("calendar-export")
        fields = dict(rrule="FREQ=DAILY", delivery_at="07:20", every_sec=None,
                      duration_estimate_min=0, timezone="Europe/Berlin")
        fields.update(schedule)
        return dataclasses.replace(
            w, placement=dataclasses.replace(w.placement, kind="recurring"),
            schedule=dataclasses.replace(w.schedule, **fields))

    def page_for(self, workload, findings=(), runs=None):
        rep = report_mod.Report(findings=list(findings), header="probed",
                                runs=dict(runs or {}))
        return view.render(rep, [workload], generated_at=STAMP)

    def test_a_run_at_another_hour_does_not_fill_the_appointment(self):
        import re
        w = self.daily()
        page = self.page_for(w, runs={w.id: ("2026-08-23T13:54:15Z", 0)})
        at_appointment = set(re.findall(r'class="tick (\S+)" style="left:30\.5', page))
        self.assertTrue(at_appointment, "nothing was drawn at the appointment at all")
        self.assertFalse(at_appointment & {"trace", "trace-failed"},
                         "a verification run at 15:54 was drawn onto the 07:20 "
                         "appointment, which says the appointment was kept")

    def test_the_run_gets_its_own_mark_at_its_own_time(self):
        w = self.daily()
        page = self.page_for(w, runs={w.id: ("2026-08-23T13:54:15Z", 0)})
        self.assertIn("trace", page)
        # 15:54 local (Europe/Berlin, summer) of 24 hours = 66.25 percent.
        self.assertIn("66.2", page,
                      "the run was placed at its UTC hour, so every mark on the "
                      "axis is two hours out for half the year")

    def test_a_run_that_failed_is_not_the_same_mark_as_one_that_worked(self):
        w = self.daily()
        page = self.page_for(w, runs={w.id: ("2026-08-23T13:54:15Z", 2)})
        self.assertIn("trace-failed", page)

    def test_without_a_declared_zone_the_run_is_not_placed_at_all(self):
        # The trace is UTC as the host wrote it, and the axis is the machine's
        # own day. Guessing the offset would put every mark hours out, silently.
        w = self.daily(timezone=None)
        page = self.page_for(w, runs={w.id: ("2026-08-23T13:54:15Z", 0)})
        self.assertNotIn('class="tick trace"', page)
        # The deliberate sentence, not any sentence containing those words: with
        # the guard gone, ZoneInfo("None") raises "No time zone found with key
        # None", the message lands in the same place, and a looser check passed
        # over the very defect it was written for.
        self.assertIn("the declaration states no time zone", page,
                      "it declined to place the mark by accident, through an "
                      "exception, rather than because it checked")

    def test_the_appointment_ring_never_reads_the_trace(self):
        # Structural, not a wording check: the ring is decided by a function
        # that is not given the runs at all.
        import inspect as _inspect
        source = _inspect.getsource(view._appointment_shape)
        self.assertNotIn("runs", source,
                         "the mark that judges the schedule can see the trace, "
                         "and the two verdicts will part company on the day it "
                         "matters")


class ASentenceIsNotAnIdentifier(ViewBase):
    """A purpose is prose and must wrap; only the identifier may refuse to.

    Measured from the published page on 2026-08-24: the `state` column, the one
    carrying the verdict, was pushed off the right edge and cut mid-word. The
    cause was one declaration: `.id { white-space: nowrap }` on the whole cell,
    while that cell holds the id AND the purpose underneath it. A sentence of
    eighty characters was therefore forced onto a single line, the first column
    grew past the page's own 68rem, and every column after it went out of view.

    The rule was right for what it was written for and wrong for what it
    inherited. nowrap belongs to an identifier, which must not break across
    lines; a sentence needs the opposite.

    What these tests prove: the purpose is placed in its own element, and that
    element carries an explicit rule releasing it from the ancestor's nowrap.
    What they do NOT prove: how many pixels wide anything ends up. There is no
    layout engine here, so the claim stays at the cause, which is where the
    defect actually lived.
    """

    LONG = ("Daily overview of open issues across all organisations, "
            "delivered to exactly one recipient")

    def test_the_purpose_sits_in_its_own_element(self):
        # Not decoration: a rule can only release the purpose from the cell's
        # nowrap if the purpose has an element of its own to be addressed by.
        html = self.page()
        self.assertRegex(html, r'<td class="id">[^<]+<div class="meta">[^<]+.*?</div>',
                         "the purpose is not in an element of its own inside the "
                         "id cell, so no rule can address it separately")

    def test_the_purpose_is_released_from_the_cells_nowrap(self):
        html = self.page()
        self.assertRegex(
            html, r"\.id\s+\.meta\s*\{[^}]*white-space:\s*normal",
            "the purpose still inherits `white-space: nowrap` from the id cell, "
            "which is what pushed the state column off the page")

    def test_and_the_identifier_itself_still_refuses_to_break(self):
        html = self.page()
        self.assertRegex(html, r"\.id\s*\{[^}]*white-space:\s*nowrap",
                         "an identifier that wraps mid-token is unreadable in a "
                         "different way; the fix must not swap one for the other")

    def test_a_long_purpose_is_bounded_so_it_cannot_dominate_the_row(self):
        """The ceiling moved from the sentence to the COLUMN, on 2026-08-27.

        A `max-width` in character units bounded the sentence and left the
        column itself to be shared out by content. That is how the identifier
        ended up with a quarter of the measure, wrapping every purpose over
        four lines, while three columns holding one short token each floated in
        white. A declared share bounds the same sentence and closes the same
        defect from the side the defect was actually on. The property is
        unchanged: one long sentence must not set the shape of the table.
        """
        html = self.page()
        block = re.search(r"<colgroup>(.*?)</colgroup>", html, re.S)
        self.assertIsNotNone(block, "the columns declare no widths at all, so "
                                    "content decides the shape of the table "
                                    "and the longest sentence wins")
        widths = [int(w) for w in re.findall(r"width:\s*(\d+)%", block.group(1))]
        head = html.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(len(widths), head.count("<th"),
                         f"not every column declares a share: {widths}")
        self.assertEqual(sum(widths), 100,
                         f"the declared shares do not make a whole: {widths}")
        self.assertLessEqual(widths[0], 50,
                             "the identifier column may take at most half the "
                             "measure; past that the verdict is squeezed again")

class APageNobodyRefreshesSaysSo(ViewBase):
    """No declared cadence is a fact about the page, not a reason for silence.

    Measured on 2026-08-24. The page at /workloads/ was published once, by
    hand, and nothing refreshed it. Eight hours later its reader opened it,
    read "In service (1)", and concluded that one run existed. Two did. The
    page was not wrong about the moment it was made; it simply had no way to
    say that the moment was the only thing it could vouch for.

    The age WAS on the page, in small grey type, in brackets. It did not do
    its job, because the headline number reads as a present-tense inventory
    while the age reads as a detail.

    The existing rule stays and is right: without a declared cadence, no
    verdict is drawn, because a threshold nobody chose is a number invented
    here. But "no cadence is declared" is itself something somebody can be
    told, and telling it costs no invention.

    What these tests prove: the two statements are mutually exclusive, and the
    one for the no-cadence case names no interval. What they do NOT prove:
    that a reader notices. That is a question for the eye, not the suite.
    """

    def render(self, **kw):
        rep = report_mod.Report(findings=[], header="")
        return view.render(rep, [self.load("calendar-export")],
                           generated_at=STAMP, **kw)

    def test_without_a_cadence_the_page_says_nothing_refreshes_it(self):
        html = self.render()
        self.assertIn('id="norefresh"', html,
                      "a page that nothing refreshes looks exactly like one "
                      "refreshed a minute ago, and its reader has no way to "
                      "tell them apart")

    def test_the_statement_names_no_interval_it_was_not_given(self):
        html = self.render()
        block = html.split('id="norefresh"', 1)[1].split("</p>", 1)[0]
        self.assertNotRegex(
            block, r"\d+\s*(min|minute|hour|h\b|day)",
            "naming a period here would be the invented threshold the "
            "verdict rule exists to refuse")

    def test_with_a_cadence_the_verdict_takes_over_and_the_statement_goes(self):
        html = self.render(stale_after_min=30)
        self.assertIn('id="stale"', html)
        self.assertNotIn('id="norefresh"', html,
                         "both at once would tell the reader two different "
                         "things about the same page")

    def test_without_a_cadence_there_is_still_no_verdict(self):
        # The older rule, kept under guard: the fix must add a statement, not
        # start drawing a line nobody drew.
        self.assertNotIn('id="stale"', self.render())

    def test_the_readers_clock_is_still_the_one_that_speaks(self):
        # In both cases. The age is what the statement points at, so losing it
        # would make the new sentence refer to nothing.
        for kw in ({}, {"stale_after_min": 30}):
            with self.subTest(kw=kw):
                self.assertIn('<span id="age">', self.render(**kw))

class TheTableCarriesBothLabels(ViewBase):
    """Whose run it is, and what it is called on the machine.

    Asked for by the operator on 2026-08-24. The word means two things in a
    Bridge, and BOTH were missing from the page:

      * `persona_ref`, the sphere a run belongs to. Added to every declaration
        and to every register entry the day before, checked by both gates
        since, and shown by no view at all.
      * the launchd label. The page shows the declaration id, and the unit on
        the machine is called something else (`bridge.<id>`). Anyone holding
        this page next to `launchctl list` had to know the mapping by heart.

    The unit name is ASKED OF THE BACKEND, never rebuilt here. A second
    derivation of a name is how `bridge.issue-radar` ended up filed as foreign
    software this morning: four hand kept prefix lists, already disagreeing.

    Three states for the persona, not two. A declaration may name a sphere, may
    name one of the two reserved answers, or may not have decided. Undecided
    renders as its own word, because an empty cell reads as "belongs to nobody"
    and that is a different claim.
    """

    def page_for(self, name="calendar-export"):
        rep = report_mod.Report(findings=[], header="")
        return view.render(rep, [self.load(name)], generated_at=STAMP)

    def test_every_run_carries_both_labels(self):
        """Both labels, per run. Measured on the RUN, not on the header.

        They used to be two columns and are now a chip and a term in the
        dossier, which is a layout decision; that both facts are on the page
        for every run is the skill's own hard rule and is not. So the test
        follows them to wherever they are rendered instead of asserting the
        shape they happened to have on the day it was written.
        """
        from engine.backends import get_backend
        w = self.load("calendar-export")
        html = self.page_for()
        group = re.search(r'<tbody data-id="%s".*?</tbody>' % re.escape(w.id),
                          html, re.S)
        self.assertIsNotNone(group, "the run has no group of its own")
        block = group.group(0)
        self.assertIn(get_backend(w.placement.runtime).unit_name(w), block,
                      "the run does not carry the name the machine knows it by")
        self.assertRegex(block, r'<dt>sphere</dt>',
                         "the run does not carry the sphere it belongs to")

    def test_the_unit_name_is_the_one_the_backend_gives(self):
        # The corpus entry runs under launchd, so the machine calls it
        # `bridge.<id>`. If this ever stops matching, the page and the machine
        # have started disagreeing about a name, which is the whole defect.
        from engine.backends import get_backend
        w = self.load("calendar-export")
        backend = get_backend(w.placement.runtime)
        self.assertIn(backend.unit_name(w), self.page_for(),
                      "the page does not show the name the backend gives, so "
                      "it is either missing or rebuilt somewhere else")

    def test_a_declaration_without_a_persona_says_undecided(self):
        # Not an empty cell: absent and `_shared` are different answers, and an
        # empty one reads as the second.
        html = self.page_for()
        w = self.load("calendar-export")
        if getattr(w, "persona_ref", None):
            self.skipTest("the corpus entry declares one; covered by the next test")
        self.assertIn("undecided", html)

    def test_the_page_says_so_where_a_runtime_names_nothing(self):
        """Measured on the PAGE, not on the backend.

        The version of this that asked the backend directly was green under a
        view that rebuilt the name itself, which is the exact defect. A run
        under `manual` or `external` is documented, not executed: there is no
        unit, and the page must say that rather than print a name it derived.
        """
        for name in ("chat-channel", "public-funnel"):
            with self.subTest(fixture=name):
                html = self.page_for(name)
                self.assertIn("no unit on the machine", html,
                              "the page prints a unit name for a runtime that "
                              "has none, so it is deriving one instead of "
                              "asking the backend")
                self.assertNotIn(f"bridge.{name}", html,
                                 "a name was invented for a run the machine "
                                 "does not carry")

    def test_a_runtime_with_no_name_on_the_machine_says_so(self):
        # `manual` and `external` are documented, not executed: there is no
        # unit and inventing one would be a claim about a machine nobody asked.
        from engine.backends import get_backend
        for runtime in ("manual", "external"):
            with self.subTest(runtime=runtime):
                self.assertEqual("", get_backend(runtime).unit_name(None),
                                 "a runtime that names nothing must return "
                                 "nothing, not a guess")


class TheVerdictGetsTheRoomItNeeds(ViewBase):
    """A verdict is a word, its reason is a sentence, and a column fits one.

    Measured from the published page on 2026-08-24, after the two label columns
    landed. The table had grown to nine columns inside a 68rem page. Seven of
    them carry a single short token and take their width unconditionally, two
    of them carry prose: the purpose under the id, and the reason under the
    state. The seven won, because a token that refuses to wrap always wins
    against a sentence that can.

    What the reader got: `state`, the one column the table exists to answer,
    squeezed to roughly a tenth of the page while a full English sentence tried
    to fit inside it. The complaint was two words long and exact: too small.

    The earlier fix (ASentenceIsNotAnIdentifier) stopped a sentence from
    breaking the layout. It did not give the verdict any room, because the
    reason still sat in the same narrow cell. So the reason leaves the row: it
    is prose, and prose belongs at the page's measure, not in a column that
    every added label makes narrower.

    What these tests prove: the reason is rendered outside the cell grid, on a
    row of its own that spans the table; each reason still names the state it
    belongs to, so the mapping survives the move even where one run carries
    several findings; the verdict column is floored so the next column added
    cannot crush it again; and the run and its reasons stay visually one unit.
    What they do NOT prove: any pixel width. There is no layout engine here.
    """

    def rows(self):
        f1 = self.finding("calendar-export", "in_sync", "info",
                          "gui/501/bridge.calendar-export matches the declaration")
        f2 = self.finding("calendar-export", "unknown", "info",
                          "calendar-export asked for missing detection, and its "
                          "kind states no cadence this skill can work out")
        return self.page(findings=[f1, f2])

    def test_the_reason_leaves_the_cell_grid(self):
        # The point of the change: a sentence rendered inside the ninth of nine
        # columns has no room, however the column is styled.
        html = self.rows()
        self.assertNotRegex(
            html, r'<td class="state"[^>]*>.*?<div class="hint">',
            "the reason is still inside the state cell, which is the column "
            "being crushed")
        # The number is ASKED of the table, never written down here. It used
        # to say 9, and the day the table grew a tenth column this case went
        # red for a reason that had nothing to do with what it measures: the
        # reason row spanning the WHOLE table, whatever the table is wide.
        import re as _re
        # `<th` and not `<th>`: since the day became a column its header
        # carries a class, and counting only the bare tag missed it and then
        # demanded a span one column too narrow.
        spalten = len(_re.findall(r"<th[ >]", html.split("</thead>")[0]))
        self.assertGreater(spalten, 1, "no table head was rendered at all")
        # The opening tag carries an id since 2026-08-27 (the run row points at
        # it with aria-controls), so the assertion matches the CLASS and the
        # span rather than the literal tag. What it measures is unchanged.
        self.assertRegex(html, rf'<tr class="why"[^>]*><td colspan="{spalten}"',
                         f"the reason row does not span all {spalten} columns of "
                         "the table it belongs to")

    def test_each_reason_still_names_its_state(self):
        # A run can carry several findings. Moving the sentences out of the
        # cell that held their state word would otherwise leave a reader
        # guessing which sentence explains which verdict.
        html = self.rows()
        why = re.search(r'<tr class="why"[^>]*>.*?</tr>', html, re.S)
        self.assertIsNotNone(why, "no reason row was rendered")
        block = why.group(0)
        for state in ("in_sync", "unknown"):
            self.assertIn(state, block,
                          f"the reason row does not name {state!r}, so its "
                          "sentence cannot be mapped back to a verdict")

    def test_the_verdict_column_has_a_floor(self):
        html = self.rows()
        self.assertRegex(
            html, r"\.state\s*\{[^}]*min-width",
            "without a floor the verdict column is crushed again by whatever "
            "column is added next")

    def test_the_verdict_is_not_the_smallest_text_in_its_own_row(self):
        # It is the answer the table exists to give. It was rendered at the
        # table's default while the severity above it and the reason below it
        # both had explicit sizes.
        html = self.rows()
        m = re.search(r"\.state\s*\{([^}]*)\}", html)
        self.assertIsNotNone(m, "no rule addresses the state at all")
        size = re.search(r"font-size:\s*([\d.]+)rem", m.group(1))
        self.assertIsNotNone(size, "the verdict has no explicit size, so it "
                                   "inherits and reads as small print")
        self.assertGreaterEqual(
            float(size.group(1)), 0.875,
            "the verdict is set smaller than the table's own body text")

    def test_a_run_and_its_reasons_stay_one_visual_unit(self):
        # Two rows per run breaks `tbody tr:nth-child(even)` striping: the
        # reason would be striped away from the run it explains. Grouping each
        # run in its own tbody is what keeps the pair together.
        html = self.rows()
        self.assertNotRegex(
            html, r"\.runs\s+tbody\s+tr:nth-child\(even\)",
            "striping in the runs table still counts single rows, so a reason "
            "row is shaded apart from the run it belongs to")
        self.assertRegex(
            html, r"\.runs\s+tbody\s*\{[^}]*border-bottom",
            "nothing draws the boundary of a run at the group level, so the "
            "pair has no edge of its own and a reason floats between two runs")
        self.assertRegex(
            html, r"<tbody[^>]*><tr class=\"run\"[^>]*>.*?<tr class=\"why\"[^>]*>.*?</tbody>",
            "the run and its reason row are not enclosed together")
        # The finding tables are one row per finding and must KEEP ordinary
        # striping; an eighteen-row unstriped table is its own readability bug.
        self.assertRegex(
            html, r"\.findings\s+tbody\s+tr:nth-child\(even\)",
            "the finding tables lost their striping to the runs-table fix")

    def test_a_run_without_findings_still_says_so_on_its_own_row(self):
        # `not reported` is not a healthy state, and the sentence that says so
        # must survive the move out of the cell.
        html = self.page()
        self.assertIn("no finding was produced for this declaration", html,
                      "the unreported case lost its sentence in the move")
        self.assertRegex(html, r'<tr class="why"[^>]*>',
                         "the unreported sentence is not on a reason row")


class NotReportedIsNotAlwaysAMystery(ViewBase):
    """Where the reason for a silence is known, saying it is not optional.

    Measured from a published page on 2026-08-24. A refresher was declared with
    `host: local`, because it runs on the laptop that reaches the served machine
    over ssh, while the page itself is built by reconciling that served machine.
    So the run appeared in the table carrying `not reported`, with the sentence
    "no finding was produced for this declaration, which is not the same as a
    healthy one".

    Every word of that is true and it is still the wrong answer, because the
    page KNEW why: it reconciled one machine and this declaration is placed on
    another. A page that holds the reason and prints the generic sentence
    teaches its reader that `not reported` means nothing in particular, and the
    next time it means a run that stopped.

    This does not make the page reconcile several machines. It makes it say
    which machine it asked.
    """

    def elsewhere(self, hosts):
        w = self.load("calendar-export")
        return view.render(report_mod.Report(findings=[], header=""), [w],
                           generated_at=STAMP, hosts=hosts)

    def declared_host(self):
        return self.load("calendar-export").placement.host

    def test_a_run_placed_on_a_machine_the_page_did_not_ask_says_so(self):
        html = self.elsewhere(("some-other-box",))
        self.assertIn("some-other-box", html,
                      "the page does not name the machine it actually asked")
        self.assertNotIn("no finding was produced for this declaration", html,
                         "the generic sentence is still used where the reason "
                         "is known")

    def test_a_run_on_the_asked_machine_keeps_the_honest_generic_sentence(self):
        # Silence about a run on the machine that WAS reconciled has no known
        # cause, and inventing one would be worse than the generic sentence.
        html = self.elsewhere((self.declared_host(),))
        self.assertIn("no finding was produced for this declaration", html,
                      "a genuinely unexplained silence lost its sentence")

    def test_asking_every_machine_leaves_the_generic_sentence_alone(self):
        # No host filter means nothing was excluded, so nothing is explained.
        html = self.elsewhere(())
        self.assertIn("no finding was produced for this declaration", html,
                      "with no host filter there is no reason to give, and the "
                      "page must not invent one")

    def test_a_run_that_did_report_is_untouched_by_any_of_this(self):
        """Measured against the RUN'S OWN BLOCK, not the whole page.

        It asserted over the whole document until 2026-08-27, when the page
        gained a second and entirely legitimate reason to name a machine: the
        header states when each one came up, and names the ones that would not
        say. A page-wide assertion turned that into a failure of a case about
        something else, which is a test measuring more than its name promises.
        """
        w = self.load("calendar-export")
        f = self.finding(w.id, "in_sync", "info", "matches the declaration")
        html = view.render(report_mod.Report(findings=[f], header=""), [w],
                           generated_at=STAMP, hosts=("some-other-box",))
        self.assertIn("matches the declaration", html)
        self.assertNotIn("some-other-box", self.run_block(html, w.id),
                         "a finding exists, so there is no silence to explain")


class ThePageIsPlainTextAllTheWayDown(ViewBase):
    """A rendered page travels as an argument, and argv has no room for NUL.

    Measured on 2026-08-24. A separator was written into the stylesheet as the
    CSS escape `\\00B7`. The stylesheet is a triple quoted Python string, so
    Python read `\\00` as an octal escape long before any browser saw CSS: the
    page carried a real NUL byte, and `workload publish` died inside subprocess
    with "embedded null byte", nowhere near the stylesheet.

    The house rule this breaks is the same one that governs every generated
    file here: write the character, never an escape for it.

    The guard is deliberately wider than that one byte. Any C0 control
    character in generated markup is either a mistake of this shape or invalid
    XML, and tab, newline and carriage return are the only ones with a job.
    """

    def test_no_control_characters_survive_into_the_page(self):
        html = self.page()
        allowed = {"\t", "\n", "\r"}
        bad = sorted({c for c in html if ord(c) < 0x20 and c not in allowed}
                     | {c for c in html if ord(c) == 0x7F})
        self.assertEqual(
            bad, [],
            "control characters in the page: "
            + ", ".join(f"U+{ord(c):04X}" for c in bad)
            + ". A page carrying one cannot be passed as a process argument.")

    def test_the_page_survives_a_round_trip_as_a_process_argument(self):
        # The exact operation that failed: the page becomes one argv element.
        import subprocess
        html = self.page()
        done = subprocess.run(["/bin/cat"], input=html, text=True,
                              capture_output=True, check=False)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(done.stdout), len(html))


class TwoAppointmentsAreTwoMarksOnOneLane(ViewBase):
    """A run that answers twice a day is drawn twice, on its own lane.

    The calendar reads one appointment per declaration and stores it in a
    single scalar. Handed a run with two, it would place the first and drop the
    second WITHOUT SAYING SO: the lane would look exactly like a run that fires
    once, and the drawing would assert something the unit files contradict.

    Gate 3 of the visual-output rules covers precisely this case in two
    sentences that apply here unchanged: anything that cannot be placed says
    so, and the hour comes from the same function the unit file is rendered
    from, so the drawing and the machine cannot disagree about when a job
    fires. A silently dropped appointment breaks both.

    The trace mark stays what it is: a SECOND kind of mark, for what the
    machine recorded, never merged with an appointment. Two appointments make
    two appointment marks, not an appointment and a trace.
    """

    def lane(self):
        w = self.load("twice-daily-report")
        rep = report_mod.Report(findings=[], header="")
        rows = [lane for lane in view.lanes(rep, [w]) if lane.workload_id == w.id]
        self.assertEqual(len(rows), 1,
                         "one declaration must stay ONE lane; a lane per "
                         "appointment would make a reader count runs and get "
                         "the wrong number")
        return rows[0]

    def test_both_appointments_are_placed_on_the_axis(self):
        marks = self.lane().appointments
        self.assertEqual(len(marks), 2,
                         "an appointment was dropped from the drawing without "
                         "the drawing saying so")

    def test_each_mark_sits_at_its_own_hour(self):
        pcts = sorted(round(m.at_pct, 2) for m in self.lane().appointments)
        self.assertEqual(pcts, [round(390 / 14.4, 2), round(750 / 14.4, 2)],
                         "the marks are not at 06:30 and 12:30")

    def test_the_hours_come_from_the_function_the_unit_file_uses(self):
        # Same rule as the single-appointment case: the drawing and the machine
        # may not disagree about when a job fires, and the only way to promise
        # that is to ask the same function.
        w = self.load("twice-daily-report")
        from engine.backends import base as backend_base
        expected = sorted((h * 60 + m) for _, h, m, _ in backend_base.starts_of(w))
        drawn = sorted(round(mark.at_pct * 14.4) for mark in self.lane().appointments)
        self.assertEqual(drawn, expected)

    def test_the_lane_names_both_times_for_a_reader_without_the_picture(self):
        label = self.lane().label
        self.assertIn("06:30", label)
        self.assertIn("12:30", label)

    def test_a_single_appointment_run_still_draws_exactly_one_mark(self):
        w = self.load("daily-health-report")
        rep = report_mod.Report(findings=[], header="")
        lane = [l for l in view.lanes(rep, [w]) if l.workload_id == w.id][0]
        self.assertEqual(len(lane.appointments), 1,
                         "the ordinary case changed shape, which it must not")

    def test_the_page_draws_a_tick_for_every_appointment(self):
        # Measured on the rendered HTML, not on the dataclass: a mark that
        # exists in the model and never reaches the page is the same defect.
        w = self.load("twice-daily-report")
        html = self.page(workloads=[w])
        # The TRACK inside this run's own block, not the whole page: the
        # legend renders sample ticks of its own, and a count taken over both
        # would pass while the run's day stayed empty.
        track = re.search(r'<div class="track">(.*?)</div>',
                          self.run_block(html, w.id), re.S)
        self.assertIsNotNone(track, "the run has no track on the page")
        self.assertEqual(len(re.findall(r'class="tick ', track.group(1))), 2,
                         "the page draws fewer marks than the run has "
                         f"appointments: {track.group(1)!r}")


class TheTableNamesEveryUnitAndEveryTime(ViewBase):
    """A run with two units must not read as a run with none.

    MEASURED ON THE PUBLISHED PAGE, 2026-08-24, an hour after the migration
    that created the case. The row for a run with two appointments said
    "no unit on the machine" in the unit column and "-" in the when column,
    while both of its units were loaded, in sync and had just delivered.

    Two separate causes, one shape. `unit_name` asks the backend for THE unit
    and the backend refuses, correctly, where there are several; the view
    caught the refusal and rendered the empty answer, which is the sentence
    reserved for a runtime that names nothing at all. `when` reads the
    shorthand fields, which a declaration using `appointments` does not carry.

    Both are the same mistake: a plural fact squeezed into a place built for
    one, answered with the word for "none". The reserved word for absence must
    keep meaning absence, or the next genuinely unnamed run reads as normal.
    """

    def row(self, spec="twice-daily-report"):
        w = self.load(spec)
        rows = view.rows(report_mod.Report(findings=[], header=""), [w])
        return [r for r in rows if r.workload_id == w.id][0]

    def test_both_unit_names_are_shown(self):
        unit = self.row().unit
        for name in ("morning", "midday"):
            self.assertIn(f"bridge.twice-daily-report.{name}", unit,
                          f"the {name} unit is not named: {unit!r}")

    def test_a_run_with_units_never_says_it_has_none(self):
        # Measured on the RENDERED cell, not on the Row field. The reserved
        # sentence is added at render time, so a test on the dataclass sees an
        # empty string and passes while the page says the opposite of the truth.
        html = self.page(workloads=[self.load("twice-daily-report")])
        cell = re.search(r'<dd class="unit">(.*?)</dd>', html, re.S)
        self.assertIsNotNone(cell, "no unit cell on the page")
        self.assertNotIn(
            "no unit", cell.group(1).lower(),
            "the sentence reserved for a runtime that names nothing was used "
            "for a run with two units; the reserved word must keep meaning "
            f"absence, or the next genuinely unnamed run reads as normal: "
            f"{cell.group(1)!r}")

    def test_a_single_appointment_run_shows_exactly_one_name(self):
        unit = self.row("block-style-report").unit
        self.assertTrue(unit and "\n" not in unit and "," not in unit,
                        f"the ordinary case changed shape: {unit!r}")

    def test_the_when_column_carries_both_times(self):
        when = self.row().when
        self.assertIn("06:30", when)
        self.assertIn("12:30", when)

    def test_the_when_column_carries_the_recurrence(self):
        # A time without its day set is half an answer: 06:30 on which days?
        self.assertIn("BYDAY", self.row().when.upper().replace("BYDAY", "BYDAY"))

    def test_the_page_renders_both_names_in_the_cell(self):
        html = self.page(workloads=[self.load("twice-daily-report")])
        cell = re.search(r'<dd class="unit">(.*?)</dd>', html, re.S)
        self.assertIsNotNone(cell, "no unit cell on the page")
        for name in ("morning", "midday"):
            self.assertIn(name, cell.group(1),
                          f"the page does not show the {name} unit: {cell.group(1)!r}")

    def test_the_two_names_are_separated_in_the_markup(self):
        # A newline between them is whitespace to HTML, and the cell carries
        # `white-space: nowrap` for the identifiers, so the two labels would run
        # into one another as a single unreadable token. The break has to be
        # markup.
        html = self.page(workloads=[self.load("twice-daily-report")])
        cell = re.search(r'<dd class="unit">(.*?)</dd>', html, re.S).group(1)
        self.assertRegex(
            cell, r"morning.*?<br\s*/?>.*?midday",
            f"the two unit names are not separated by markup: {cell!r}")


class ATabLeftOpenTellsTheTruth(ViewBase):
    """The page ages while it is being READ, not only while it is being made.

    `Date.now()` used to be read exactly once, at load. A tab left open then
    said `just now` for as long as it stayed open and never revealed its stale
    banner, so at three in the morning it still claimed to be the present. That
    is the failure this page exists to prevent, moved one step along, and worse
    than the original: a page nobody refreshed at least kept quiet, while this
    one asserted freshness out loud.

    Everything below RUNS the wiring against a stub document with a clock the
    test controls. Asserting that the source contains `setInterval` would be
    the same weak shape this suite keeps finding.
    """

    def wired(self, checks, *, stale_after_min="60", poll_sec=None, stamp=STAMP):
        """Execute the page's wiring against a fake document and a fake clock."""
        import json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path as _Path
        node = shutil.which("node")
        if not node:
            self.skipTest("no node on this machine, so the page's wiring is not measured here")
        attrs = {"data-stale-after-min": stale_after_min}
        if poll_sec is not None:
            attrs["data-poll-sec"] = str(poll_sec)
        stub = """
var CLOCK = Date.parse(%s);
Date.now = function () { return CLOCK; };
var ATTRS = %s;
var timers = [];
globalThis.setInterval = function (fn, ms) { timers.push({ fn: fn, ms: ms }); return timers.length; };
globalThis.localStorage = { getItem: function () { return null; }, setItem: function () {} };
globalThis.location = { href: 'http://example/', reload: function () { RELOADED = true; } };
var RELOADED = false;
var NODES = {
  stamp: { getAttribute: function () { return %s; } },
  age: { textContent: '' },
  stale: { hidden: true, removeAttribute: function () { this.hidden = false; } }
};
globalThis.document = {
  documentElement: {
    getAttribute: function (k) { return ATTRS[k] === undefined ? null : ATTRS[k]; },
    setAttribute: function () {}
  },
  getElementById: function (id) { return NODES[id] === undefined ? null : NODES[id]; }
};
function advance(ms) { CLOCK = CLOCK + ms; }
function fireEvery(ms) { timers.forEach(function (t) { if (t.ms === ms) { t.fn(); } }); }
""" % (json.dumps(stamp), json.dumps(attrs), json.dumps(stamp))
        harness = "\n".join([stub, view._JS, "const out = [];",
                              *[f"out.push({c});" for c in checks],
                              "console.log(JSON.stringify(out));"])
        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / "wired.js"
            path.write_text(harness, encoding="utf-8")
            done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0,
                         f"the page's wiring does not run: {done.stderr}")
        return json.loads(done.stdout)

    def test_the_age_is_recomputed_while_the_tab_stays_open(self):
        said = self.wired([
            "NODES.age.textContent",
            "(advance(3 * 3600000), fireEvery(30000), NODES.age.textContent)",
        ])
        self.assertEqual(said[0], " (just now)", "the age was not written at load")
        self.assertEqual(
            said[1], " (3 h ago)",
            "three hours passed with the tab open and the page still said `just "
            "now`. Reading the clock once is what made an eight hour old page "
            "look like the present in the first place")

    def test_a_tab_left_open_reveals_its_own_stale_banner(self):
        said = self.wired([
            "NODES.stale.hidden",
            "(advance(120 * 60000), fireEvery(30000), NODES.stale.hidden)",
        ])
        self.assertTrue(said[0], "a fresh page must not shout")
        self.assertFalse(
            said[1],
            "twice the declared limit went by with the tab open and the banner "
            "stayed hidden, so the one sentence that would have warned the "
            "reader was decided once and never revisited")

    def test_without_a_declared_cadence_the_page_never_asks_for_a_newer_copy(self):
        said = self.wired(["timers.map(function (t) { return t.ms; })"])
        self.assertEqual(
            said[0], [30000],
            "with no cadence declared there must be exactly one timer, the one "
            "that ages the page. A polling rate nobody chose would be invented, "
            "which is the same rule the staleness verdict already follows")

    def test_a_declared_cadence_adds_exactly_one_more_timer(self):
        said = self.wired(["timers.map(function (t) { return t.ms; })"], poll_sec=120)
        self.assertEqual(sorted(said[0]), [30000, 120000],
                         "the declared cadence has to reach the page in seconds")

    def test_the_page_finds_the_moment_in_a_real_rendering_of_itself(self):
        """The coupling between what the renderer writes and what the poll reads."""
        page = self.page()
        answers = self.js([f"stampIn({page!r}.replace(/\\n/g, String.fromCharCode(10)))"])
        self.assertEqual(
            answers[0], STAMP,
            "the poll looks for the moment by string search, so it breaks "
            "silently the day the renderer spells that element differently. "
            "Feeding it a hand-written sample would never notice")

    def test_an_answer_that_is_not_newer_is_not_reloaded_on(self):
        answers = self.js([
            f"isNewer('{STAMP}', '{STAMP}')",
            f"isNewer('{STAMP}', '2020-01-01T00:00:00+02:00')",
            f"isNewer('{STAMP}', 'gestern nachmittag')",
            f"isNewer('{STAMP}', null)",
            f"isNewer('{STAMP}', '2099-01-01T00:00:00+02:00')",
        ])
        self.assertEqual(
            answers, [False, False, False, False, True],
            "an unreadable or older answer must not trigger a reload: it would "
            "throw away a page that is still saying something true, and replace "
            "it with whatever the server happened to hand back")


class TheStripSaysHowItHasBeenGoing(ViewBase):
    """The last firing is one fact; how the last two dozen went is another.

    A page showing only the newest run cannot distinguish a job that has been
    clean for a month from one that failed twice this week and happened to
    succeed at the moment somebody looked. Both render identically, and the
    second one is the reason anybody opens this page.
    """

    HISTORIE = (
        ("2026-08-24T06:30:00Z", 143, "expired", "calendar-export"),
        ("2026-08-25T06:30:00Z", 0, "ok", "calendar-export"),
        ("2026-08-26T06:30:00Z", 1, "failed", "calendar-export"),
    )

    def seite(self, historie=None, **kw):
        return self.page(history={"calendar-export": historie
                                  if historie is not None else self.HISTORIE}, **kw)

    def zelle(self, html):
        found = re.search(r'<td class="recorded">(.*?)</td>', html, re.S)
        self.assertIsNotNone(found, f"no recorded cell was rendered:\n{html[:600]}")
        return found.group(1)

    def test_one_mark_per_recorded_run(self):
        marks = re.findall(r'class="mark[^"]*"', self.zelle(self.seite()))
        self.assertEqual(len(marks), len(self.HISTORIE),
                         "the strip does not carry one mark per recorded run")

    def test_the_oldest_run_is_on_the_left(self):
        zelle = self.zelle(self.seite())
        erste = re.search(r'title="([^"]+)"', zelle).group(1)
        self.assertIn("2026-08-24", erste,
                      "the strip does not read left to right in time, so a "
                      "reader counting backwards counts the wrong way")

    def test_every_mark_carries_its_stamp_and_return_value(self):
        zelle = self.zelle(self.seite())
        self.assertIn("2026-08-26T06:30:00Z", zelle)
        self.assertIn("rc=1", zelle)
        self.assertIn("failed", zelle)

    def test_a_failed_run_is_a_different_shape_than_a_good_one(self):
        # Shape and not colour: the page is read on a projector and by people
        # who cannot tell two hues apart, and rules/visual-output.md says so.
        zelle = self.zelle(self.seite())
        self.assertIn(view.STRIP_SHAPES["failed"], zelle)
        self.assertIn(view.STRIP_SHAPES["ok"], zelle)
        self.assertNotEqual(view.STRIP_SHAPES["failed"], view.STRIP_SHAPES["ok"])

    def test_every_shape_on_the_strip_is_in_the_legend(self):
        html = self.seite()
        legende = html.split('class="meta">recorded:')[-1][:400]
        for wort, form in view.STRIP_SHAPES.items():
            with self.subTest(verdict=wort):
                self.assertIn(form, legende,
                              f"the shape for {wort} is drawn and never explained")

    def test_a_verdict_this_page_does_not_know_is_a_mark_and_not_a_gap(self):
        html = self.seite((("2026-08-26T06:30:00Z", 0, "quiesced", "calendar-export"),))
        self.assertIn(view.STRIP_UNKNOWN, self.zelle(html),
                      "a fifth verdict from the guard vanishes into the four "
                      "this page happens to know")

    def test_nothing_recorded_says_so_instead_of_leaving_a_gap(self):
        zelle = self.zelle(self.page())
        self.assertIn("nothing recorded", zelle,
                      "an empty cell reads as a run that went fine")

    def test_the_cap_in_the_sentence_is_the_cap_that_was_applied(self):
        # Asked of the module that applies it. A number typed into the page
        # promises a span the page may not show, and a reader counts the marks
        # and believes the sentence.
        from engine import reconcile as reconcile_mod
        self.assertIn(f"at most {reconcile_mod.STRIP_MAX} per", self.seite())

    def test_a_mark_from_a_second_appointment_names_which_one(self):
        html = self.seite((("2026-08-26T06:30:00Z", 0, "ok", "calendar-export.mittags"),))
        self.assertIn("calendar-export.mittags", self.zelle(html),
                      '"the midday one failed" is a different sentence from '
                      '"it failed"')


class ARunThatNeverEndsHasNoRunsToShow(ViewBase):
    """For this kind the guard writes a line when the CHILD returns.

    So its strip is a list of deaths. Drawn without a word, four crashes read
    as four healthy firings, and a daemon that has been up for weeks reads as
    a job where nothing ever happened.
    """

    def daemon(self, history=None):
        w = self.load("long-running-poller")
        return self.page(workloads=[w],
                         history={w.id: history} if history else None)

    def zelle(self, html):
        return re.search(r'<td class="recorded">(.*?)</td>', html, re.S).group(1)

    def test_the_premise_this_case_rests_on(self):
        self.assertIn(self.load("long-running-poller").placement.kind,
                      model.CONTINUOUS_KINDS,
                      "the fixture is not a continuous kind, so this class "
                      "measures nothing")

    def test_marks_are_named_as_ends_and_not_as_runs(self):
        zelle = self.zelle(self.daemon(
            (("2026-08-26T10:33:22Z", 137, "failed", "long-running-poller"),)))
        self.assertIn("not runs", zelle,
                      "the strip of a continuous kind is drawn without saying "
                      "what its marks are")

    def test_an_empty_strip_is_the_good_case_and_says_which(self):
        zelle = self.zelle(self.daemon())
        self.assertIn("writes a line when it stops", zelle,
                      "for this kind an empty strip means it never stopped, "
                      "and a bare empty cell reads as the opposite")


class WhoIsDeclaredIsNotWhoWasReached(ViewBase):
    """Declared and delivered are two facts, and they fail independently.

    Nothing on the execution path reads `response.recipients` today. A line
    that printed them beside a green mark would be this page claiming a
    delivery it never measured, which is the 2026-08-23 calendar mistake with
    a different subject.
    """

    def seite(self):
        return self.page(workloads=[self.load("daily-health-report")])

    def test_the_premise_the_fixture_names_somebody(self):
        w = self.load("daily-health-report")
        self.assertTrue(w.response.recipients,
                        "the fixture declares no recipient, so this class "
                        "measures nothing")

    def test_the_group_is_named(self):
        w = self.load("daily-health-report")
        gruppe = w.response.recipients[0].mandant
        if not gruppe:
            self.skipTest("the fixture names no group")
        self.assertIn(gruppe, self.seite())

    def test_no_person_slug_reaches_the_page(self):
        # A person slug IS a name, and this page is served over a network.
        w = self.load("daily-health-report")
        html = self.seite()
        for recipient in w.response.recipients:
            person = getattr(recipient, "person", "")
            if person:
                with self.subTest(person=person):
                    self.assertNotIn(person, html,
                                     "a person named in a declaration reached "
                                     "a page every device on the network reads")

    def test_the_sentence_says_which_of_the_two_facts_it_is(self):
        html = self.seite()
        self.assertIn("Declared, not delivered", html,
                      "the page states recipients without saying that nothing "
                      "here measured whether anything arrived")



class TheLinkBarNavigatesAndMeasuresNothing(ViewBase):
    """A link to a neighbouring page is not a reading of it.

    This page has never opened any of them. It cannot know when one was last
    written, whether the producer behind it still runs, or whether it is there
    at all. A tile with a colour, a tick or an age on it would state every one
    of those, and a picture is believed faster than a sentence and is almost
    never diffed: rules/visual-output.md Gate 3. So the bar is links and a
    sentence saying what it is, and nothing else.

    The targets come from configuration and never from this file. The skill is
    core; a host name, a port or a path in the renderer would be one instance's
    data shipped to every Bridge that pulls it.
    """

    LINKS = (("Operations", "../betrieb/"), ("Services", "../betrieb/dienste.html"))

    def bar(self, html) -> str:
        start = html.find('<nav class="links"')
        if start < 0:
            return ""
        return html[start:html.index("</nav>", start) + len("</nav>")]

    def test_without_configuration_there_is_no_bar_and_nothing_breaks(self):
        # The normal case. A Bridge that publishes one page has no neighbours,
        # and a bar invented for it would point at pages that do not exist.
        html = self.page()
        self.assertEqual(self.bar(html), "")
        self.assertIn("<h1>Workloads</h1>", html, "the page still rendered")

    def test_a_configured_link_appears_with_its_label_and_its_target(self):
        bar = self.bar(self.page(links=self.LINKS))
        self.assertIn('href="../betrieb/"', bar)
        self.assertIn(">Operations<", bar)
        self.assertIn(">Services<", bar)

    def test_the_bar_says_that_it_opened_none_of_them(self):
        # Without the sentence a reader takes a link on a dashboard for a link
        # the dashboard vouches for, which is the assertion nobody measured.
        bar = self.bar(self.page(links=self.LINKS))
        self.assertIn(view.LINKS_NOTE, bar)

    def test_the_bar_wears_no_mark_that_could_read_as_a_state(self):
        bar = self.bar(self.page(links=self.LINKS))
        for offender in ("sev-", "tick", "mark-", "band", "strip",
                         "data-stale", "unreported", " ago", "id=\"age\""):
            with self.subTest(offender=offender):
                self.assertNotIn(offender, bar,
                                 "the bar carries something shaped like a "
                                 "verdict about a page this one never opened")

    def test_a_label_is_data_and_never_markup(self):
        # Same rule as every other value on this page. The bar is the newest
        # surface and therefore the one most likely to be forgotten.
        bar = self.bar(self.page(links=(('<script>x</script>', '"><b>'),)))
        self.assertNotIn("<script>", bar)
        self.assertNotIn('"><b>', bar)
        self.assertIn("&lt;script&gt;", bar)

    def test_half_an_entry_is_not_drawn_as_a_dead_link(self):
        # A link with no target navigates nowhere and looks exactly like one
        # that does. The command line refuses such an entry outright; the
        # renderer's own answer is to draw nothing rather than a decoy.
        bar = self.bar(self.page(links=(("Operations", "   "),)))
        self.assertEqual(bar, "")

    def test_the_bar_stands_above_the_banners_it_is_not_about(self):
        html = self.page(links=self.LINKS, header="0 of 2 probed")
        self.assertLess(html.find('<nav class="links"'), html.find('class="banner"'),
                        "navigation belongs at the top; a banner about THIS "
                        "page must not be read as a caption for links to other "
                        "ones")


class TheBarCarriesConfiguredDataAndNothingOfItsOwn(ViewBase):
    """What reaches the bar is the caller's, and it reaches it as DATA.

    Two separate properties. The order and the targets are the configuration's
    to decide, and a renderer that reordered or supplied them would be deciding
    something about an instance from inside a core skill. And both halves of an
    entry are somebody's text, so both go through the escaper: a label is the
    obvious one, a target is the one that looks like markup already.
    """

    def bar(self, links):
        html = view.render(report_mod.Report(findings=[], header=""),
                           [self.load("calendar-export")], generated_at=STAMP,
                           links=links)
        found = re.search(r"<nav class=\"links\".*?</nav>", html, re.S)
        return found.group(0) if found else ""

    def test_every_entry_appears_in_the_order_it_was_configured(self):
        bar = self.bar((("One", "../one/"), ("Two", "../two/")))
        self.assertLess(bar.index("One"), bar.index("Two"),
                        "the renderer sorted a list somebody else put in order")

    def test_a_target_is_data_and_never_markup(self):
        # The half that looks like markup already, so it is the half that gets
        # written without an escaper.
        bar = self.bar((("x", '../x/" onclick="alert(1)'),))
        self.assertNotIn('onclick="alert(1)"', bar)
        self.assertIn("&quot;", bar)

    def test_this_skill_names_no_target_of_its_own(self):
        # Measured rather than promised: a default bar in a core skill would
        # publish one instance's addresses from every Bridge that pulled it.
        self.assertEqual(self.bar(()), "")
        self.assertEqual(self.bar(((" ", " "),)), "",
                         "an entry with nothing in it was drawn as a link "
                         "pointing at this page")


class TheFilterIsArithmeticAndNotDecoration(ViewBase):
    """`facetMatch` is executed, never read. A predicate whose test asserts that
    the source contains an `if` is the failure this suite exists to catch."""

    def test_nothing_chosen_matches_everything(self):
        # The empty case is the one a reader is in when the page opens, and it
        # must be the SAME code path as "show all". Two paths disagree.
        said = self.js(["facetMatch({kind: ['agent']}, {})",
                        "facetMatch({}, {})",
                        "facetMatch({kind: ['agent']}, {kind: []})"])
        self.assertEqual(said, [True, True, True],
                         "an unfiltered page hides rows")

    def test_values_inside_one_facet_are_or(self):
        # Asking for agents AND daemons means both, not neither.
        said = self.js(["facetMatch({kind: ['agent']}, {kind: ['agent', 'daemon']})",
                        "facetMatch({kind: ['daemon']}, {kind: ['agent', 'daemon']})",
                        "facetMatch({kind: ['interval']}, {kind: ['agent', 'daemon']})"])
        self.assertEqual(said, [True, True, False],
                         "the values of one facet are not an OR")

    def test_facets_are_and_across_each_other(self):
        # agents ON THIS host, not agents plus everything on this host.
        said = self.js([
            "facetMatch({kind: ['agent'], host: ['a']}, {kind: ['agent'], host: ['a']})",
            "facetMatch({kind: ['agent'], host: ['b']}, {kind: ['agent'], host: ['a']})",
        ])
        self.assertEqual(said, [True, False],
                         "two facets are not an AND, so a filter widens instead "
                         "of narrowing")

    def test_a_run_carrying_several_values_matches_on_any_of_them(self):
        # `state` is a list because one run can carry several findings, and a
        # filter for the milder verdict must still find a run that has it.
        said = self.js([
            "facetMatch({state: ['drifted', 'overdue']}, {state: ['drifted']})",
            "facetMatch({state: ['drifted', 'overdue']}, {state: ['absent']})",
        ])
        self.assertEqual(said, [True, False],
                         "a run with several states is matched on only one")

    def test_a_facet_the_run_does_not_carry_never_matches(self):
        # Absence is not a wildcard. A run without the attribute must fall out
        # of a filter that asks for a value, not slip through it.
        said = self.js(["facetMatch({}, {kind: ['agent']})"])
        self.assertEqual(said, [False],
                         "a run missing the facet passes a filter for it")


class TheFacetBarIsBuiltFromWhatIsThere(ViewBase):
    """Facets come from the runs on the page. A hardcoded list would ship one
    instance's vocabulary to every other, and this skill is core."""

    def test_a_facet_with_one_value_is_not_drawn(self):
        # Measured on this instance the day it was written: host, runtime and
        # owner each had exactly one value. A row of buttons offering the single
        # answer every run gives teaches a reader the bar is useless.
        page = self.page()
        self.assertNotRegex(page, r'data-facet="host"',
                            "a facet with a single value was drawn anyway")

    def test_a_facet_with_two_values_is_drawn_with_its_counts(self):
        second = self.load("calendar-export")
        second = second.__class__(**{**second.__dict__,
                                     "id": "other-run",
                                     "placement": second.placement.__class__(
                                         **{**second.placement.__dict__,
                                            "kind": "daemon"})})
        page = self.page(workloads=[self.load("calendar-export"), second])
        self.assertRegex(page, r'data-facet="kind" data-value="daemon"',
                         "the second kind did not become a filter")
        self.assertRegex(page, r'data-value="interval"[^>]*>interval'
                               r'<span class="n">1</span>',
                         "the button does not carry how many runs it would show")

    def test_the_bar_ships_hidden(self):
        # A control that cannot act must not be on the page: without scripting
        # the table is complete and unfiltered, which is honest.
        second = self.load("calendar-export")
        second = second.__class__(**{**second.__dict__, "id": "other-run",
                                     "placement": second.placement.__class__(
                                         **{**second.placement.__dict__,
                                            "kind": "daemon"})})
        page = self.page(workloads=[self.load("calendar-export"), second])
        self.assertRegex(page, r'<div class="facets" id="facets" hidden>',
                         "the filter bar is visible before anything can use it")

    def test_a_run_is_on_the_page_exactly_once_and_carries_its_own_day(self):
        """The axis and the table used to be two lists of the same runs.

        Every declaration appeared twice, once as a lane and once as a row,
        each holding half of what is known about it, and the filter had to hide
        both or leave marks belonging to nothing behind. They are one element
        now, which is why this test measures a COUNT: the defect it replaces
        cannot come back as long as a run has exactly one block.
        """
        page = self.page()
        self.assertEqual(len(re.findall(r'<tbody data-id="calendar-export"', page)), 1,
                         "the run is on the page more than once, so a reader "
                         "has to match two lists by name to answer one question")
        block = self.run_block(page, "calendar-export")
        self.assertRegex(block, r'<td class="day">',
                         "the run's own day is not in its row, so it is either "
                         "somewhere else on the page or nowhere")


class TheMachinesOwnUnitsAreNamedAndNotOnlyCounted(ViewBase):
    """The list of services a machine really carries, built here.

    That list is the good idea of the neighbouring operations page, and until
    2026-08-27 this page reached for it by FRAMING that page, which put a
    second design with its own header, navigation and stamp inside this one.
    The reader's verdict on that was blunt and correct.

    It never needed framing. This skill's own probe already sees every unit on
    the machine; it was adding them all up into a single number. Measured on
    one machine that day: 1834 belong to the operating system and 32 to its
    owner. Listing all of them is unreadable, counting all of them says nothing
    about the ones somebody put there, and deciding which is which by looking
    at a name is exactly the kind of guess this skill is built against. So the
    prefixes come from configuration, and with none configured nothing changes.

    Nothing is adopted either way: every row here is this run's own finding
    about a unit it probed itself, not a figure read off somebody's page.
    """

    #: Generic on purpose: a real prefix here would be one instance's inventory
    #: written into a file that ships to every other bridge, and the promote
    #: gate of this very suite refuses it.
    MINE, THEIRS = "com.vendor.", "com.platform."

    def units(self):
        return [self.finding(f"{self.MINE}thing", "unmanaged", "info",
                             f"gui/501/{self.MINE}thing runs here"),
                self.finding(f"{self.THEIRS}thing", "unmanaged", "info",
                             f"gui/501/{self.THEIRS}thing runs here")]

    def test_a_configured_prefix_is_named(self):
        page = self.page(findings=self.units(), machine_units=(self.MINE,))
        self.assertIn(f"{self.MINE}thing", page,
                      "a unit the reader asked to see was folded into a number")

    def test_everything_else_stays_a_number(self):
        page = self.page(findings=self.units(), machine_units=(self.MINE,))
        self.assertNotIn(f"{self.THEIRS}thing", page,
                         "the operating system's own units were listed, which "
                         "is eighteen hundred rows nobody reads")
        self.assertRegex(page, r"And 1 further unit\(s\)",
                         "what was left out is not counted, so the page shows "
                         "a slice and reads as the whole machine")

    def test_without_configuration_nothing_is_named(self):
        page = self.page(findings=self.units())
        self.assertNotIn(f"{self.MINE}thing", page,
                         "a bridge that configured nothing had a prefix chosen "
                         "for it")
        self.assertRegex(page, r"And 2 further unit\(s\)")

    def many(self, n=6):
        """Enough of them for the repetition to be the point."""
        return [self.finding(f"{self.MINE}thing-{i}", "unmanaged", "info",
                             f"gui/501/{self.MINE}thing-{i} runs on host-a and "
                             "no declaration claims it")
                for i in range(n)]

    def test_the_same_sentence_is_not_repeated_once_per_unit(self):
        """Measured on the live page: thirty-two rows, each carrying the same
        sentence with the name already in the cell beside it. About eleven
        hundred pixels of one sentence, in a section that is context."""
        page = self.page(findings=self.many(), machine_units=(self.MINE,))
        said = page.count("no declaration claims it</li>")
        self.assertEqual(said, 0,
                         "the sentence is back in the body of every entry")
        self.assertNotIn("<th>detail</th>", page.split("On the machine", 1)[1],
                         "the undeclared units are a table with a column "
                         "repeating one sentence per row again")

    def test_every_name_keeps_its_own_sentence(self):
        """Nothing was dropped, only stopped from being said again: the
        sentence is on the cursor of the name it belongs to."""
        page = self.page(findings=self.many(), machine_units=(self.MINE,))
        for i in range(6):
            self.assertRegex(
                page,
                r'<li title="[^"]*%sthing-%d[^"]*">%sthing-%d</li>'
                % (re.escape(self.MINE), i, re.escape(self.MINE), i),
                f"unit {i} lost the sentence that explains it")

    def test_the_names_are_in_an_order_a_reader_can_use(self):
        out = [f.workload_id for f in self.many()]
        page = self.page(findings=list(reversed(self.many())),
                         machine_units=(self.MINE,))
        found = re.findall(r'<li title="[^"]*">([^<]+)</li>', page)
        self.assertEqual(found, sorted(out),
                         "thirty names in whatever order the service manager "
                         "returned them can only be read from the top")

    def test_the_heading_states_both_numbers(self):
        page = self.page(findings=self.units(), machine_units=(self.MINE,))
        self.assertIn("On the machine, undeclared (1 named, 1 counted)", page,
                      "one total over a shorter list is read as the length of "
                      "that list, which is the mismatch the section headings "
                      "inside the table had")


class AFramedNeighbourIsShownAndNotAdopted(ViewBase):
    """A frame shows the neighbour's own page. It parses nothing out of it and
    repeats no figure of it, which is the line this skill actually holds."""

    def test_a_configured_panel_is_framed_with_its_label(self):
        page = self.page(panels=(("Operations", "../betrieb/"),))
        self.assertIn('<h2>Operations</h2>', page, "the panel lost its label")
        self.assertRegex(page, r'<iframe src="\.\./betrieb/"[^>]*loading="lazy"',
                         "the neighbour is not framed, or is fetched eagerly")

    def test_the_panel_says_it_measured_nothing(self):
        page = self.page(panels=(("Operations", "../betrieb/"),))
        self.assertIn(view.PANELS_NOTE, page,
                      "a framed page without that sentence reads as vouched "
                      "for by this one")

    def test_a_label_is_data_and_never_markup(self):
        page = self.page(panels=(('<script>x</script>', "../x/"),))
        self.assertNotIn("<script>x</script>", page,
                         "a configured label reached the page as markup")

    def test_no_panel_is_the_normal_case(self):
        self.assertNotIn("<iframe", self.page(),
                         "a page with nothing configured framed something anyway")

    def test_half_an_entry_is_not_framed(self):
        page = self.page(panels=(("Operations", ""), ("", "../x/")))
        self.assertNotIn("<iframe", page,
                         "half an entry was drawn as an empty frame")


class TheShellIsOnePlaceAndNotAStack(ViewBase):
    """A neighbour framed at the FOOT of this page is not a shared surface.

    Measured 2026-08-27, on the published page: two framed pages sat under the
    runs table in boxes seventy percent of the window high, each with its own
    header, its own navigation and its own scrollbar, under headings in another
    voice. The reader's verdict was that everything had been squeezed in. Two
    designs sharing one column read as neither, and the fix is not smaller
    frames: it is that each page gets the whole window under one shared bar.

    Everything here is PROGRESSIVE. The document ships whole, every section on
    it, and the bar is a set of jump links until a script turns it into a
    switch. A shell that hides four fifths of a page before scripting runs has
    not organised it, it has lost it.
    """

    PANELS = (("Services", "../betrieb/dienste.html"),
              ("The day", "../betrieb/kalender.html"))

    def test_a_framed_neighbour_is_a_view_of_its_own(self):
        page = self.page(panels=self.PANELS)
        ids = re.findall(r'<section class="view" id="([^"]+)"', page)
        self.assertEqual(len(ids), 1 + len(self.PANELS),
                         f"the frames are not views of their own: {ids}")
        self.assertEqual(ids[0], view.OVERVIEW_ID,
                         "this run's own material is not the first view")

    def test_every_tab_names_a_view_and_every_view_has_a_tab(self):
        page = self.page(panels=self.PANELS)
        tabs = re.findall(r'<a href="#[^"]*" data-view="([^"]+)"', page)
        views = re.findall(r'<section class="view" id="([^"]+)"', page)
        self.assertEqual(tabs, views,
                         "the bar and the sections disagree about what exists, "
                         "so a tab either opens nothing or a view is unreachable")

    def test_the_first_tab_can_be_named_by_the_caller(self):
        page = self.page(panels=self.PANELS, overview_label="Übersicht")
        self.assertRegex(page, r'data-view="view-overview"[^>]*>Übersicht</a>',
                         "the one label the shell supplies itself cannot be "
                         "chosen, so a German bar carries one English word")

    def test_an_unnamed_first_tab_still_has_a_name(self):
        page = self.page(panels=self.PANELS)
        self.assertIn(f">{view.OVERVIEW_LABEL}</a>", page,
                      "without configuration the first tab lost its name")

    def test_nothing_is_hidden_before_a_script_runs(self):
        page = self.page(panels=self.PANELS)
        for block in re.findall(r'<section class="view"[^>]*>', page):
            self.assertNotIn("hidden", block,
                             f"a view ships hidden, so a reader without "
                             f"scripting loses it entirely: {block}")

    def test_a_page_with_nothing_to_switch_to_grows_no_bar(self):
        self.assertNotIn('<nav class="tabs"', self.page(),
                         "a bar appeared with a single view behind it, which "
                         "can only re-select what is already showing")

    def test_two_labels_that_slugify_alike_stay_two_views(self):
        page = self.page(panels=(("The day", "../a/"), ("the DAY", "../b/")))
        ids = re.findall(r'<section class="view" id="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)),
                         f"two views share an identifier, so one of them is "
                         f"unreachable: {ids}")


class TheDayDrawsNoBeatItDidNotMeasure(ViewBase):
    """A cadence has no o'clock, and until 2026-08-27 it was drawn as one.

    The band was a stripe repeating every fourteen pixels, and the period was
    the same for a run every five minutes and a run every hour: roughly a
    hundred evenly spaced marks across the axis, which a reader counts as
    firings. Ten of those lanes together read as static, and the two marks on
    the page that WERE measured were lost in it.

    The lanes are grouped as well, because twenty-three of them in one flat
    list is read as texture. A group is what a lane IS: an appointment, a beat,
    or a presence.
    """

    def cadences(self):
        # 120s and 900s: seven and a half times apart, so anything drawn per
        # firing cannot come out the same for both.
        return [self.load("voicememo-notify"), self.load("calendar-export")]

    def test_the_drawing_does_not_scale_with_the_cadence(self):
        loaded = self.cadences()
        page = self.page(workloads=loaded)
        drawn = {}
        for w in loaded:
            cell = re.search(r'<td class="day">(.*?)</td>',
                             self.run_block(page, w.id), re.S)
            self.assertIsNotNone(cell, f"{w.id} has no day cell")
            drawn[w.id] = (cell.group(1).count('<span class="band')
                           + cell.group(1).count('<span class="tick'))
        self.assertEqual(len(set(drawn.values())), 1,
                         "the two runs carry a different number of marks, so "
                         f"the picture is drawn per firing: {drawn}")

    def test_a_cadence_band_repeats_nothing(self):
        css = view._CSS
        block = re.search(r"\.band\.cadence\s*\{([^}]*)\}", css)
        self.assertIsNotNone(block, "nothing draws a cadence at all")
        self.assertNotIn("repeating-", block.group(1),
                         "the cadence band repeats a pattern again, which is a "
                         "rhythm this page never measured")

    def test_the_legend_no_longer_promises_a_stripe(self):
        words = dict(view.BANDS)
        self.assertNotIn("striped", words.get("cadence", ""),
                         "the legend still describes the drawing it replaced")

    def sections(self, page):
        """Each section heading with the run blocks that follow it."""
        out = []
        for chunk in page.split('<tbody class="grouphead" data-band="')[1:]:
            band = chunk.split('"', 1)[0]
            body = chunk.split('<tbody class="grouphead"', 1)[0]
            out.append((band, chunk.split("</tbody>", 1)[0], body))
        return out

    def test_every_run_sits_in_the_section_its_own_drawing_says(self):
        page = self.page(workloads=self.cadences()
                         + [self.load("daily-health-report")])
        found = self.sections(page)
        self.assertTrue(found, "the table is not divided into sections at all")
        for band, _head, body in found:
            drawn = set(re.findall(r'<span class="band ([a-z]+)"', body))
            filed = set(re.findall(r'<tbody data-id="[^"]*" [^>]*data-band="([a-z]+)"', body))
            if band == "clock":
                self.assertEqual(drawn, set(),
                                 "a banded run was filed under the o'clock "
                                 f"section: {drawn}")
            else:
                self.assertEqual(drawn, {band},
                                 f"the {band} section holds runs drawn as {drawn}")
            self.assertTrue(filed <= {band} or filed == {"clock"} and band == "clock",
                            f"a row in the {band} section says it is {filed}, so "
                            "the script would take the heading away with the "
                            "wrong rows")

    def test_a_section_count_is_an_element_the_filter_can_correct(self):
        """Measured on the LIVE page, 2026-08-27, and it was wrong there.

        Filtering to three agents left the "up the whole time" section standing
        with three rows under a heading that went on saying eight. Hiding the
        heading when its last row goes is only half the fix; while rows remain,
        the number over them has to be one of them. A literal cannot be
        corrected by a script, so the count is an element, exactly like the
        page total.
        """
        page = self.page(workloads=self.cadences()
                         + [self.load("daily-health-report")])
        for band, head, _body in self.sections(page):
            self.assertRegex(
                head, r'<span class="n" data-total="\d+">\d+</span>',
                f"the {band} heading states its count as a literal, so a "
                "filter cannot correct it and it outlives its own rows")
        self.assertIn("said.textContent", view._JS,
                      "nothing in the script ever corrects a section count")

    def test_a_section_counts_only_the_runs_under_it(self):
        page = self.page(workloads=self.cadences()
                         + [self.load("daily-health-report")])
        for band, head, body in self.sections(page):
            said = re.search(r'data-total="(\d+)"', head)
            self.assertIsNotNone(said, f"the {band} heading states no count")
            self.assertEqual(int(said.group(1)), body.count('<tbody data-id="'),
                             f"the {band} heading counts something other than "
                             "the runs under it")


class TheRunKeepsItsFactsWithoutTenColumns(ViewBase):
    """Four columns at rest, and everything else one click down.

    Ten columns of one token each squeezed the identifier into a quarter of the
    measure and wrapped every purpose over four lines while three columns of
    single words floated in white. What a run IS does not change between
    readings; what it DID does. So the identity moved into a definition list
    under the row, which is also what the panel was asked for: the detail
    arrives where the eye already is instead of being scrolled to.
    """

    TERMS = ("unit", "host", "kind", "runtime", "owner", "sphere", "when")

    def test_the_resting_row_is_four_columns(self):
        html = self.page()
        head = html.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(head.count("<th"), 4, f"the row grew again: {head}")
        self.assertRegex(html, r'<tr class="why"[^>]*><td colspan="4"',
                         "the panel underneath spans a different number of "
                         "columns than the row above it, so it sits crooked")

    def test_every_term_the_row_dropped_is_in_the_panel(self):
        html = self.page()
        terms = set(re.findall(r"<dt>([a-z]+)</dt>", html))
        for term in self.TERMS:
            self.assertIn(term, terms,
                          f"{term} left the row and arrived nowhere, so the "
                          "page simply stopped saying it")

    def test_the_columns_are_hinted_and_never_fixed(self):
        html = self.page()
        self.assertIn("<colgroup>", html,
                      "the columns share the page by content again, which is "
                      "how three short ones took it from the identifier")
        self.assertNotRegex(
            view._CSS, r"\.runs[^{]*\{[^}]*table-layout:\s*fixed",
            "a fixed layout clips a history longer than its column, and "
            "recorded runs would disappear without the page saying so")

    def test_repeated_verdicts_are_counted_and_never_dropped(self):
        """Six findings saying one thing are one line and a count.

        A run with six appointments carries six findings. Stacked, they made
        one row three hundred pixels tall to say a single thing six times;
        dropped, six healthy appointments would read exactly like one. The
        count is the whole difference, and every finding is still listed one by
        one in the reasons underneath.
        """
        w = self.load("twice-daily-report")
        html = self.page(workloads=[w], findings=[
            self.finding(w.id, "in_sync", "info", "the morning one is in sync"),
            self.finding(w.id, "in_sync", "info", "the midday one is in sync"),
        ])
        block = self.run_block(html, w.id)
        self.assertEqual(block.count('<span class="state">'), 1,
                         "the same verdict is printed once per finding, so one "
                         "run takes as many lines as it has appointments")
        self.assertIn("×2", block,
                      "two findings collapsed to one WITHOUT a count, so a run "
                      "answering twice reads exactly like one answering once")

    def test_the_head_is_not_pinned_inside_its_own_scroll_container(self):
        """Measured 2026-08-27 on the rendered page, not reasoned about.

        The head was `position: sticky` so the hour axis would follow a reader
        down the table. It sits inside a container with `overflow-x: auto`,
        which makes that container the scrollport: the head stuck to the TABLE
        and was pinned 3.5rem into it, covering the first section heading. The
        overflow is not the thing to remove — without it a long history pushes
        the whole page sideways — so the axis stays where it is written.
        """
        css = view._CSS
        self.assertRegex(css, r"\.scroll\s*\{[^}]*overflow-x:\s*auto",
                         "the table can push the whole page sideways")
        # EVERY rule that addresses the head, not the first one found. The
        # first version of this test took `re.search` and measured the base
        # styling forty lines above, which can never contain the word it looks
        # for: it was green under the mutation that puts the pin back, and the
        # battery is what said so.
        blocks = re.findall(r"thead th\s*\{([^}]*)\}", css)
        self.assertTrue(blocks, "nothing addresses the table head at all")
        for block in blocks:
            self.assertNotIn("sticky", block,
                             "the head is pinned inside the table's own "
                             "scrollport and covers the first section heading "
                             f"under it: {block!r}")

    def test_a_term_with_nothing_to_say_is_left_out(self):
        # An empty definition is a label pointing at a blank, which reads as a
        # fact that is missing rather than one that does not apply.
        html = self.page()
        self.assertNotRegex(html, r"<dd[^>]*></dd>",
                            "a term is rendered with an empty value")


class TheReasonsAreOneClickAwayNotOneScroll(ViewBase):
    """The reason row is what a reader had to scroll for. It becomes a
    disclosure, and the page still SHIPS it open."""

    def test_the_run_row_controls_its_reason_row(self):
        page = self.page()
        self.assertRegex(page, r'aria-controls="why-calendar-export"',
                         "the run row does not point at its reasons")
        self.assertRegex(page, r'<tr class="why" id="why-calendar-export">',
                         "the reason row has no id to be pointed at")

    def test_the_page_ships_expanded(self):
        # Progressive, not conditional: a reader without scripting must get the
        # long document, not a table whose reasons are all hidden.
        page = self.page()
        self.assertRegex(page, r'<tr class="run"[^>]*aria-expanded="true"',
                         "the page ships collapsed, so no-script readers lose "
                         "every reason on it")
        self.assertNotRegex(page, r'<tr class="why"[^>]*hidden',
                            "the reasons ship hidden and only script brings "
                            "them back")


class TheDayIsTheWidestThingOnThePage(ViewBase):
    """A day drawn 270 pixels wide is a footnote about a day.

    Measured on the live page on 2026-08-27, at the reader's own request: the
    twenty-four hour track was the narrowest usable column on a table whose
    subject it is, while a row of identical dots held a third of the measure.
    That row has a hard floor, one glyph per recorded run and no wrapping, so
    it took its width unconditionally and the day got what was left over.

    Both halves are measured here. Widening the column alone changes nothing
    while the floor under the history is still wider than the space it is
    being given.
    """

    def widths(self, html):
        group = re.search(r"<colgroup>(.*?)</colgroup>", html, re.S)
        self.assertIsNotNone(group, "the columns share the page by content again")
        return [int(w) for w in re.findall(r"width:(\d+)%", group.group(1))]

    def rule(self, selector):
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", view._CSS)
        self.assertIsNotNone(found, f"nothing styles {selector} at all")
        return found.group(1)

    def test_the_day_gets_more_of_the_page_than_any_other_column(self):
        widths = self.widths(self.page())
        self.assertEqual(len(widths), 4, f"four columns were declared as {widths}")
        self.assertEqual(
            widths.index(max(widths)), 1,
            "the day is not the widest column on a page whose subject it is: "
            f"{widths}")

    def test_the_history_is_set_small_enough_to_stop_taking_the_width(self):
        block = self.rule(".strip")
        size = re.search(r"font-size:\s*([0-9.]+)rem", block)
        space = re.search(r"letter-spacing:\s*([0-9.]+)em", block)
        self.assertIsNotNone(size, "the recorded strip states no size of its own")
        self.assertIsNotNone(space, "the recorded strip states no spacing")
        self.assertLess(
            float(size.group(1)), 0.875,
            "the history is set at reading size again, and twenty-four glyphs "
            "of it are a floor wider than the day beside them")
        self.assertLess(float(space.group(1)), 0.08,
                        "the spacing between marks is back to widening the "
                        "floor under the column")

    def test_the_track_is_tall_enough_for_the_marks_it_carries(self):
        height = re.search(r"height:\s*([0-9.]+)rem", self.rule(".track"))
        self.assertIsNotNone(height, "the track states no height")
        self.assertGreaterEqual(
            float(height.group(1)), 1.75,
            "the track is thinner than the marks standing on it, so a diamond "
            "at an o'clock overhangs the day it is supposed to sit in")

    def test_the_hours_at_each_end_stand_on_their_own_ground(self):
        """Twenty-four hours ruled evenly is a comb nobody can count. The ends
        are shaded so midday is found without counting ticks, and the shading
        is the AXIS: it says nothing about any run standing on it."""
        found = re.search(
            r"linear-gradient\(90deg,\s*(var\(--[a-z-]+\))\s*0 25%,"
            r"\s*(var\(--[a-z-]+\))\s*25% 75%,"
            r"\s*(var\(--[a-z-]+\))\s*75% 100%\)",
            self.rule(".track"), re.S)
        self.assertIsNotNone(found, "the day is not shaded by the clock at all")
        ends, middle, other = found.groups()
        # The COLOURS, not the stops. Measured by the battery on 2026-08-27:
        # this case asserted that a gradient with those stops existed, which
        # stays true when both grounds are set to the same token. It read as a
        # check and measured nothing.
        self.assertEqual(ends, other,
                         "the two ends of the day are shaded differently from "
                         "one another, so the axis is not symmetric about noon")
        self.assertNotEqual(
            ends, middle,
            "both grounds are the same colour, so the day is flat again and "
            "midday can only be found by counting ticks from the left")
        self.assertIn(
            "the day: every track is one whole day",
            self.page(),
            "the ground the marks stand on is drawn and never accounted for, "
            "which is decoration a reader can mistake for data")

    def test_the_page_never_names_which_ground_is_darker(self):
        """The dark theme swaps them. A page that names one of the two is
        wrong for half its readers, and it is the kind of wrong nobody
        reports: the sentence still reads perfectly."""
        note = re.search(r'<p class="meta">the day:(.*?)</p>', self.page(), re.S)
        self.assertIsNotNone(note, "the shading is never accounted for at all")
        for word in ("darker", "lighter"):
            self.assertNotIn(
                word, note.group(1),
                f"the note calls one of the two grounds {word}, which the "
                "other theme reverses")

    def test_the_page_is_given_the_measure_the_table_needs(self):
        wrap = self.rule(".wrap")
        self.assertIn("var(--max)", wrap,
                      "the measure is a literal again, so widening the table "
                      "means editing the rule rather than the token")
        declared = re.search(r"--max:\s*([0-9.]+)rem", view._CSS)
        self.assertIsNotNone(declared, "no measure is declared")
        self.assertGreaterEqual(float(declared.group(1)), 84,
                                "the page is back to a measure on which the "
                                "day column cannot be a day")


class TheRulerStaysWithinReachOfItsTracks(ViewBase):
    """One ruler at the top of a table is a reference lost on the first scroll.

    It cannot simply be pinned: the table is its own scroll container, so a
    sticky head sticks to THAT box and ends up three and a half rem inside the
    table, over the first section heading. That was measured and removed on
    2026-08-27. The ruler is drawn per SECTION instead, which needs no
    stickiness to stay in reach and costs one line each.
    """

    def headings(self, page):
        out = []
        for chunk in page.split('<tbody class="grouphead" data-band="')[1:]:
            out.append((chunk.split('"', 1)[0], chunk.split("</tbody>", 1)[0]))
        return out

    def placed(self):
        return [self.load("daily-health-report"), self.load("calendar-export"),
                self.load("chat-channel")]

    def test_every_section_that_draws_a_day_carries_its_own_ruler(self):
        found = self.headings(self.page(workloads=self.placed()))
        self.assertGreaterEqual(len(found), 3,
                                "the table is not divided into sections at all")
        for band, head in found:
            self.assertIn('class="scale"', head,
                          f"the {band} section draws tracks under no ruler")

    def test_the_section_that_places_nothing_carries_no_ruler(self):
        """An hour scale over cells holding a sentence invites the reading that
        they are somewhere on it. They are on the page precisely because they
        are not."""
        page = self.page(workloads=[self.load("daily-health-report"),
                                    self.load("contract-review-reminder")])
        found = dict(self.headings(page))
        self.assertIn("unplaced", found,
                      "the run nothing could place did not get its own section")
        self.assertNotIn('class="scale"', found["unplaced"],
                         "a ruler is drawn over the runs that are not on the "
                         "day at all")

    def test_the_ruler_is_not_written_once_and_left_at_the_top(self):
        page = self.page(workloads=self.placed())
        head = page.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertNotIn('class="scale"', head,
                         "the ruler is back at the top of the table only, "
                         "where the first scroll takes it away")
        self.assertGreaterEqual(
            page.count('class="scale"'), 3,
            "there are fewer rulers than sections drawing a day")

    def test_the_ruler_and_the_track_are_ruled_the_same(self):
        """Two instruments on different scales are worse than one: a reader
        lines a mark up against ticks that do not belong to it."""
        scale = re.search(r"\.dayhead \.scale::after\s*\{([^}]*)\}", view._CSS)
        track = re.search(r"\.track\s*\{([^}]*)\}", view._CSS, re.S)
        self.assertIsNotNone(scale, "the ruler carries no ticks")
        self.assertIn("12.5%", scale.group(1),
                      "the ruler is not ticked every three hours")
        self.assertIn("12.5%", track.group(1),
                      "the track is not ruled every three hours")


class NowComesFromTheMachinesZoneAndNeverTheReaders(ViewBase):
    """The upright line, and the one way it could quietly be wrong.

    The axis is the MACHINE's day. A line taken from the reader's own offset
    is right in one office and hours out in the next, and looks identical in
    both. So the hour is computed in the zone the declarations state, and where
    they state more than one the page draws no line and says why.

    It is script-only on purpose, exactly like the age in the header: it is a
    fact only a running clock knows, and a server-rendered one would be frozen
    at the moment the page was written while looking live.
    """

    def berlin(self):
        return [self.load("daily-health-report"), self.load("calendar-export")]

    def test_a_page_whose_declarations_agree_states_the_zone(self):
        page = self.page(workloads=self.berlin())
        self.assertIn('data-zone="Europe/Berlin"', page,
                      "the page names no zone, so the script has nothing to "
                      "compute the hour in and draws nothing")

    def test_a_page_whose_declarations_disagree_states_no_zone(self):
        page = self.page(workloads=self.berlin()
                         + [self.load("foreign-timezone-report")])
        self.assertNotRegex(page, r"data-zone=",
                            "one line was drawn across runs keeping two "
                            "different zones, so it is the right moment for at "
                            "most one of them")
        self.assertIn("no line marks now", page,
                      "the line is missing and nothing on the page says why, "
                      "which reads as a page that simply forgot")
        self.assertIn("Pacific/Auckland", page,
                      "the page does not name the zones it found disagreeing")

    def test_a_page_with_no_zone_at_all_says_that_instead(self):
        page = self.page(workloads=[self.load("chat-channel")])
        self.assertNotRegex(page, r"data-zone=")
        self.assertIn("no declaration here states a time zone", page,
                      "a page whose runs name no zone is silent about why it "
                      "has no line")

    def test_the_line_is_never_in_the_document_the_server_wrote(self):
        body = self.page(workloads=self.berlin()).split("<body>", 1)[1]
        self.assertNotIn('class="nowline"', body.split("<script>", 1)[0],
                         "a now line was rendered by the server, so it is "
                         "frozen at the moment the page was written and looks "
                         "exactly like a live one")

    def test_the_sentence_about_now_waits_for_a_clock(self):
        page = self.page(workloads=self.berlin())
        note = re.search(r'<p class="meta" id="nownote"([^>]*)>', page)
        self.assertIsNotNone(note, "the line is drawn and never accounted for")
        self.assertIn("hidden", note.group(1),
                      "the page explains a line it may never draw, so a reader "
                      "without scripting is told to look for one that is not "
                      "there")

    def test_the_axis_arithmetic_places_a_wall_clock_reading(self):
        answers = self.js(["nowPct('00:00')", "nowPct('06:00')",
                           "nowPct('12:00')", "nowPct('23:59')"])
        self.assertEqual(answers[0], 0)
        self.assertEqual(answers[1], 25)
        self.assertEqual(answers[2], 50)
        self.assertGreater(answers[3], 99.9)

    def test_the_axis_arithmetic_refuses_what_it_cannot_read(self):
        """A line at a guessed hour is worse than none: it is indistinguishable
        from a measured one."""
        answers = self.js(["nowPct('')", "nowPct('half past six')",
                           "nowPct('25:00')", "nowPct('12:99')",
                           "nowPct(null)"])
        for got in answers:
            self.assertIsNone(got, f"an unreadable clock was placed at {got}")

    def test_the_hour_is_the_machines_and_not_the_readers(self):
        """One instant, two zones, two placements. If this ever returns the
        same answer twice, the line is being taken from whoever is looking."""
        answers = self.js([
            "clockIn('Europe/Berlin', new Date('2026-08-27T12:00:00Z'))",
            "clockIn('Pacific/Auckland', new Date('2026-08-27T12:00:00Z'))",
            "clockIn('Not/AZone', new Date('2026-08-27T12:00:00Z'))",
        ])
        self.assertEqual(answers[0], "14:00")
        self.assertEqual(answers[1], "00:00")
        self.assertNotEqual(answers[0], answers[1],
                            "the same instant placed identically in two zones, "
                            "so the zone is being ignored")
        self.assertEqual(answers[2], "",
                         "an unknown zone produced an hour anyway, which puts "
                         "the line somewhere nobody measured")


class TheCalendarSectionReadsInClockOrder(ViewBase):
    """Alphabetical order made the one section that IS a calendar unreadable
    as one: a 00:30 job sat below a 06:10 one, so the marks scattered down the
    column instead of walking across it. Measured on the live page on
    2026-08-27, where seven appointments were sorted by name.

    Each case asserts its own premise first, because the moment a fixture's
    name changes so that the two orders coincide, the test stops measuring
    anything and stays green.
    """

    def ids(self, page, band):
        return [m.group(1) for m in
                re.finditer(r'<tbody data-id="([^"]+)"[^>]*data-band="([^"]+)"',
                            page)
                if m.group(2) == band]

    def test_an_appointment_section_is_ordered_by_the_hour_it_fires(self):
        # 00:30, 06:10, 23:50, and alphabetically the exact reverse.
        names = ["early-daily-report", "daily-health-report", "midnight-report"]
        self.assertNotEqual(names, sorted(names),
                            "premise: these names no longer discriminate a "
                            "clock order from an alphabetical one")
        page = self.page(workloads=[self.load(n) for n in sorted(names)])
        self.assertEqual(self.ids(page, "clock"), names,
                         "the appointments are not in the order they fire")

    def test_a_beat_is_ordered_by_its_period_and_not_by_its_name(self):
        # 300s, 600s, 900s, 3600s.
        names = ["process-isolation-report", "ambiguous-check-report",
                 "calendar-export", "umlaut-report"]
        self.assertNotEqual(names, sorted(names), "premise: no discrimination")
        page = self.page(workloads=[self.load(n) for n in sorted(names)])
        self.assertEqual(self.ids(page, "cadence"), names,
                         "the cadences are not in the order of their periods, "
                         "so every 3600s can stand above every 300s")

    def test_the_key_sorts_by_number_and_never_by_the_name(self):
        """Directly, because on some sets of names the two orders coincide and
        a page level case then proves nothing."""
        slow = view.Lane(workload_id="a-first", purpose="", order=3600.0)
        fast = view.Lane(workload_id="z-last", purpose="", order=900.0)
        self.assertLess(view._order_key(fast, fast.workload_id),
                        view._order_key(slow, slow.workload_id),
                        "the slower run sorts first, so the key is reading the "
                        "name and not the period")

    def test_a_run_with_no_order_of_its_own_keeps_a_stable_place(self):
        names = ["watched-daemon", "chat-channel", "long-running-poller"]
        page = self.page(workloads=[self.load(n) for n in names])
        self.assertEqual(self.ids(page, "continuous"), sorted(names),
                         "runs with no order of their own are in no order at "
                         "all, so two renders can disagree about the page")


class AScheduleOfSixTimesIsAListAndNotSixAnds(ViewBase):
    """Measured on the live page: "06:00 and 09:00 and 12:00 and 15:00 and
    18:00 and 21:00". The eye leaves after the third."""

    def test_two_times_keep_the_ordinary_word(self):
        page = self.page(workloads=[self.load("twice-daily-report")])
        self.assertIn("06:30 and 12:30", page,
                      "the common case lost the word that reads best in it")

    def test_more_than_two_become_a_list(self):
        self.assertEqual(view._and_list(["a", "b", "c", "d"]), "a, b, c and d")
        self.assertEqual(view._and_list(["a", "b"]), "a and b")
        self.assertEqual(view._and_list(["a"]), "a")
        self.assertEqual(view._and_list([]), "")


class ARefusalCostsItsOwnRunASentenceAndNotThePage(ViewBase):
    """Found by rendering the whole fixture corpus at once on 2026-08-27.

    Two functions can refuse to place a run, and only the first was guarded: a
    recurrence `starts_of` accepts can still be one `weekdays_of` cannot
    express in days. That refusal escaped the renderer as an exception, so ONE
    such declaration took the whole page down instead of costing itself a
    sentence, which is the opposite of what the guard is for.
    """

    def test_a_recurrence_no_backend_can_express_still_renders(self):
        exotic = self.load("exotic-recurrence-watched")
        page = self.page(workloads=[self.load("daily-health-report"), exotic])
        self.assertIn(exotic.id, page,
                      "the run that could not be placed is simply not on the "
                      "page, so it was lost rather than explained")
        self.assertIn("cannot be placed on the axis", page,
                      "the run is on the page with an empty day, which reads "
                      "as a run that fires at no time")

    def test_the_rest_of_the_page_survives_it(self):
        page = self.page(workloads=[self.load("daily-health-report"),
                                    self.load("exotic-recurrence-watched")])
        self.assertIn("daily-health-report", page,
                      "one unplaceable declaration took the other runs with it")


class TheDayShowsWhereItHasGotTo(ViewBase):
    """A track that looks the same at 03:00 and at 23:00 is a plan, not a day.

    Taken from the neighbouring operations page on 2026-08-27: left of now is
    what happened, right of it is what is still to come, and the two are drawn
    differently. Same provenance as the upright line, so the same rule applies:
    only a running clock knows it, so only a running clock may draw it.
    """

    def rule(self, selector):
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", view._CSS)
        self.assertIsNotNone(found, f"nothing styles {selector}")
        return found.group(1)

    def test_nothing_is_shaded_before_a_clock_has_run(self):
        block = self.rule(".track::after")
        self.assertIn(
            "var(--now, 100%)", block,
            "the fallback no longer parks the shading off the right edge, so a "
            "page without scripting asserts where the day has got to using a "
            "moment nobody took")

    def test_the_shading_is_one_property_for_every_track(self):
        """Twenty-five elements updated on a timer is twenty-five chances for
        half of them to be at one moment and half at another."""
        self.assertIn("setProperty('--now'", view._JS,
                      "nothing ever sets the property the tracks read")

    def test_the_ground_it_draws_is_accounted_for(self):
        page = self.page(workloads=[self.load("daily-health-report")])
        note = re.search(r'id="nownote"[^>]*>(.*?)</p>', page, re.S)
        self.assertIsNotNone(note, "the line and the shading are never explained")
        self.assertIn("has not happened yet", note.group(1),
                      "the shading is drawn and only the line is accounted "
                      "for, so half the drawing is unexplained")


class AStampBecomesADistance(ViewBase):
    """"How long ago" is the question a reader opens an operations page with.

    The diamond carries the exact moment and the strip carries the history, and
    neither answers it: a reader had to compare an hour by hand against their
    own clock. The absolute stamp is what SHIPS, so nothing is lost without
    scripting; the clock turns it into a distance.
    """

    def with_a_run(self):
        w = self.load("daily-health-report")
        rep = report_mod.Report(findings=[], header="",
                                runs={w.id: ("2026-08-23T04:10:00Z", 0)})
        return view.render(rep, [w], generated_at=STAMP), w

    def test_the_absolute_stamp_is_what_ships(self):
        page, w = self.with_a_run()
        block = self.run_block(page, w.id)
        self.assertRegex(
            block,
            r'<time class="since" datetime="2026-08-23T04:10:00Z">'
            r"2026-08-23T04:10:00Z</time>",
            "the moment is in an attribute only, so a reader without a clock "
            "gets an empty line where the answer should be")

    def test_a_run_with_no_trace_gets_no_age_line(self):
        page = self.page(workloads=[self.load("daily-health-report")])
        self.assertNotIn('class="ago"', self.run_block(page, "daily-health-report"),
                         "a run that has never been recorded carries a line "
                         "about how long ago it was recorded")

    def test_the_page_holds_one_arithmetic_for_every_age(self):
        """The header's age and a track's age on one page, computed twice, will
        disagree the day one of them is fixed."""
        self.assertEqual(view._JS.count("function ageText"), 1,
                         "there is more than one way of saying how old "
                         "something is on this page")


class ThePageOpensWithWhatNeedsAPerson(ViewBase):
    """The page opened with four counts and a table, which is an inventory.

    A reader had to work out "is anything wrong here" by eye across
    twenty-five rows. The material for the answer was already on the page and
    being thrown away: every finding carries a HINT, this skill's own sentence
    about what to do next, and no renderer had ever put one on a page.
    """

    def loud(self):
        w = self.load("calendar-export")
        f = report_mod.Finding(
            workload_id=w.id, state="overdue", severity="high",
            detail="it was due at 09:00 and its newest line is from 06:00",
            hint="read the unit's log, then bootout and bootstrap it",
            source="machine")
        return view.render(report_mod.Report(findings=[f], header=""), [w],
                           generated_at=STAMP), w

    def test_the_answer_stands_above_the_table_as_a_count(self):
        # The page still opens with the ANSWER to "does anything here need me".
        # It is a count and a way to the rows, not a second copy of them: until
        # 2026-09-04 every finding was written out here AND again in its own
        # row's dossier, which is two accounts of one fact.
        page, _ = self.loud()
        head = page.split('<section class="block">', 1)[0]
        self.assertIn('id="attention"', head,
                      "the answer is missing or below the table it is about")
        self.assertRegex(head, r"1 finding on 1 run needs a person",
                         "the opening line does not say how much needs a person")

    def test_the_skills_own_instruction_reaches_the_runs_own_row(self):
        # The hint used to live ONLY in the block above the table. Removing the
        # block without moving it would have thrown away the one sentence this
        # skill writes about what to do next, and left the finding standing.
        page, w = self.loud()
        self.assertIn("bootout and bootstrap it", self.run_block(page, w.id),
                      "the hint is computed for every finding and does not "
                      "reach the row the finding belongs to")

    def test_the_shortcut_names_a_pill_the_bar_actually_carries(self):
        # A control that cannot act must not be on the page. The shortcut works
        # by PRESSING the facet pill, so a pill that was never drawn (a facet
        # is drawn only from two values up) leaves a button that does nothing.
        w = self.load("calendar-export")
        quiet = self.load("daily-health-report")
        f = report_mod.Finding(workload_id=w.id, state="overdue", severity="high",
                               detail="d", hint="h", source="machine")
        page = view.render(report_mod.Report(findings=[f], header=""),
                           [w, quiet], generated_at=STAMP)
        shortcut = re.search(r'id="attention".*?data-facet="([^"]+)"'
                             r'\s+data-value="([^"]+)"', page, re.S)
        self.assertIsNotNone(shortcut, "the opening line offers no way to the rows")
        facet, value = shortcut.groups()
        self.assertRegex(
            page, r'<button type="button" data-facet="%s" data-value="%s"'
                  % (re.escape(facet), re.escape(value)),
            "the shortcut names a facet value the filter bar never drew, so "
            "pressing it does nothing at all")

    def test_no_shortcut_where_there_would_be_no_pill(self):
        # Every run needs a person: `attention` then has ONE value, the bar
        # draws no pill for it, and a shortcut would be furniture.
        w = self.load("calendar-export")
        f = report_mod.Finding(workload_id=w.id, state="overdue", severity="high",
                               detail="d", hint="h", source="machine")
        page = view.render(report_mod.Report(findings=[f], header=""), [w],
                           generated_at=STAMP)
        self.assertIn('id="attention"', page, "the answer itself is missing")
        self.assertNotIn('class="pick"', page,
                         "a button is offered for a filter the bar cannot show")

    def test_information_alone_is_a_sentence_and_not_an_empty_box(self):
        page = self.page(findings=[self.finding("calendar-export", "in_sync",
                                                "info", "matches")])
        self.assertNotIn('class="open"', page,
                         "an empty box teaches a reader to skip the one place "
                         "that will one day not be empty")
        self.assertIn("Nothing here needs a person", page)
        self.assertIn("never a promise about what was not", page,
                      "the all clear reads as a promise about the whole "
                      "machine rather than about what was measured")

    def test_a_finding_is_stated_once_and_not_twice(self):
        # The case that replaced "the summary must agree with the row". Two
        # accounts of one fact cannot disagree if there is only one, and the
        # old shape wrote every detail and every hint out a second time above
        # the table. Measured on the live page: twenty-five entries over a
        # table carrying the same twenty-five.
        page, w = self.loud()
        detail = "it was due at 09:00 and its newest line is from 06:00"
        self.assertEqual(page.count(detail), 1,
                         "the finding's sentence is on the page more than once")
        # Ohne den Apostroph gemessen: `_esc` schreibt ihn als Entity, und ein
        # Vergleich gegen den Rohtext zaehlt dann null und meldet Erfolg aus dem
        # falschen Grund.
        self.assertEqual(page.count("then bootout and bootstrap it"), 1,
                         "the hint is on the page more than once")
        self.assertIn(detail, self.run_block(page, w.id),
                      "the one place it is stated is not the run's own row")


class AReaderCanLookForAWordThePillsDoNotHave(ViewBase):
    """A facet can only offer the words this skill files a run under.

    The word somebody actually remembers is usually in the purpose, and until
    2026-08-27 there was no way to look for it. Measured on the live page: a
    search for `wissensagent` finds three runs, none of which carries the word
    in its name.
    """

    def test_every_run_carries_what_a_reader_would_type(self):
        page = self.page()
        block = self.run_block(page, "calendar-export")
        found = re.search(r'data-search="([^"]*)"', block)
        self.assertIsNotNone(found, "the row carries nothing to search")
        haystack = found.group(1)
        self.assertIn("calendar-export", haystack)
        for word in ("interval", "host-a", "launchd"):
            self.assertIn(word, haystack,
                          f"{word} is on the row and cannot be searched for")
        self.assertEqual(haystack, haystack.lower(),
                         "the haystack carries case, so a search has to guess "
                         "how the declaration was written")

    def test_the_bar_survives_a_page_where_no_facet_discriminates(self):
        """One run means every pill offers the single answer it gives, so the
        pills are furniture. The search is the only control that still works,
        and it used to disappear with them."""
        page = self.page(workloads=[self.load("calendar-export")])
        self.assertIn('id="q"', page,
                      "a page with one run has no way to search it at all")
        self.assertNotIn('data-facet="kind"', page,
                         "a facet offering one value came back as furniture")

    def test_two_words_narrow_and_never_widen(self):
        answers = self.js([
            "searchMatch('telegram morning digest', 'telegram')",
            "searchMatch('telegram morning digest', 'telegram digest')",
            "searchMatch('telegram morning digest', 'telegram wiki')",
        ])
        self.assertEqual(answers, [True, True, False],
                         "a second word ADDS rows, which reads as a filter "
                         "that stopped working")

    def test_an_empty_query_is_not_a_filter(self):
        answers = self.js(["searchMatch('anything', '')",
                           "searchMatch('anything', '   ')",
                           "searchMatch('anything', null)"])
        for got in answers:
            self.assertTrue(got, "an empty search hid every row on the page")


class TheTableSortsWithoutLosingItsSections(ViewBase):
    """Sorting answers "which is worst"; the sections answer "what is this".

    A sort that dissolved the sections would answer neither, so it happens
    WITHIN each one. A third click restores the order the page was built in,
    because a table with no way back to its own default is one a reader leaves
    sorted wrong.
    """

    def test_every_column_offers_a_sort(self):
        head = self.page().split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(head.count("data-sort="), 4,
                         f"not every column can be sorted by: {head}")

    def test_the_keys_are_rendered_and_never_derived_in_the_script(self):
        """Which of two verdicts is worse is a decision of the renderer. A
        second copy of it in JavaScript drifts from this one the day a severity
        is added, and drifts silently: both orders look plausible."""
        block = self.run_block(self.page(), "calendar-export")
        for key in ("data-sort-id", "data-sort-when", "data-sort-recorded",
                    "data-sort-state"):
            self.assertIn(key, block, f"the row carries no {key}")
        self.assertIn("data-sort-", view._JS,
                      "the script sorts by something other than the keys the "
                      "renderer wrote")

    def test_the_rows_are_moved_along_a_cursor_and_not_a_fixed_anchor(self):
        """A SOURCE assertion, and it is one deliberately: the defect lives in
        DOM insertion, which this suite has no DOM to run.

        Measured in a live browser on 2026-08-27. `section.head.nextSibling`
        taken once is itself one of the rows about to be moved; from the moment
        it moves, every later insertion happens relative to wherever it landed.
        Three clicks on one column returned six of seven rows correctly and put
        the seventh last, which reads as a sort nobody asked for.
        """
        self.assertIn("at = row;", view._JS,
                      "the cursor is gone, so the rows are being placed "
                      "against an anchor that moves with them")
        self.assertNotIn("var anchor = section.head.nextSibling", view._JS,
                         "the fixed anchor is back")

    def test_one_list_is_called_heads_and_only_one(self):
        """Measured in a live browser on 2026-08-27, twenty minutes after it
        was written. A second `var heads` in the same function silently rebound
        the first: the filter then iterated the table's four column headers,
        hid all four on every filter, and stopped correcting the section
        counts, which is exactly the defect those counts were made elements to
        prevent. Both lists still looked entirely reasonable in the diff.
        """
        self.assertEqual(
            len(re.findall(r"\bvar heads\b", view._JS)), 1,
            "two lists in one scope answer to the same name, and the second "
            "one wins wherever the first is read")


class ADecisionIsNotAChore(ViewBase):
    """A decided absence gets its own heading, never the drift one.

    The drift section says these entries "have drifted away from both", and the
    advice under each row is to delete the entry. On the live page on
    2026-08-27 nine of its sixteen rows were decisions somebody had written
    down, with a date and a reason: a security bar, two backups parked on a
    failing disk, a transport replaced in June. Filing a decision under drift
    tells a reader there is work here, and the work it names is deleting the
    record of the decision.
    """

    def absent(self, slug="share-tunnel"):
        return self.finding(
            slug, "intentionally_absent", "info",
            f"the inventory of host-a lists {slug!r} and nothing runs it, "
            "which is on purpose since 2026-08-14: fully dismantled on request",
            hint="nothing to do: this entry records a decision rather than a gap")

    def test_the_heading_above_it_is_its_own(self):
        """Measured against the NEAREST heading, not against one absent word.

        Asserting only that the drift wording is missing passes while the row
        sits under "On the machine, undeclared", which is a second wrong place:
        an entry that exists only in a file is not something the machine
        carries. The heading a reader sees above the row is the property.
        """
        page = self.page(findings=[self.absent()])
        before = page.split("share-tunnel")[0]
        self.assertIn("Absent on purpose", before.split("<h2>")[-1],
                      "the row sits under somebody else's heading")

    def test_its_date_and_its_reason_are_both_on_the_page(self):
        page = self.page(findings=[self.absent()])
        self.assertIn("2026-08-14", page)
        self.assertIn("fully dismantled on request", page)

    def test_the_two_sections_stand_apart_when_both_have_rows(self):
        page = self.page(findings=[
            self.absent(),
            self.finding("voice-news", "inventory_stale", "info",
                         "the inventory lists it, neither a declaration nor the "
                         "machine knows it")])
        self.assertIn("voice-news", page)
        self.assertIn("share-tunnel", page)
        heads = [page.index("<h2>" + h) for h in
                 ("Inventory entries", "Absent on purpose")]
        self.assertEqual(len(set(heads)), 2, "the two headings collapsed into one")

    def test_a_decided_absence_alone_still_gets_its_section(self):
        page = self.page(findings=[self.absent()])
        self.assertIn("Absent on purpose (1)", page)
        self.assertNotIn("Inventory entries that name nothing", page)

    def test_it_never_reaches_what_needs_a_person(self):
        page = self.page(findings=[self.absent()])
        self.assertIn("Nothing here needs a person", page)


class TheFirstQuestionAfterACrossIsWhere(ViewBase):
    """A row said `failed` and did not say where to read about it.

    The guard captures every run's stdout and stderr into `<state_key>.out`
    beside the trace this page already draws, so the path was derivable from
    two things the page had and was never derived. The reader was left with a
    convention to remember.

    Named, never opened. The page states a path; whether a file is there, and
    what is in it, is a question for a terminal, and claiming either would be
    the kind of unmeasured sentence this whole surface is built to avoid.
    """

    DIR = "~/.bridge/workloads"

    def test_a_row_names_the_file_its_run_writes_into(self):
        page = self.page(state_dir=self.DIR)
        self.assertIn(f"{self.DIR}/calendar-export.out", page)

    def test_a_run_with_two_appointments_names_one_file_per_appointment(self):
        """The same trap the trace fell into: neither file is called `<id>.out`.

        A run with two appointments writes one capture per appointment, named
        after the state key. Printing the bare id would name a path that does
        not exist for exactly the runs whose logs are hardest to find.
        """
        page = self.page(workloads=[self.load("twice-daily-report")],
                         state_dir=self.DIR)
        self.assertNotIn(f"{self.DIR}/twice-daily-report.out", page)
        self.assertIn("twice-daily-report.morning.out", page)
        self.assertIn("twice-daily-report.midday.out", page)

    def test_without_a_configured_directory_nothing_is_printed(self):
        """A path this page invented would read exactly like one it was given."""
        self.assertNotIn(".out", self.page())

    def test_the_page_says_it_did_not_open_them(self):
        page = self.page(state_dir=self.DIR)
        self.assertRegex(page, r"(?s)log.{0,400}?(did not open|never opened)")


class ANameWithoutAVerbIsNotAnAnswer(ViewBase):
    """The undeclared section listed names and named nothing to do with them.

    What it says is true and complete about the past: this run found them,
    touched none of them, and holds no deadline, owner or guard for any. A
    reader arrives at that list with one question, and this skill has an answer
    with a verb of its own, so withholding it is not restraint.

    Said ONCE, in the lede. Every one of those names differs in nothing this
    run measured, so a sentence per row would be one template repeated thirty
    times, which is how a section meant as context grows longer than the
    subject of the page.
    """

    def named(self, count=3):
        return [self.finding(f"com.example.thing{i}", "unmanaged", "info",
                             "on the machine, claimed by no declaration")
                for i in range(count)]

    def page_with_names(self, count=3):
        return self.page(findings=self.named(count),
                         machine_units=("com.example.",))

    def test_the_section_names_the_verb_that_answers_it(self):
        self.assertIn("adopt", self.page_with_names(),
                      "the page lists what nobody declared and never says how "
                      "one of them becomes a declaration")

    def test_it_is_said_once_and_never_per_name(self):
        page = self.page_with_names(12)
        self.assertIn("com.example.thing11", page,
                      "the fixture stopped listing them")
        self.assertLessEqual(
            page.count("adopt"), 2,
            "one sentence per row is a template repeated twelve times")

    def test_it_still_says_this_run_touched_none_of_them(self):
        """The offer must not quietly become a claim of ownership."""
        self.assertIn("never touches any of them", self.page_with_names())


class WhereTheProgramItRunsIsKept(ViewBase):
    """`in_sync` is about the unit and the artifact, and the program is neither.

    A wrapper outside the repository that has come apart from its twin runs
    forever while a change in the repository never reaches it, with no error
    anywhere. The page carried the unit, the host, the schedule and the log,
    and never the one file the run actually executes.

    Both facts come from the report: comparing needs a digest from the machine
    and a file from the repository, and a renderer has neither.
    """

    def page_with(self, programs):
        rep = report_mod.Report(findings=[], header="", programs=programs)
        return view.render(rep, [self.load("calendar-export")], generated_at=STAMP)

    def test_the_row_names_the_program_and_where_it_sits(self):
        page = self.page_with({"calendar-export": ("/opt/elsewhere/run.sh",
                                                   "a copy of scripts/run.sh, "
                                                   "and they have come apart")})
        self.assertIn("/opt/elsewhere/run.sh", page)
        self.assertIn("come apart", page)

    def test_the_healthy_answer_is_printed_too(self):
        """A line only for the exception reads as a page with nothing to say
        about everything else."""
        page = self.page_with({"calendar-export": ("/repo/scripts/run.sh",
                                                   "in this repository")})
        self.assertIn("in this repository", page)

    def test_a_run_nobody_asked_about_gets_no_line(self):
        self.assertNotIn(">program<", self.page_with({}))


class AWeeklyRunIsNotDueEveryDay(ViewBase):
    """The weekday was in the text cell and not in the picture.

    Measured on the live page on a Thursday: a run that fires on Sundays drew a
    ring at 10:00 whose hover read "nothing says this schedule is behind",
    identical to a run that really was due that morning. The row's own text
    said "10:00 Sun", so the page was not silent; the DRAWING asserted an
    appointment today, and the drawing is why the axis exists.

    The verdict logic never had this wrong: `previous_due` reads the same
    weekday set. The judgement knew and the picture did not, which is the
    narrower and worse version of the same fault.
    """

    #: A Sunday. The fixture fires Monday to Saturday, so every appointment it
    #: has falls somewhere other than the day this page is drawn for.
    SUNDAY = "2026-08-23T16:30:00+02:00"
    MONDAY = "2026-08-24T16:30:00+02:00"

    def page_on(self, when):
        return view.render(report_mod.Report(findings=[], header=""),
                           [self.load("twice-daily-report")], generated_at=when)

    def marks(self, when):
        page = self.page_on(when)
        return re.findall(r'class="tick ([a-z-]+)"[^>]*title="([^"]*)"', page)

    def test_an_appointment_on_another_day_is_drawn_apart(self):
        shapes = {shape for shape, _ in self.marks(self.SUNDAY)}
        self.assertIn("elsewhen", shapes,
                      "a Monday-to-Saturday run drew its ordinary marks on a "
                      "Sunday, which is the page asserting an appointment "
                      "nobody declared for that day")

    def test_and_it_says_which_days_it_does_fire_on(self):
        said = " ".join(note for _, note in self.marks(self.SUNDAY))
        self.assertIn("not on this day", said)
        self.assertIn("Mon", said, "the reader is left to look the days up")

    def test_on_its_own_day_it_is_an_ordinary_mark(self):
        shapes = {shape for shape, _ in self.marks(self.MONDAY)}
        self.assertNotIn("elsewhen", shapes)

    def test_it_is_drawn_and_never_dropped(self):
        """An empty lane reads as a run with nothing scheduled, which is the
        other wrong answer and the harder one to notice."""
        self.assertTrue(self.marks(self.SUNDAY))

    def test_the_legend_explains_the_faint_mark(self):
        self.assertIn("does not fall on the day drawn", self.page_on(self.SUNDAY))

    def test_a_legend_never_explains_a_mark_that_is_not_there(self):
        self.assertNotIn("does not fall on the day drawn", self.page_on(self.MONDAY))


class TheWeekAndTheMonthAreScalesOfTheirOwn(ViewBase):
    """A day answers "when today"; a week answers "which days".

    A weekly run on a 24 hour axis is a ring at an hour with its day in a text
    cell beside the picture. On a week it is the picture. Both scales ship
    rendered rather than built on click: what a page shows has to be what the
    run measured, and a reader with no scripting keeps the day.
    """

    SUNDAY = "2026-08-23T16:30:00+02:00"

    def page(self, when=SUNDAY, workloads=None, history=None):
        rep = report_mod.Report(findings=[], header="", history=dict(history or {}))
        return view.render(rep, workloads or [self.load("twice-daily-report")],
                           generated_at=when)

    def cells(self, page, scale):
        # The closing quote right after the name is load-bearing: the ruler is
        # `class="grid week ruler"`, and a looser pattern would measure it
        # instead of the row, which carries the same number of cells and none
        # of the marks.
        block = re.search(r'<div class="grid %s"[^>]*>(.*?)</div>' % scale, page, re.S)
        return re.findall(r'class="cell([^"]*)"[^>]*title="([^"]*)"',
                          block.group(1)) if block else []

    def test_the_week_is_seven_days(self):
        self.assertEqual(len(self.cells(self.page(), "week")), 7)

    def test_and_it_marks_only_the_days_the_run_fires_on(self):
        cells = self.cells(self.page(), "week")
        due = [i for i, (classes, _) in enumerate(cells) if "due" in classes]
        self.assertEqual(due, [0, 1, 2, 3, 4, 5],
                         "the fixture fires Monday to Saturday, and Sunday is "
                         "the seventh column")

    def test_the_month_is_one_cell_per_day_of_the_month_drawn(self):
        self.assertEqual(len(self.cells(self.page(), "month")), 31,
                         "August has thirty-one days")

    def test_what_actually_ran_is_a_second_mark_from_a_second_source(self):
        """`due` comes from the declaration and `ran` from the machine.

        Merged into one they would make a day that was never scheduled and a
        day that was scheduled and missed look the same.
        """
        page = self.page(history={"twice-daily-report": (
            ("2026-08-21T04:30:00Z", 0, "ok", "twice-daily-report.morning"),)})
        cells = self.cells(page, "week")
        self.assertIn("ran", cells[4][0], "Friday the 21st carried a run")
        self.assertNotIn("ran", cells[3][0])

    def test_all_three_ship_and_one_is_shown(self):
        """Measured on a ROW, not on the section heading.

        The heading carries its own three rulers, so counting `data-scale`
        across the page passed on a page whose rows had no week and no month at
        all: the rulers alone kept the numbers equal. Found by the battery.
        """
        page = self.page()
        cell = re.search(r'<td class="day">(.*?)</td>', page, re.S).group(1)
        self.assertIn('data-scale="day"', cell)
        self.assertIn('class="grid week"', cell)
        self.assertIn('class="grid month"', cell)
        self.assertIn('data-scale="week" hidden', cell)
        self.assertNotIn('data-scale="day" hidden', cell)

    def test_each_scale_brings_its_own_ruler(self):
        page = self.page()
        self.assertIn("Mon", page)
        self.assertIn('class="grid month ruler"', page)

    def test_a_run_with_no_weekday_constraint_is_due_on_all_seven(self):
        """`weekdays_of` answers with an EMPTY tuple for a daily run.

        Read as "no days" instead of "every day" it would empty the week and
        the month of every daily job on the page, which is most of them, and
        the two scales would look like a machine that had stopped.
        """
        page = self.page(workloads=[self.load("early-daily-report")])
        cells = self.cells(page, "week")
        self.assertEqual(len(cells), 7)
        self.assertTrue(all("due" in classes for classes, _ in cells))

    def test_the_month_ruler_and_its_cells_are_told_the_same_grid(self):
        """Two grids stacked under one another line up only if both are told
        how many columns they have.

        Left to `auto-fit` the ruler sized its columns to the digits in them
        and the cells, which carry no text, to nothing: the scale then pointed
        at the wrong days, and it looked entirely ordinary while doing it.
        """
        page = self.page()
        self.assertRegex(
            page, r'class="grid month ruler" '
                  r'style="grid-template-columns: repeat\(31, 1fr\)"')
        self.assertRegex(
            page, r'class="grid month" '
                  r'style="grid-template-columns: repeat\(31, 1fr\)"')

    def test_without_a_moment_nothing_is_placed_in_a_week(self):
        """A guessed date would put marks on days nobody measured."""
        page = self.page(when="not a moment")
        self.assertEqual(self.cells(page, "week"), [])
        self.assertEqual(self.cells(page, "month"), [])


class ThePageNamesTheDayItDrew(ViewBase):
    """A grid of hours belongs to no day and a grid of numbers to no month.

    The page is read hours after it was written, so without the sentence
    yesterday's calendar and today's are the same picture. The reader's own day
    is added by the script, because only the reader's clock knows it.
    """

    def test_the_day_and_the_zone_are_named(self):
        page = view.render(report_mod.Report(findings=[], header=""),
                           [self.load("twice-daily-report")],
                           generated_at="2026-08-23T16:30:00+02:00")
        self.assertIn("drawn for Sunday 23 August 2026", page)
        self.assertIn("Europe/Berlin", page)

    def test_a_moment_nobody_can_read_gets_no_sentence(self):
        """Asserted on the ELEMENT, not on the words.

        The phrase itself also appears in a comment inside the script, so a
        test looking for the words passed on a page that carries the sentence
        and failed on one that does not.
        """
        page = view.render(report_mod.Report(findings=[], header=""),
                           [self.load("twice-daily-report")],
                           generated_at="whenever")
        self.assertNotIn('id="drawnfor"', page)


class TheTableIsSectionedByOneOfTwoQuestions(ViewBase):
    """`--group-by`, and the invariant that makes a second axis safe at all.

    A heading and its rows are paired by ONE attribute, `data-band`, and the
    script compares them literally: it hides a heading whose rows are all
    filtered away by counting the rows that carry the same value. So the axis
    is not free to change one of the two. If a heading is keyed by system while
    its rows stay keyed by band, every heading counts zero rows and the whole
    table disappears the first time somebody types in the search box, which is
    the kind of defect nobody sees in a screenshot.

    The case below therefore does not check that the sections "look right". It
    reads the rendered page and asserts that every row sits under a heading
    carrying its own key, on BOTH axes.
    """

    def stack(self):
        """Three runs: two of one system, one that names none."""
        import dataclasses

        base = self.load("calendar-export")
        return [
            dataclasses.replace(base, id="an-agent", system="a-stack"),
            dataclasses.replace(base, id="an-agent-tunnel", system="a-stack"),
            dataclasses.replace(base, id="a-loner", system="_standalone"),
            dataclasses.replace(base, id="unclassified", system=None),
        ]

    def sections(self, html):
        heads = re.findall(
            r'<tbody class="grouphead" data-band="([^"]*)"[^>]*>.*?'
            r'data-total="(\d+)"', html, re.S)
        rows = re.findall(
            r'<tbody [^>]*data-sort-id="[^"]+"[^>]*data-band="([^"]*)"', html)
        return heads, rows

    def test_the_default_axis_is_the_clock_and_says_so_by_drawing_it(self):
        # The old page, unchanged. A new axis that moved the default would make
        # every reader re-learn a page they already knew.
        heads, _ = self.sections(self.page(workloads=self.stack()))
        self.assertTrue(heads, "no section was drawn at all")
        for key, _count in heads:
            self.assertIn(key, ("clock", "cadence", "continuous", "unplaced"),
                          f"{key!r} is not a band, so the default axis moved")

    def test_runs_that_name_one_system_land_under_one_heading(self):
        heads, _ = self.sections(self.page(workloads=self.stack(),
                                           group_by="system"))
        found = dict(heads)
        self.assertEqual(found.get("a-stack"), "2",
                         f"the two runs of a-stack were not gathered: {heads}")

    def test_every_row_carries_its_own_headings_key_on_both_axes(self):
        # THE case. Everything else here is a convenience next to it.
        for axis in view.GROUP_BY:
            with self.subTest(axis=axis):
                heads, rows = self.sections(
                    self.page(workloads=self.stack(), group_by=axis))
                keys = [key for key, _ in heads]
                for key, count in heads:
                    self.assertEqual(rows.count(key), int(count),
                                     f"{axis}: heading {key!r} says {count} and "
                                     f"{rows.count(key)} rows carry that key, so "
                                     f"the script would hide it")
                for key in rows:
                    self.assertIn(key, keys,
                                  f"{axis}: a row carries {key!r} and no heading does")

    def test_nobody_looked_is_its_own_section_and_not_folded_into_alone(self):
        # The whole reason `_standalone` is a value. One of these two asks the
        # reader for a decision and the other does not, so they must not print
        # as one number.
        heads, _ = self.sections(self.page(workloads=self.stack(),
                                           group_by="system"))
        found = dict(heads)
        self.assertEqual(found.get(view.SYSTEM_ALONE), "1")
        self.assertEqual(found.get(view.SYSTEM_UNDECIDED), "1")

    def test_named_systems_come_in_name_order_and_never_in_size_order(self):
        # An operations page somebody reads every morning must not reshuffle
        # itself the day a system grows a member.
        import dataclasses

        base = self.load("calendar-export")
        loads = [dataclasses.replace(base, id="z-one", system="zulu"),
                 dataclasses.replace(base, id="a-one", system="alpha"),
                 dataclasses.replace(base, id="a-two", system="alpha")]
        heads, _ = self.sections(self.page(workloads=loads, group_by="system"))
        named = [key for key, _ in heads if not key.startswith("_")]
        self.assertEqual(named, ["alpha", "zulu"],
                         "sections are not in name order, so the page reshuffles "
                         "itself when a system grows")

    def test_an_axis_nobody_defined_is_refused_and_not_quietly_the_default(self):
        # Falling back to `band` would draw a plausible page for a request
        # nobody could satisfy, and the caller would never learn its flag was
        # ignored.
        with self.assertRaises(ValueError):
            self.page(workloads=self.stack(), group_by="whatever")


class TheDocumentIsThePageWithoutTheMarkup(ViewBase):
    """`view --json`: the same content for a reader that draws its own.

    The risk is a second derivation. A dashboard that recounts the findings, or
    re-places a run on the day, disagrees with this page the first time either
    of them learns something, and a reader holding both cannot tell which one
    is right. So these cases compare the document against the very stages the
    page is built from, and the page against itself with the document built.
    """

    CONTRACT = ("schema", "host", "generated_at", "zone", "stats", "facets",
                "systems", "runs", "elsewhere")
    RUN_KEYS = ("id", "title", "purpose", "system", "kind", "sphere", "host",
                "runtime", "owner", "when", "unit", "log", "program",
                "program_where", "retired", "state", "severity", "findings",
                "strip", "continuous", "day", "week", "month_due", "ran_days")

    def fixture(self):
        import dataclasses

        base = self.load("calendar-export")
        loads = [dataclasses.replace(base, id="an-agent", system="a-stack"),
                 dataclasses.replace(base, id="a-loner", system="_standalone"),
                 base]
        findings = [
            self.finding("an-agent", "overdue", "high", "no trace since 06:00",
                         hint="look at the log"),
            self.finding("an-agent", "in_sync", "info", "unit matches"),
            self.finding("a-loner", "in_sync", "info", "unit matches"),
            self.finding("old-entry", "inventory_stale", "medium", "names nothing"),
            self.finding("kept-out", "intentionally_absent", "info", "decided"),
            self.finding("someone.daemon", "foreign", "info", "not declared"),
        ]
        history = {"an-agent": [("2026-08-23T05:00:00Z", 0, "ok", "an-agent"),
                                ("2026-08-23T06:00:00Z", 1, "failed", "an-agent")]}
        runs = {"an-agent": ("2026-08-23T06:00:00Z", 1)}
        rep = report_mod.Report(findings=findings, header="1 of 1 probed",
                                history=history, runs=runs, state_dir="/state")
        return rep, loads

    def document(self, rep, loads):
        return view.data(rep, loads, generated_at=STAMP, hosts=("host-a",))

    def test_it_carries_the_contract_keys_and_is_json(self):
        import json

        rep, loads = self.fixture()
        doc = json.loads(json.dumps(self.document(rep, loads)))
        for key in self.CONTRACT:
            self.assertIn(key, doc)
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["host"], "host-a")
        self.assertEqual(set(doc["stats"]),
                         {"in_service", "with_findings", "not_reported", "retired"})
        for facet in ("kind", "sphere", "host", "runtime", "state"):
            self.assertIn(facet, doc["facets"])
        self.assertEqual(set(doc["elsewhere"]),
                         {"inventory_stale", "intentionally_absent", "undeclared"})
        for run in doc["runs"]:
            for key in self.RUN_KEYS:
                self.assertIn(key, run, f"run {run.get('id')} lacks {key}")
            self.assertEqual(len(run["week"]), 7)

    def test_a_run_says_what_its_row_and_lane_say(self):
        rep, loads = self.fixture()
        doc = self.document(rep, loads)
        row = {r.workload_id: r for r in view.rows(rep, loads)}["an-agent"]
        lane = {l.workload_id: l for l in view.lanes(rep, loads)}["an-agent"]
        run = {r["id"]: r for r in doc["runs"]}["an-agent"]
        for key, attr in (("title", "title"), ("purpose", "purpose"),
                          ("kind", "kind"), ("sphere", "persona"),
                          ("host", "host"), ("runtime", "runtime"),
                          ("owner", "owner"), ("when", "when"),
                          ("unit", "unit"), ("log", "log")):
            self.assertEqual(run[key], getattr(row, attr), key)
        self.assertEqual(run["system"], "a-stack")
        self.assertEqual((run["state"], run["severity"]), ("overdue", "high"),
                         "the worst finding is not the run's state")
        self.assertEqual([f["state"] for f in run["findings"]],
                         [view._state(f) for f in row.findings])
        self.assertEqual(run["findings"][0]["hint"], "look at the log")
        self.assertEqual([(s["at"], s["rc"], s["verdict"]) for s in run["strip"]],
                         [entry[:3] for entry in row.strip])
        self.assertEqual(run["day"]["trace_at"], lane.trace_at)
        self.assertEqual(run["day"]["trace_pct"], lane.trace_pct)
        self.assertEqual(run["week"], list(lane.week))
        self.assertEqual(run["ran_days"], sorted(lane.ran))

    def test_silence_is_not_reported_and_never_in_sync(self):
        # The page refuses to read an absent finding as a healthy one, so the
        # document must not either.
        rep, loads = self.fixture()
        run = {r["id"]: r for r in self.document(rep, loads)["runs"]}["calendar-export"]
        self.assertEqual(run["state"], view.UNREPORTED)
        self.assertEqual(run["severity"], "none")

    def test_the_counts_are_the_pages_counts(self):
        rep, loads = self.fixture()
        doc = self.document(rep, loads)
        html = self.page(findings=rep.findings, workloads=loads,
                         history=rep.history, runs=rep.runs, state_dir="/state")
        drawn = dict((k, int(n)) for n, k in re.findall(
            r'<span class="n">(\d+)</span><span class="k">([^<]+)</span>', html))
        self.assertEqual(drawn["in service"], doc["stats"]["in_service"])
        self.assertEqual(drawn["carrying a finding"], doc["stats"]["with_findings"])
        self.assertEqual(drawn[view.UNREPORTED], doc["stats"]["not_reported"])
        self.assertEqual(drawn["retired"], doc["stats"]["retired"])
        pills = dict(((k, v), int(n)) for k, v, n in re.findall(
            r'data-facet="([^"]+)" data-value="([^"]+)" aria-pressed="false">'
            r'[^<]*<span class="n">(\d+)</span>', html))
        names = dict(view.DATA_FACETS)
        for (key, value), n in pills.items():
            self.assertEqual(doc["facets"][names[key]].get(value), n, (key, value))
        self.assertEqual([s["id"] for s in doc["systems"]],
                         ["a-stack", view.SYSTEM_ALONE, view.SYSTEM_UNDECIDED])

    def test_elsewhere_is_split_the_way_the_page_splits_it(self):
        rep, loads = self.fixture()
        out = self.document(rep, loads)["elsewhere"]
        self.assertEqual(out["inventory_stale"], ["old-entry"])
        self.assertEqual(out["intentionally_absent"], ["kept-out"])
        self.assertEqual(out["undeclared"], {"named": ["someone.daemon"], "counted": 0})

    def test_people_are_counted_and_never_named(self):
        import dataclasses
        import json

        rep, loads = self.fixture()
        person = SimpleNamespace(mandant="household", person="a-person-slug")
        loads[0] = dataclasses.replace(
            loads[0], response=SimpleNamespace(recipients=(person,)))
        text = json.dumps(self.document(rep, loads))
        self.assertNotIn("a-person-slug", text)
        run = json.loads(text)["runs"][0]
        self.assertEqual(run["people"], 1)
        self.assertEqual(run["recipient_groups"], ["household"])

    def test_building_the_document_leaves_the_page_unchanged(self):
        rep, loads = self.fixture()
        for axis in view.GROUP_BY:
            with self.subTest(axis=axis):
                before = view.render(rep, loads, generated_at=STAMP,
                                     hosts=("host-a",), group_by=axis)
                self.document(rep, loads)
                after = view.render(rep, loads, generated_at=STAMP,
                                    hosts=("host-a",), group_by=axis)
                self.assertEqual(before, after)
