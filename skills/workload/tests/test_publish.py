"""publish: putting the page where a browser reaches it, and the two ways that lies.

The first lie is about the destination. A served directory usually belongs to
something already: a puller that rsyncs it back, another system's views. Writing
into it works, and then either the next sync deletes this page without a word or
this page overwrites theirs. So the destination has to be *proved* ours before a
single byte moves, and the proof is a marker inside it, the same shape the rest
of this skill uses for the units it owns.

The second lie is one word for two facts. Bytes landing on a disk and a browser
receiving them are different questions with different failure modes: a file in
the wrong directory lands perfectly and is never served. "Published" collapses
them, so this module never says it. It says delivered, and separately reachable,
and reachable stays unknown rather than false where nobody asked.
"""

from __future__ import annotations

import unittest

from tests.conftest import FakeCompleted, FakeHost, MachineGuard, RecordingRunner, mod

errors = mod("engine.errors")
publish = mod("engine.publish")

PAGE = "<!doctype html>\n<html lang=\"en\">the page</html>\n"
DEST = "~/site/workloads"


class PublishBase(MachineGuard):

    def setUp(self):
        super().setUp()
        self.host = FakeHost(slug="host-a")

    def runner(self, *, listing=None, marker=None, readback=PAGE, write_rc=0,
               attached=()):
        """A machine that answers the questions publish asks.

        `listing=None` means the directory does not exist; `marker=None` means
        there is none. Order matters: every write matches the first route, so a
        marker being written is never mistaken for a marker being read.

        `attached` is a sequence of (name, bytes-that-come-back) for the files
        travelling with the page, `None` for one the machine cannot hand back.
        Their routes sit after the page's, which is safe because a route is a
        substring of the argv and no attachment may be called `index.html`
        twice: `deliveries` refuses that before a runner is ever reached.
        """
        r = RecordingRunner()
        r.add("cat > ", FakeCompleted(rc=write_rc))
        r.add(".workload-view",
              FakeCompleted(rc=1) if marker is None else FakeCompleted(rc=0, stdout=marker))
        r.add("index.html",
              FakeCompleted(rc=1) if readback is None else FakeCompleted(rc=0, stdout=readback))
        for name, back in attached:
            r.add(name, FakeCompleted(rc=1) if back is None
                  else FakeCompleted(rc=0, stdout=back))
        r.add("ls -A",
              FakeCompleted(rc=1, stderr="No such file or directory") if listing is None
              else FakeCompleted(rc=0, stdout="".join(f"{e}\n" for e in listing)))
        return r

    #: Probed off the machine in real use, fixed here. Never a default in the
    #: engine: a guessed home writes into somebody else's directory.
    HOME = "/home/someone"

    def run_publish(self, runner, **kw):
        kw.setdefault("dest", DEST)
        kw.setdefault("dry_run", False)
        kw.setdefault("home", self.HOME)
        return publish.publish(PAGE, self.host, runner=runner, timeout_sec=30, **kw)


class ItRefusesADirectoryItDoesNotOwn(PublishBase):

    def test_a_directory_full_of_someone_elses_files_is_refused(self):
        # The concrete accident this exists for: the root of a served directory,
        # owned by a puller that rsyncs it back on every commit.
        runner = self.runner(listing=["index.html", "assets", "betrieb", "state.json"])
        with self.assertRaises(errors.DestinationNotOurs) as caught:
            self.run_publish(runner, dest="~/site")
        said = str(caught.exception)
        self.assertIn("index.html", said,
                      "the refusal has to name what it found, or the reader "
                      "cannot tell whether it is right")
        self.assertFalse(runner.called_with("cat > "),
                         "it refused AFTER writing, which is not refusing")

    def test_a_marker_naming_another_producer_is_refused(self):
        runner = self.runner(listing=["index.html", ".workload-view"],
                             marker="producer: bridge-ops-publish\n")
        with self.assertRaises(errors.DestinationNotOurs) as caught:
            self.run_publish(runner)
        self.assertIn("bridge-ops-publish", str(caught.exception))
        self.assertFalse(runner.called_with("cat > "))

    def test_a_directory_that_does_not_exist_yet_is_taken_with_a_marker(self):
        runner = self.runner(listing=None)
        outcome = self.run_publish(runner)
        self.assertTrue(outcome.delivered)
        self.assertIn(publish.MARKER, runner.joined_calls,
                      "it took the directory without leaving anything that says so, "
                      "so the next run cannot tell its own output from a stranger's")
        # Claim first, write second. The other order leaves, when the marker
        # write fails, a page nobody claims, which every later run refuses as a
        # stranger's: a lockout on our own output.
        writes = [i for i, c in enumerate(runner.calls) if "cat > " in c["joined"]]
        claim = [i for i in writes if publish.MARKER in runner.calls[i]["joined"]]
        self.assertEqual(len(claim), 1, "the marker was not written exactly once")
        self.assertEqual(claim[0], writes[0],
                         "the page was written before the directory was claimed")

    def test_an_empty_directory_is_taken_too(self):
        # Empty is not foreign. Nothing is at risk of being overwritten.
        outcome = self.run_publish(self.runner(listing=[]))
        self.assertTrue(outcome.delivered)

    def test_a_directory_this_skill_already_owns_is_reused(self):
        runner = self.runner(listing=[".workload-view", "index.html"],
                             marker=f"producer: {publish.PRODUCER}\n")
        outcome = self.run_publish(runner)
        self.assertTrue(outcome.delivered)


