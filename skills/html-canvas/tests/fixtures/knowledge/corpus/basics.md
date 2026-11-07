# Basics of processing

## Latency

Latency is the time between request and response. It is measured at the client, not at the server.

When the queue grows, latency rises, even if every single job is handled just as fast.

## Queue

A queue collects jobs until a worker is free. A long queue is an early warning sign.
