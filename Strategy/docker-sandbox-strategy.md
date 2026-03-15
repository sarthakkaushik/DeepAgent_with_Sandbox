# Self-Hosted Docker Sandbox Strategy

## Goal

Build a self-hosted alternative to E2B where Python code runs inside isolated Docker containers that are created and managed by your own service.

The main design question is whether sandboxes are:

- one-shot per request
- long-lived per session

## Recommended Starting Point

Start with **one-shot container per request**.

Why:

- simpler architecture
- easier failure recovery
- easier concurrency
- cleaner isolation
- no stale session complexity

This is the best fit if the main job is deterministic calculation and code execution.

## High-Level Architecture

### 1. Agent layer

The Deep Agent keeps the same tool contract:

- code
- optional files
- optional session id
- optional reset flag

### 2. Sandbox API

A small service, usually FastAPI, exposes endpoints such as:

- `POST /execute`
- `POST /sessions`
- `POST /sessions/{id}/execute`
- `POST /sessions/{id}/files`
- `DELETE /sessions/{id}`

The agent tool talks to this API, not to Docker directly.

### 3. Container runtime

The API uses Docker, Kubernetes, ECS, or another runtime to start isolated Python containers.

### 4. Storage

Use storage for:

- uploaded inputs
- output artifacts
- logs

For an MVP, local disk is acceptable.

For production, object storage such as S3 or MinIO is cleaner.

### 5. Metadata and locking

Use Redis or Postgres to track:

- sandbox/session status
- container id
- last heartbeat
- request ownership
- per-session locks

## One-Shot Mode

### Flow

1. Receive code and files.
2. Create a fresh container.
3. Copy files into the container.
4. Run Python with timeout and resource limits.
5. Capture stdout, stderr, result, and errors.
6. Destroy the container.

### Why this is attractive

- no session reuse bugs
- every request starts clean
- concurrency is straightforward
- retries are simpler because state does not need to be preserved

## Session Mode

### Flow

1. Create a sandbox and return `session_id`.
2. Reuse the same container across calls.
3. Keep memory and filesystem state alive until timeout or reset.

### Why this is harder

You now need to manage:

- session expiry
- stale handles
- session cleanup
- locking
- state loss on crash

This is closer to notebook semantics, but also much more operationally complex.

## Failure Handling

### Container crashes

Handling:

- mark the sandbox unhealthy
- destroy it
- retry once in a fresh container if the request is stateless and safe to replay

### Infinite loop or hanging code

Handling:

- per-execution timeout
- kill the process or whole container
- return structured timeout error

### Worker host goes down

Handling:

- store sandbox metadata outside the worker
- detect dead container on next request
- recreate sandbox if needed

### Same session receives concurrent requests

Handling:

- allow only one active execution per session
- use a per-session lock
- either queue the second request or return a busy error

## Concurrency Model

### One-shot mode

Each request gets its own container.

This is the simplest concurrency story:

- requests are isolated
- horizontal scaling is natural
- no shared in-memory state between requests

### Session mode

Concurrency must be handled carefully.

Recommended rule:

- one session can have only one active execution at a time

This avoids race conditions in shared Python state and shared files.

## Recovery Strategy

Every request should go through a sandbox manager that:

1. resolves the target sandbox
2. checks whether it is healthy
3. recreates it if necessary
4. retries once when the failure is clearly a dead sandbox problem

This is the self-hosted equivalent of stale-sandbox retry logic in the E2B wrapper.

## Security Baseline

Minimum production baseline:

- run as non-root
- no privileged containers
- no Docker socket exposed to the sandbox
- CPU, memory, process, and disk limits
- timeout on every execution
- network restrictions when possible
- aggressive cleanup of expired containers

For stronger isolation later:

- gVisor
- Firecracker
- hardened Kubernetes runtime classes

## Recommended Product Path

### Phase 1: MVP

- FastAPI service
- one-shot container per request
- file upload support
- structured JSON result
- timeout and resource limits

### Phase 2: operational hardening

- persistent logs
- metrics
- queueing
- autoscaling
- Redis or Postgres metadata

### Phase 3: optional session mode

Only add this if you truly need persistent notebook-like state between calls.

## Main Tradeoff

Self-hosting gives you more control than E2B, but you now own:

- sandbox lifecycle
- security hardening
- concurrency
- cleanup
- observability
- recovery logic

## Recommended Default

For this use case, the best initial architecture is:

- agent tool -> sandbox API -> one-shot Docker container

That is the smallest design that is still maintainable and production-friendly.
