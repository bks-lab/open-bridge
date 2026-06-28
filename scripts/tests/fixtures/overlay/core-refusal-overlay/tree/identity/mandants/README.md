# Mandants (fixture README)

Fixture: a cluster-wrapper `README.md`. Wrapper READMEs (under `identity/`,
`infra/`, `workflow/`) are CORE — the overlay engine must refuse this dest and
never write it, even though everything else in the overlay is `scope: org`.
