# A2A on the wire: 1.x and 0.3

| | 1.x (spec 1.0, SDK a2a-sdk 1.x) | 0.3 |
|---|---|---|
| Send | `SendMessage` | `message/send` |
| Stream | `SendStreamingMessage` | `message/stream` |
| Read back | `GetTask` | `tasks/get` |
| Cancel | `CancelTask` | `tasks/cancel` |
| Header | `A2A-Version: 1.0` | none |
| Role | `ROLE_USER` | `user` |
| Part | `{"text": "..."}` | `{"kind": "text", "text": "..."}` |
| Result | `{"task": {...}}` or `{"message": {...}}` | the task itself, `kind: task` |
| States | `TASK_STATE_COMPLETED`, ... | `completed`, ... |
| Card: where to call | `supportedInterfaces[].url` + `protocolBinding` + `protocolVersion` | top-level `url`, `preferredTransport`, `protocolVersion` |
| Card path | `/.well-known/agent-card.json` | `/.well-known/agent.json` (older) |

Pick the dialect from the card, never from habit. A 1.x server built on a2a-sdk may
also accept 0.3 on the same URL (`enable_v0_3_compat`).

States that matter to a caller: `WORKING` (keep polling), `INPUT_REQUIRED` (the
server wants input from YOU), `AUTH_REQUIRED`, and the terminal ones `COMPLETED`,
`FAILED`, `CANCELED`, `REJECTED`. A server that waits for its own owner's approval
should stay `WORKING` with a status message, not `INPUT_REQUIRED`.

A Bridge agent whose slots are all taken ends the task `FAILED` with `reason: busy`
and `retry_after_s` in the status message metadata. That is "ask again later", not
an answer: `a2a.py ask` waits the suggested delay (capped at 30 s) and sends the
question again, at most twice, before it reports the failure.

Security in the card: `securitySchemes` (apiKey, http bearer or basic, oauth2,
openIdConnect, mtls) plus `securityRequirements`, optionally per skill. Identity,
delegation and data classification are not part of the protocol.

Spec: https://github.com/a2aproject/A2A (v1.0.1, 2026-05-28).
