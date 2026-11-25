# From the cmux browser to Playwright

For skills that drove the cmux browser pane (`cmux browser <verb>`, or an MCP server wrapping it).
Start a session with `browser.py start <session> <url>` instead of `cmux browser open`, then:

| cmux browser | Playwright CLI (`playwright-cli -s=<session> …`) |
|---|---|
| `open`, `navigate`, `goto` | `goto <url>` (the first page comes with `browser.py start`) |
| `back`, `forward`, `reload` | `go-back`, `go-forward`, `reload` |
| `url`, `get-url` | every reply carries `- Page URL:` |
| `snapshot` | `snapshot`; `find <text>` searches a large one |
| `click`, `hover`, `dblclick` | `click <ref>`, `hover <ref>`, `dblclick <ref>` |
| `fill`, `type` | `fill <ref> <text>` (add `--submit` for Enter), `type <text>` |
| `press` | `press <key>` |
| `select`, `check`, `uncheck` | `select <ref> <value>`, `check <ref>`, `uncheck <ref>` |
| `set-input-files` | `click <ref of the file input>`, then `upload <path>` |
| `eval` | `eval "<expression>"`; `eval "<fn>" <ref>` for one element |
| `wait` | actions wait on their own; otherwise `run-code` with `waitFor` |
| `screenshot` | `screenshot [--filename=f]`, `screenshot <ref>` for one element |
| `console`, `errors` | `console [error]` |
| `tab` | `tab-list`, `tab-new [url]`, `tab-select <i>`, `tab-close [i]` |
| `cookies`, `storage` | `cookie-list`, `localstorage-list`, `state-save` |
| `dialog` | `dialog-accept [text]`, `dialog-dismiss` |
| `frame` | `snapshot` includes iframe content with its own refs; check it on the page at hand |

Logins made in the cmux browser do not move over: log in once in the new session's profile.