class DeliveredIsNotReachable(PublishBase):

    def test_delivery_is_proved_by_reading_the_bytes_back(self):
        runner = self.runner(listing=[])
        outcome = self.run_publish(runner)
        self.assertTrue(outcome.delivered)
        self.assertTrue(runner.called_with("2>/dev/null"),
                        "nothing was read back, so 'delivered' is the return code "
                        "of a write talking about itself")

    def test_bytes_that_came_back_different_are_not_delivered(self):
        runner = self.runner(listing=[], readback="<html>something else</html>\n")
        outcome = self.run_publish(runner)
        self.assertFalse(outcome.delivered)
        self.assertIn("differ", outcome.evidence.lower())

    def test_a_write_that_never_arrived_is_not_delivered(self):
        outcome = self.run_publish(self.runner(listing=[], readback=None))
        self.assertFalse(outcome.delivered)

    def test_reachable_stays_unknown_when_no_url_was_given(self):
        outcome = self.run_publish(self.runner(listing=[]))
        self.assertIsNone(outcome.reachable,
                          "False would be a claim nobody made: nothing was fetched")

    def test_the_fetch_is_never_made_unless_a_url_was_given(self):
        calls = []
        self.run_publish(self.runner(listing=[]),
                         fetch=lambda url, **kw: calls.append(url))
        self.assertEqual(calls, [])

    def test_reachable_is_claimed_only_after_the_body_came_back_equal(self):
        seen = []

        def fetch(url, **kw):
            seen.append(url)
            return 200, PAGE.encode("utf-8")

        outcome = self.run_publish(self.runner(listing=[]),
                                   url="http://host-a:8080/workloads/", fetch=fetch)
        self.assertTrue(outcome.delivered)
        self.assertTrue(outcome.reachable)
        self.assertEqual(seen, ["http://host-a:8080/workloads/"])

    def test_a_url_that_serves_other_bytes_is_not_reachable(self):
        # The exact failure the ssh half cannot see: the file landed, and the
        # server is serving a different directory.
        outcome = self.run_publish(
            self.runner(listing=[]), url="http://host-a:8080/workloads/",
            fetch=lambda url, **kw: (200, b"<html>directory listing</html>"))
        self.assertTrue(outcome.delivered)
        self.assertFalse(outcome.reachable)

    def test_a_server_that_answers_with_an_error_is_not_reachable(self):
        outcome = self.run_publish(
            self.runner(listing=[]), url="http://host-a:8080/workloads/",
            fetch=lambda url, **kw: (404, b""))
        self.assertFalse(outcome.reachable)
        self.assertIn("404", outcome.evidence)


