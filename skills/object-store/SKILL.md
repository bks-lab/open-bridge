---
name: object-store
description: >-
  Resolves object://<store>/<key> to a local path or file, never content, for
  what must not live in a repository: recordings, filed documents, exports
  with personal data. Owns declarations in infra/object-stores/. Trigger:
  "/object-store", "object store", "where does this recording go",
  "outside git", "minio", "s3 bucket".
metadata:
  scope: core
allowed-tools:
  - Bash(python3:*)
  - Read
  - Grep
  - Glob
---

# Object store

Owns every object reference in this tree and the stores they point into. The
decision it implements is [`docs/object-store.md`](../../docs/object-store.md);
where this file and the ADR disagree, the ADR wins.

The engine is `skills/object-store/objstore/` behind the shim
`skills/object-store/object-store.sh`. The grammar it parses is a copy of
`infra/object-stores/_schema.yaml`, and `scripts/check-object-grammar.py`
fails CI the day the two drift.

## The principle

Git holds what is read as text, diffed and reviewed. A store holds what is read
whole and moved as bytes. An entry in the tree keeps the reference, the size,
the content hash and the class; the bytes stay in the store.

**There is deliberately no command that prints an object.** Not behind a flag,
not in a pipe. `path` returns a filesystem path, `fetch` writes a file the
caller names, `stat` returns size and sha256. An agent reads this output, and a
multi-gigabyte object in it would end the session that asked for it.

## Arguments

```bash
skills/object-store/object-store.sh stores                           # the declarations here
skills/object-store/object-store.sh stat  object://recordings/2026-09/a.m4a
skills/object-store/object-store.sh path  object://recordings/2026-09/a.m4a --sha256 <hash>
skills/object-store/object-store.sh fetch object://exports/q3.csv --to /tmp/q3.csv
skills/object-store/object-store.sh put   object://recordings/2026-09/a.m4a --from ./a.m4a
skills/object-store/object-store.sh init  recordings                  # mark a local store's root, once
skills/object-store/object-store.sh forget --sha256 <hash>            # drop a cached copy
```

`--root <dir>` names the Bridge whose `infra/object-stores/` applies (default:
the current directory). `path` and `fetch` report `served from: store` or
`served from: cache` on stderr, so stdout stays a path or a line.

## What a failure says

A failure prints `<ref>: <outcome>: <message>` on stderr and nothing on stdout.
None of these is an empty result, because an empty result is what "not there"
and "not reachable" both used to look like to a script that only checked for
output.

| Outcome | Exit | Means |
|---|---|---|
| `not-found` | 3 | the store answered: no such object |
| `usage` | 64 | the command line is wrong: a hash that is not one, a file that is not there |
| `unexpected` | 70 | anything the resolver did not anticipate, reported by its TYPE only |
| `store-not-declared` | 4 | the reference is well formed; no declaration here answers its store |
| `denied` / `refused` | 5 | the store said no, or the resolver will not do it (a key outside the root, a hash that does not match) |
| `not-reachable` | 69 | measured live: the directory is not there, the service did not answer |
| `malformed-reference` | 78 | not `object://<store>/<key>`, or a key with `..` in it |
| `credentials-unavailable` | 78 | the store needs keys and nothing could hand them over |
| `bad-declaration` | 78 | a file in `infra/object-stores/` the resolver cannot use |

## Credentials

A declaration names `credentials.access_key_ref` and `secret_key_ref`, both
references into a secret store. They are resolved in this order: the
environment, PER STORE (`OBJECT_STORE_<NAME>_ACCESS_KEY_ID` and
`OBJECT_STORE_<NAME>_SECRET_ACCESS_KEY`, `<NAME>` upper case with `-` as `_`,
which is what `secrets run --env NAME=<ref> -- ...` hands a child), then the
secrets skill next to this one, in-process. Per store, because one pair for all
stores sent store A's key to store B. A value never travels in argv and is never
printed; a value with a character a header cannot carry is refused without
being shown. A local store needs none.

## Which store answers

The most specific address wins across all declarations: an exact name, then the
longest prefix (`rec*`), then `*`. Two stores claiming a name equally is refused.
A catch-all bucket must never take a reference meant for a named local store
because its filename sorts first.

## The cache, and why there is no queue

Reads that know the content hash (a tracked entry does) consult
`.bridge/objects/` first, a content-addressed cache capped at 2 GiB
(`OBJECT_STORE_CACHE_MAX_BYTES`). That is the offline answer: a store that
cannot be reached still serves what was read before, and says so.

Writes never touch the cache and never queue. A write that cannot land fails
with `not-reachable`. To work offline, write to a local store and copy later,
with an operation somebody can see.

A local store's root must already exist AND carry the marker `init` writes. An
unmounted volume leaves an empty mount point behind, which `is_dir()` calls a
directory, and a write there would put the bytes on the boot disk. `init` marks
an existing directory and never creates one.

The cache keeps a copy after the store deleted the object, for as long as
somebody knows its hash. When an object has to be ERASED, run `forget` too.
Cached files are read-only: `path` hands out the file itself.

## Limits, said out loud

- Uploads are a single PUT, which S3 limits to 5 GiB.
- A missing key answers 404 only to a principal allowed to list the bucket.
  With a GetObject-only credential S3 answers 403, and this resolver reports
  `denied`: it cannot tell the two apart and does not pretend to.
- Redirects are refused, never followed: the request carries a signature valid
  for minutes, and following would hand it to another host.
- A download is checked against Content-Length and against the sha256 recorded
  with the object; a download that fails either is never kept.

## What is not here yet

Named in the ADR as not decided, so not built: encryption beyond what the
service does at rest, versioning and retention per class, garbage collection of
objects nothing references, a `where <class>` answer from `holds`, the index over
a large corpus, and objects shipped by an org overlay.

## Decision Tree

```
User wants to...
├── know which stores exist here        → stores
├── check an object without reading it  → stat
├── hand an object to a program         → path (or fetch --to <file>)
├── file content outside git            → put, then track the reference, size and sha256
├── declare a new store                 → copy infra/object-stores/_template.yaml
└── read an object into the answer      → NO. There is no such command.
```

## Tests

```bash
bash skills/object-store/run-tests.sh            # the suite
bash skills/object-store/run-tests.sh --mutate   # every needle must turn its test red
bash infra/object-stores/_tests/run.sh --mutate  # the schema's controls
```

## Hard Rules (non-negotiable)

- Never print an object's content, and never add a command that does.
- Never put a key, token or connection string into a store declaration.
- Never create a local store's root on a write.
- Never queue, spool or retry a write in the background.
- Never infer reachability from `reachable_from`; measure it.
- Never create a local store's root, and never mark one that is not really there.
