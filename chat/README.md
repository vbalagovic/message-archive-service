# Chat BFF

Tiny FastAPI backend-for-frontend that:

1. Serves the static UI at `/`.
2. Streams chat completions from Ollama via SSE.
3. Persists every user/AI message to the archive service.

Not part of the archive's deployment — it lives in its own image and only spins
up when you run with the `llm` Docker Compose profile (`make llm-up`).