class TheDryRunIsTheDefaultAndTouchesNothing(PublishBase):

    def test_a_dry_run_writes_nothing(self):
        runner = self.runner(listing=[])
        outcome = publish.publish(PAGE, self.host, dest=DEST, runner=runner, home=self.HOME,
                                  timeout_sec=30, dry_run=True)
        self.assertFalse(runner.called_with("cat > "))
        self.assertFalse(outcome.delivered,
                         "a dry run reported delivery, which is the one thing it "
                         "cannot know")

    def test_a_dry_run_still_refuses_a_foreign_directory(self):
        # It has to, or the refusal is discovered only by the run that writes.
        with self.assertRaises(errors.DestinationNotOurs):
            publish.publish(PAGE, self.host, dest="~/site", home=self.HOME,
                            runner=self.runner(listing=["index.html", "assets"]),
                            timeout_sec=30, dry_run=True)

    def test_the_dry_run_prints_the_steps_the_real_run_would_take(self):
        dry = publish.publish(PAGE, self.host, dest=DEST, runner=self.runner(listing=[]),
                              home=self.HOME, timeout_sec=30, dry_run=True)
        wet_runner = self.runner(listing=[])
        publish.publish(PAGE, self.host, dest=DEST, runner=wet_runner, home=self.HOME,
                        timeout_sec=30, dry_run=False)
        planned = [s.purpose for s in dry.steps]
        self.assertTrue(planned, "a dry run that lists nothing shows nothing")
        for purpose in planned:
            self.assertIn(purpose, [c["step"].purpose for c in wet_runner.calls
                                    if c["step"] is not None],
                          f"the dry run announced {purpose!r} and the real run "
                          "did something else")


class APageTooLargeToTravelIsRefusedByName(PublishBase):

    def test_a_page_that_will_not_fit_in_an_argv_is_refused_before_it_is_tried(self):
        # One line longer than a part: the only thing the split cannot carry,
        # because it splits on line boundaries and never inside a line.
        huge = "<p>" + "x" * (publish.MAX_BYTES + 1) + "</p>\n"
        with self.assertRaises(errors.PageTooLarge) as caught:
            publish.publish(huge, self.host, dest=DEST, runner=self.runner(listing=[]),
                            home=self.HOME, timeout_sec=30, dry_run=False)
        said = str(caught.exception)
        self.assertIn(str(publish.MAX_BYTES), said,
                      "the limit has to be in the refusal; an unexplained size "
                      "error reads as a broken tool")

    def test_a_large_page_of_ordinary_lines_travels_in_parts(self):
        # The page that stood still from 14.09. to 18.09. 2026: 556143 bytes,
        # longest line 13 KB. It was refused against a whole-file limit that
        # stopped being the transport's limit when writes began to travel in
        # parts, so /workloads/ showed four-day-old numbers as the present.
        big = "<p>x</p>\n" * (600 * 1024 // 9)
        outcome = publish.publish(big, self.host, dest=DEST,
                                  runner=self.runner(listing=[]), home=self.HOME,
                                  timeout_sec=30, dry_run=True)
        parts = [s.purpose for s in outcome.steps if "index.html, part " in s.purpose]
        self.assertGreater(len(parts), 1,
                           "a page over one part has to be written in several")


if __name__ == "__main__":
    unittest.main()


class ATildeIsResolvedAgainstTheMachinesOwnHome(PublishBase):
    """The path goes into a quoted shell word, where `~` is a directory name.

    It cost a real publish: every path travels quoted, so `~/site/workloads`
    reached the machine as a literal tilde and `mkdir -p` made a directory
    called `~` in the home directory. Nothing noticed, because the write and the
    read-back used the same wrong path and agreed with each other perfectly. Two
    procedures that can only agree prove nothing; it took the HTTP fetch, which
    goes the other way round, to show the page was not where it was said to be.
    """

    def test_a_leading_tilde_becomes_the_probed_home(self):
        runner = self.runner(listing=[])
        self.run_publish(runner, dest="~/site/workloads", home=self.HOME)
        self.assertIn(f"{self.HOME}/site/workloads", runner.joined_calls)
        self.assertNotIn("'~/site", runner.joined_calls,
                         "a quoted tilde reached the machine, where it is the "
                         "name of a directory and not the home directory")

    def test_the_home_is_never_guessed(self):
        # Refused by name rather than passed through. The failure it replaces is
        # silent: files land in a directory nobody looks at and every proof
        # agrees they are fine.
        with self.assertRaises(errors.DestinationNotResolvable) as caught:
            self.run_publish(self.runner(listing=[]), dest="~/site/workloads", home=None)
        self.assertIn("~", str(caught.exception))

    def test_another_users_home_is_refused_rather_than_resolved(self):
        with self.assertRaises(errors.DestinationNotResolvable):
            self.run_publish(self.runner(listing=[]), dest="~someone-else/site",
                             home=self.HOME)

    def test_an_absolute_destination_is_left_alone(self):
        runner = self.runner(listing=[])
        self.run_publish(runner, dest="/srv/site/workloads", home=self.HOME)
        self.assertIn("/srv/site/workloads", runner.joined_calls)


class TheFetcherItselfIsMeasured(MachineGuard):
    """The one seam every other case replaces.

    Each test above hands `publish` a fetcher that returns a tuple, so the real
    one was never run: it raised on any status other than 200 instead of
    reporting it, and the branch that reports a 404 was unreachable in the only
    implementation that ships. The same shape of gap, in the same skill, as an
    ssh call that nothing ever crossed. So this one talks to a real socket, on
    the loopback interface, against a server this test starts itself.
    """

    def serve(self, handler):
        import http.server
        import threading
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/"

    def handler_for(self, status, body=b""):
        import http.server

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                              # noqa: N802
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):                     # silence the test output
                return

        return Handler

    def test_a_page_that_is_served_comes_back_with_its_bytes(self):
        url = self.serve(self.handler_for(200, b"<html>the page</html>"))
        status, body = publish._fetch(url, timeout_sec=10)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<html>the page</html>")

    def test_a_status_that_is_not_two_hundred_is_reported_and_not_raised(self):
        url = self.serve(self.handler_for(404, b"nope"))
        status, _ = publish._fetch(url, timeout_sec=10)
        self.assertEqual(status, 404,
                         "the real fetcher raised instead of answering, so the "
                         "branch that reports an unreachable page never ran")

    def test_a_server_that_is_not_there_is_unreachable_rather_than_a_crash(self):
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with self.assertRaises(errors.Unreachable):
            publish._fetch(f"http://127.0.0.1:{port}/", timeout_sec=5)


