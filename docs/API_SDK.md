# AutumnGenLogin local API / Python SDK (development)

The API is **off by default**, binds only to 127.0.0.1, uses a fresh bearer token per application launch and implements a native AutumnGenLogin `/v1` contract. It is **not compatible with the proprietary GenLogin API**. No cookies, profile user-data folders or OS keyring credentials are exposed by the profile-list endpoint.

## Setup

1. Start the Python development application with `python main.py`.
2. Click **API: OFF** to enable its local server. Obtain the displayed bearer token and keep it private.
3. From the same machine and the same Python environment:

```python
from autumn_genlogin.client import AutumnAPIClient, LocalAPIError

# Insert the current, private local API token from the running GUI.
client = AutumnAPIClient(token="COPY_FRESH_TOKEN_FROM_APP")
print(client.health())
print(client.profiles())

# Open a disposable local test profile; profile_id must be a real UUID.
# profile_id = client.profiles()[0]["id"]
# client.open_profile(profile_id)
# client.run_steps(profile_id, [{"action": "goto", "url": "https://example.com"}])
# IMPORTANT: HTTP 202 means accepted, not executed to completion.
# print(client.latest_run(profile_id))  # may expire after 15 min or after auto-close
```

No package upload or new dependency is necessary. The client uses Python standard-library HTTP, validates workflow JSON/graphs before sending requests, and does not permit external addresses, proxies, URL redirects or forwarding the bearer token to another host.

## Available methods

- `health()`, `profiles()`, `open_profile(id)`, `stop_profile(id)`
- `run_steps(id, steps)`, `run_graph(id, graph)`, `cancel_run(id)`, `latest_run(id)`
- `start_recording(id)`, `stop_recording(id)`, `recorded_steps(id)`
- `schedules()`, `schedule_history(job_id=None, limit=50)`
- `start_batch(profile_ids, workflow, max_parallel=3)`, `batches(limit=20)`, `batch(batch_id)`, `cancel_batch(batch_id)`

The client never follows HTTP 30x redirects or consults environment-defined HTTP proxies. It rejects non-loopback URLs and malformed IDs before sending requests. The token is excluded from the client object's debug representation.

## Status, errors and completion

An accepted request is not proof that a browser task finished or that a website action succeeded. An API response of `{"accepted": true}` means only that a request was accepted. The client raises `LocalAPIError` with a `status` for failed HTTP responses:

- 400: invalid input, workflow or ID.
- 401: absent or incorrect bearer token.
- 404: missing profile, batch or run result.
- 409: browser/resource busy or action cannot start.
- 503: local database/connection temporarily unavailable.
- 502: unexpected/unsafe server response or redirect.

Run outcomes are generally `queued`, `running`, `succeeded`, `cancelled`, `failed`. Latest workflow result is process memory, not a durable run log. The Schedule journal stores only sanitized status metadata and the Batch runner keeps only recent in-memory summaries.

## Security boundary and non-goals

- Do not print, save, embed in code, send to remote services or commit the bearer token to Git.
- This API is not a security boundary against malware or another process running under the same Windows user.
- Browser sessions and extracted page text are sensitive. A caller with the token can run workflows and may retrieve extracted text.
- The SDK does not offer GenLogin protocol parity, Titan engine support, anti-Sybil guarantees, account bypassing, or arbitrary script execution.
- The entire application remains a **development prototype** with a blocked EXE release until independent parity and production security gates pass.
