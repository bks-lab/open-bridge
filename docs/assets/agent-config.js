// open-bridge floating chat widget — deployment configuration.
//
// This is the SINGLE place that names the agent's public endpoint. It sets a
// global the widget (assets/agent-widget.js) reads. If this value is blank,
// removed, or this file is absent, the widget stays fully dormant and renders
// nothing — so a fork without its own A2A agent backend shows no chat bubble.
//
// To enable the widget on your own fork: point this at YOUR A2A agent's public
// base URL (the origin that serves /.well-known/agent-card.json). No other file
// in the site names a host.
window.OB_AGENT_ENDPOINT = "https://openbridge.bks-lab.com";