class TheMarkerSaysWhatIsThereAndWhatWillHappenToIt(PublishBase):
    """The marker is the directory's one statement about its own content.

    It used to say that every file here is overwritten on the next publish.
    Nothing in the delivery path removes anything: there is no `rm`, no
    `rsync --delete`, only a marker and the named files being rewritten. So a
    file that landed here once and has since dropped out of the output stays,
    and a web server hands it out exactly as if it were current. The sentence
    was wrong in the one direction that costs a reader something, because it
    reads as a guarantee that the directory holds nothing stale.
    """

    def marker_written(self, runner) -> str:
        for call in runner.calls:
            if "cat > " in call["joined"] and publish.MARKER in call["joined"]:
                return call["joined"]
        raise AssertionError(f"no marker was written; calls were:\n{runner.joined_calls}")

    def test_the_marker_does_not_promise_that_the_directory_is_swept(self):
        said = publish.marker_body(("index.html",)).lower()
        self.assertNotIn("every file here is overwritten", said,
                         "the marker states something the delivery path cannot "
                         "do: it holds no rm and no rsync --delete")
        self.assertIn("nothing here is ever removed", said,
                      "the correction has to be IN the marker: whoever opens "
                      "this directory reads the file, not the source")

    def test_the_marker_says_what_follows_for_the_reader(self):
        # A true sentence nobody can act on is half an answer. What follows is
        # that the list below is the current set and everything else in the
        # directory is a leftover somebody has to delete by hand.
        said = publish.marker_body(("index.html",)).lower()
        self.assertIn("leftover", said)
        self.assertIn("by hand", said)

    def test_the_list_of_delivered_files_has_no_default(self):
        # The point of the parameter. A default list is a second truth about
        # the directory that no caller has to keep up to date, which is the
        # drift the marker exists to prevent.
        with self.assertRaises(TypeError):
            publish.marker_body()

    def test_the_marker_names_every_file_that_was_delivered(self):
        runner = self.runner(listing=[], attached=[("style.css", "body{}\n")])
        self.run_publish(runner,
                         attachments=(publish.Attachment(name="style.css",
                                                         content="body{}\n"),))
        claim = self.marker_written(runner)
        self.assertIn("index.html", claim)
        self.assertIn("style.css", claim,
                      "the marker names the page and not the file beside it, so "
                      "the directory's own statement is already incomplete on "
                      "the run that wrote it")

    def test_a_file_from_an_earlier_publish_is_named_rather_than_left_unsaid(self):
        # The practical consequence of the corrected sentence. `dienste.html`
        # was delivered last week, is not delivered now, and is still served.
        runner = self.runner(listing=[".workload-view", "index.html", "dienste.html"],
                             marker=f"producer: {publish.PRODUCER}\n")
        outcome = self.run_publish(runner)
        self.assertEqual(outcome.leftovers, ("dienste.html",))
        self.assertTrue(outcome.delivered,
                        "a leftover is not a failure: the page arrived")

    def test_what_this_run_delivers_is_never_called_a_leftover(self):
        runner = self.runner(listing=[".workload-view", "index.html", "style.css"],
                             marker=f"producer: {publish.PRODUCER}\n",
                             attached=[("style.css", "body{}\n")])
        outcome = self.run_publish(runner,
                                   attachments=(publish.Attachment(name="style.css",
                                                                   content="body{}\n"),))
        self.assertEqual(outcome.leftovers, ())


