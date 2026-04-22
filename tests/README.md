# Test Bootstrap

The first TDD slice intentionally starts narrow:

- domain models
- final action schema
- backend API request/response schemas
- backend WebSocket event schemas

The fake data in `tests/fixtures/sample_data.py` is the canonical initial test corpus.

It is intentionally small:

- one current track
- one queued next track
- one transcript segment
- one playback `near_end` event
- one radio continuation action
- one favorite player action

This is enough to start backend-first TDD without inventing a larger fake world too early.