class AttachmentsTravelWithThePageAndAreProvedLikeIt(PublishBase):
    """A page is often not one file, and a stylesheet that failed is a fact.

    Each attachment is written byte for byte, read back off the machine and
    compared, exactly like the page. It never shares the page's verdict:
    "the page arrived and the stylesheet did not" is a third situation, and one
    boolean over the set cannot tell a reader which of the three they have.
    """

    CSS = "body { color: red; }\n"

    def attach(self, name="style.css", content=None):
        return publish.Attachment(name=name, content=self.CSS if content is None
                                  else content)

    def test_an_attachment_is_written_and_read_back_off_the_machine(self):
        runner = self.runner(listing=[], attached=[("style.css", self.CSS)])
        outcome = self.run_publish(runner, attachments=(self.attach(),))
        self.assertTrue(outcome.delivered)
        self.assertEqual([item.name for item in outcome.attachments], ["style.css"])
        self.assertTrue(outcome.attachments[0].delivered)
        reads = [c["joined"] for c in runner.calls
                 if "2>/dev/null" in c["joined"] and "style.css" in c["joined"]]
        self.assertTrue(reads,
                        "the attachment was written and never read back, so its "
                        "'delivered' is the return code of the write talking "
                        "about itself")

    def test_the_page_is_delivered_before_anything_travels_with_it(self):
        runner = self.runner(listing=[], attached=[("style.css", self.CSS)])
        self.run_publish(runner, attachments=(self.attach(),))
        writes = [c["joined"] for c in runner.calls if "cat > " in c["joined"]]
        self.assertEqual(len(writes), 3, f"expected marker, page, attachment: {writes}")
        self.assertIn(publish.MARKER, writes[0])
        self.assertIn("index.html", writes[1])
        self.assertIn("style.css", writes[2])

    def test_an_attachment_that_did_not_arrive_leaves_the_page_delivered(self):
        # The page is the subject of the publish and the attachment its
        # baggage. Collapsing the two would report a healthy, reachable page as
        # a run that delivered nothing, and somebody would republish the page.
        runner = self.runner(listing=[], attached=[("style.css", None)])
        outcome = self.run_publish(runner, attachments=(self.attach(),))
        self.assertTrue(outcome.delivered)
        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.attachments[0].delivered)
        self.assertFalse(outcome.complete,
                         "a run asked for two files that delivered one has to "
                         "be distinguishable from one that delivered both")

    def test_an_attachment_that_came_back_different_is_not_delivered(self):
        runner = self.runner(listing=[],
                             attached=[("style.css", "body { color: blue; }\n")])
        outcome = self.run_publish(runner, attachments=(self.attach(),))
        self.assertFalse(outcome.attachments[0].delivered)
        self.assertIn("differ", outcome.attachments[0].evidence.lower())
        self.assertIn("style.css", outcome.attachments[0].evidence,
                      "the sentence has to name WHICH file, or a publish with "
                      "four attachments reports a mystery")

    def test_the_evidence_line_alone_does_not_read_as_a_clean_run(self):
        # Some callers print the evidence and nothing else. If the baggage is
        # only in a field they do not read, a run that lost a file reads
        # exactly like one that lost none.
        runner = self.runner(listing=[], attached=[("style.css", None)])
        outcome = self.run_publish(runner, attachments=(self.attach(),))
        self.assertIn("0 of 1 attached file(s) delivered", outcome.evidence)
        self.assertIn("style.css", outcome.evidence)

    def test_an_oversize_attachment_is_refused_by_name_and_never_truncated(self):
        huge = "x" * (publish.MAX_BYTES + 10) + "\n"
        runner = self.runner(listing=[])
        with self.assertRaises(errors.PageTooLarge) as caught:
            self.run_publish(runner, attachments=(self.attach(content=huge),))
        self.assert_error(caught, "page-too-large",
                          str(publish.MAX_BYTES), "style.css")
        self.assertFalse(runner.called_with("cat > "),
                         "it refused after writing, and the limit is per FILE "
                         "because each one travels in a command line of its own")

    def test_two_attachments_under_one_name_are_refused(self):
        # Two directories, one basename. The second would overwrite the first,
        # both would read back equal to what was sent, and the report would
        # show two files delivered where the directory holds one.
        with self.assertRaises(errors.Refused) as caught:
            self.run_publish(self.runner(listing=[]),
                             attachments=(self.attach(), self.attach()))
        self.assert_error(caught, "attachment-name-collision", "style.css")

    def test_an_attachment_may_not_be_called_like_the_marker(self):
        with self.assertRaises(errors.Refused) as caught:
            self.run_publish(self.runner(listing=[]),
                             attachments=(self.attach(name=publish.MARKER),))
        self.assert_error(caught, "attachment-name-collision", publish.MARKER)

    def test_an_attachment_may_not_address_a_directory_of_its_own(self):
        # The ownership proof covers ONE directory. A name with a separator in
        # it would write outside the only place that was proved ours.
        with self.assertRaises(errors.Refused) as caught:
            self.run_publish(self.runner(listing=[]),
                             attachments=(self.attach(name="assets/style.css"),))
        self.assert_error(caught, "attachment-name-invalid")

    def test_a_directory_holding_our_own_attachment_is_still_ours(self):
        runner = self.runner(listing=[".workload-view", "index.html", "style.css"],
                             marker=f"producer: {publish.PRODUCER}\n",
                             attached=[("style.css", self.CSS)])
        outcome = self.run_publish(runner, attachments=(self.attach(),))
        self.assertTrue(outcome.delivered)
        self.assertTrue(outcome.attachments[0].delivered)

    def test_a_dry_run_announces_the_attachment_it_would_write(self):
        runner = self.runner(listing=[], attached=[("style.css", self.CSS)])
        dry = publish.publish(PAGE, self.host, dest=DEST, runner=runner,
                              home=self.HOME, timeout_sec=30, dry_run=True,
                              attachments=(self.attach(),))
        planned = " ".join(step.purpose for step in dry.steps)
        self.assertIn("style.css", planned)
        self.assertFalse(runner.called_with("cat > "))

    def test_the_dry_run_and_the_real_run_plan_the_same_work(self):
        # The same property the page already has, extended over the baggage:
        # two constructions of the plan drift, and the preview is then a
        # preview of something else.
        dry = publish.publish(PAGE, self.host, dest=DEST, home=self.HOME,
                              runner=self.runner(listing=[],
                                                 attached=[("style.css", self.CSS)]),
                              timeout_sec=30, dry_run=True,
                              attachments=(self.attach(),))
        wet = self.runner(listing=[], attached=[("style.css", self.CSS)])
        self.run_publish(wet, attachments=(self.attach(),))
        taken = [c["step"].purpose for c in wet.calls if c["step"] is not None]
        for purpose in [s.purpose for s in dry.steps]:
            self.assertIn(purpose, taken,
                          f"the dry run announced {purpose!r} and the real run "
                          "did something else")


class WhatCannotTravelIsRefusedBeforeAMachineIsAsked(PublishBase):
    """Every attachment refusal is knowable without asking the destination.

    So all of them happen here, before a marker is written. A refusal halfway
    through leaves a directory in a state the report does not describe, and
    somebody then has to work out by hand what got there.
    """

    def file(self, name, text):
        path = self.tmpdir() / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_file_is_read_and_keeps_its_own_name(self):
        path = self.file("style.css", "body{}\n")
        got = publish.load_attachments([str(path)])
        self.assertEqual([a.name for a in got], ["style.css"])
        self.assertEqual(got[0].content, "body{}\n")

    def test_nothing_named_is_nothing_read(self):
        self.assertEqual(publish.load_attachments(()), ())

    def test_a_path_that_is_not_a_file_is_refused_by_name(self):
        missing = self.tmpdir() / "gone.css"
        with self.assertRaises(errors.WorkloadError) as caught:
            publish.load_attachments([str(missing)])
        self.assert_error(caught, "attachment-unreadable", "gone.css")

    def test_a_directory_is_not_an_attachment(self):
        # A publish that walked one would deliver whatever happened to be in it
        # that day, which is a different set on every run and never declared.
        with self.assertRaises(errors.WorkloadError) as caught:
            publish.load_attachments([str(self.tmpdir())])
        self.assert_error(caught, "attachment-unreadable")

    def test_bytes_that_are_not_text_are_refused_rather_than_mangled(self):
        path = self.tmpdir() / "logo.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        with self.assertRaises(errors.WorkloadError) as caught:
            publish.load_attachments([str(path)])
        self.assert_error(caught, "attachment-unreadable", "logo.png")

    def test_a_file_that_does_not_end_on_a_newline_is_refused(self):
        # The transport is a quoted here-document and cannot express one. It
        # would add the byte itself, and the read-back would then report a
        # difference the machine never caused, pointing the reader at the
        # wrong end of the wire.
        path = self.file("style.css", "body{}")
        with self.assertRaises(errors.WorkloadError) as caught:
            publish.load_attachments([str(path)])
        self.assert_error(caught, "attachment-not-transportable", "style.css")

    def test_an_empty_file_is_refused_for_the_same_reason(self):
        path = self.file("empty.css", "")
        with self.assertRaises(errors.WorkloadError) as caught:
            publish.load_attachments([str(path)])
        self.assert_error(caught, "attachment-not-transportable")


class TheReportStillDescribesTheDirectoryWhenSomethingWentWrong(PublishBase):
    """Three cases the happy path does not reach, and each one hides a hole.

    A run that half worked is the one whose report gets read carefully, so the
    facts have to survive the failure: what the attachments did when the PAGE
    failed, what is stale in a directory nobody has written to yet, and whether
    accepting attachments quietly widened the guard into taking any directory
    at all.
    """

    CSS = "body { color: red; }\n"

    def test_a_page_that_failed_still_reports_what_its_attachments_did(self):
        # Otherwise the directory is left in a state the report does not
        # describe, and the next attempt is planned against a guess.
        runner = self.runner(listing=[], readback=None,
                             attached=[("style.css", self.CSS)])
        outcome = self.run_publish(
            runner, attachments=(publish.Attachment("style.css", self.CSS),))
        self.assertFalse(outcome.delivered)
        self.assertEqual([(a.name, a.delivered) for a in outcome.attachments],
                         [("style.css", True)],
                         "the page failed and the baggage was dropped from the "
                         "report, so nothing says what is now in that directory")

    def test_a_dry_run_names_the_leftovers_too(self):
        # Before writing is exactly when somebody wants to know, and the
        # listing the answer comes from has already been read by then.
        outcome = publish.publish(
            PAGE, self.host, dest=DEST, home=self.HOME, timeout_sec=30, dry_run=True,
            runner=self.runner(listing=[".workload-view", "index.html", "dienste.html"],
                               marker=f"producer: {publish.PRODUCER}\n"))
        self.assertEqual(outcome.leftovers, ("dienste.html",))

    def test_a_directory_holding_a_stranger_is_still_refused(self):
        # The Gegenprobe for accepting our own attachments back: the guard must
        # not have widened into taking anything that happens to be there.
        with self.assertRaises(errors.DestinationNotOurs):
            self.run_publish(self.runner(listing=["index.html", "assets"]),
                             dest="~/site",
                             attachments=(publish.Attachment("style.css", self.CSS),))


class EveryPartOfAPageIsWrittenBeforeItIsReadBack(PublishBase):
    """The read-back is what makes splitting a file safe, so it comes last.

    Interleaved, a read-back after the first part would compare a fragment
    against the whole page and report a delivery that had not happened yet.
    """

    def big(self):
        return "<!doctype html>\n" + "".join(f"<p>{n}</p>\n" for n in range(20000))

    def test_the_page_travels_in_several_parts(self):
        steps = publish.steps_for(self.big(), DEST)
        writes = [s for s in steps if "cat >" in s.argv[2] and "index.html" in s.argv[2]]
        self.assertGreater(len(writes), 1,
                           "a page larger than one command line went as one")

    def test_and_every_one_of_them_comes_before_the_read_back(self):
        steps = publish.steps_for(self.big(), DEST)
        scripts = [s.argv[2] for s in steps]
        last_write = max(i for i, s in enumerate(scripts)
                         if "cat >" in s and "index.html" in s)
        readback = min(i for i, s in enumerate(scripts)
                       if "cat " in s and "index.html" in s and "cat >" not in s)
        self.assertLess(last_write, readback)
