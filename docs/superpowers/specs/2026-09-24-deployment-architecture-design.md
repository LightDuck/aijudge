# Deployment Architecture for a Mobile App — Design

**Date:** 2026-09-24
**Status:** proposed (decision document: compares options, recommends one, and lists the decisions still needed)

## Problem

AIJudge is meant to reach users as a mobile app (APK) used by one person per install, asking about whatever cards
they like. Today everything runs on the developer's PC:

| Component | Today |
|---|---|
| Database | Postgres 16 + pgvector in Docker (`docker compose up -d db`), app database 8.7 MB with 10 cards |
| LLM | Qwen3-8B via local Ollama (`OllamaLLMClient`), about 5 GB |
| Embeddings | `OllamaEmbeddingClient` (CLI) or `OpenAIEmbeddingClient` (API service) |
| Card data | 10 seed cards; any other card is fetched from YGOPRODeck **at question time** and parsed, with one review-agent LLM call per effect |
| Service | FastAPI (`api/`, two stateless endpoints: `POST /questions`, `POST /questions/answer`) |
| UI | Web chat UI spec (`2026-09-11-frontend-chat-ui-design.md`), which covers local development only and defers production deployment |

None of the three local pieces (Postgres, Ollama with an 8B model, Docker) runs on a phone as-is. This document
decides where each piece should live.

## Facts that shape the decision

1. **The database is reference data, almost entirely read-only.** Cards, effects, `bullet_category`,
   `card_bulleted`, rulings and rulebook chunks are only *read* while answering. The one write at question time is the
   online lookup of a card not ingested yet (`tools.lookup_card` → `seed_card`). Pre-ingesting the whole card pool
   centrally (YGOPRODeck lists about 14,500 entries) removes that write entirely.
2. **Trustworthy data is produced centrally.** Hand review (the `card_bulleted` review; any future effect review)
   happens once, upstream, and reaches users as data, as `ingestion/data/card_bulleted.json` already does. A user
   never reviews anything.
3. **The LLM is the heavy part.** A typical question makes 2–3 LLM calls: `extraction` (no local match) or `clarify`
   (local match), then `loop` (the answer, up to 3 retries on malformed output), then `verify` (up to 2 retries). A
   first-time card lookup adds one `review_agent` call per effect. The current reliability machinery (confidence
   score, verification, retries) was built around an 8B model, and a smaller model would lean on it harder.
4. **The code's database coupling is small and contained.** There are 6 repo modules (`db/*_repo.py`, 25 SQL call
   sites), and 6 modules outside `db/` import them. The Postgres-only features in use are: the pgvector `<=>`
   operator (2 similarity queries: rulings, rulebook), `VECTOR(384)`, `gen_random_uuid()` (9 uses), `RETURNING`,
   `ILIKE`, a `~` regex, `lpad`, `to_regclass`, and three `DO $$` migration blocks.
5. **A secret can't be hidden inside an APK.** Any API key shipped in the app can be extracted. So calling a hosted LLM
   API from the phone needs a small server in between that holds the key, even if nothing else is hosted.

## Options

### Option A — Everything hosted (thin client)

The app is a UI that calls the existing FastAPI service. The server runs Postgres, the LLM and the API.

- **Runs on the phone:** UI only.
- **Runs on the server:** everything else, as today.
- **Work:** smallest code change. Production-harden `api/` (authentication, per-user rate limiting, HTTPS,
  deployment), host Postgres, and choose the LLM host (see Decisions). Keep or remove online ingest at question time.
- **Costs:** a server that is always on. The LLM is either a GPU machine running Ollama (fixed monthly cost) or a
  hosted API (cost per question, which grows with use).
- **Benefits:** fixes, reviews and new cards reach users instantly. There is one place to monitor, and the call logs
  (`logs/aijudge.jsonl`) could show which cards people ask about, if users consent.
- **Risks:** the app does nothing offline; availability and abuse are now the maintainer's problem; users'
  questions pass through the maintainer's server (privacy notice needed).

### Option B — Data on the device, LLM hosted (hybrid)

The app ships a SQLite copy of the reference data and downloads updates as new versions of that file. Only LLM
calls go over the network, through a small stateless proxy that holds the API key.

- **Runs on the phone:** UI, card matching, the KNOWN FACTS block, the rules engine, confidence scoring, SQLite
  lookups (with `sqlite-vec` for the two similarity queries).
- **Runs on the server:** an LLM proxy (authentication, rate limiting, forwarding to the chosen LLM), with no database.
- **Work:**
  1. A **central data pipeline** that ingests the whole card pool, runs the parser and checks, applies reviewed data,
     and outputs a versioned SQLite file. This replaces question-time ingestion.
  2. **Port the repos to SQLite:**
     - UUIDs generated in Python instead of `gen_random_uuid()`;
     - `ILIKE` → `LIKE` with `COLLATE NOCASE`;
     - the regex and `lpad` migration → a one-off data fix done in Python;
     - `<=>` → a `sqlite-vec` distance query;
     - the `DO $$` migration blocks aren't needed, because the file is rebuilt, not migrated.

     `RETURNING` and `ON CONFLICT` are supported by SQLite.
  3. Run the orchestration layer on the device, which depends on the app technology (see Decisions).
  4. The LLM proxy.
- **Costs:** LLM usage plus a very small proxy. No database server.
- **Benefits:** card data works offline, and the database costs nothing to run. Reviewed data ships the same way
  `card_bulleted` does. The server stores no user data, so it can be stateless and cheap.
- **Risks:**
  - The SQLite port is a second database dialect to keep working, unless Postgres is dropped entirely (see
    Decisions).
  - Data updates need a download channel.
  - The answer still needs network, so the app isn't fully offline.

### Option C — Everything on the device

SQLite as in B, plus a small LLM on the device (1–4B parameters, via llama.cpp or an Android on-device runtime).

- **Runs on the phone:** everything.
- **Work:** everything in Option B except the proxy, plus packaging an on-device model, which is a large download
  (hundreds of MB to several GB).
- **Costs:** none to run.
- **Benefits:** fully offline and private; no server at all.
- **Risks:**
  - **Answer quality is the unknown.** Nobody has measured how a 1–4B model does on this project's prompts (the
    `TOOL:`/`FINAL:` protocol, verification, chain and timing questions), and the 8B model already needs retries.
  - Battery use and speed on mid-range phones.
  - The app becomes very large.

## Comparison

| | A: All hosted | B: Hybrid | C: All on device |
|---|---|---|---|
| Works offline | No | Card data yes, answers no | Yes |
| Running cost | Server + LLM | LLM + tiny proxy | None |
| Code change | Small | Medium–large | Large |
| Answer quality | As today | As today | Unknown, probably lower |
| How updates reach users | Instantly | Data-file download | Data-file download + app updates |
| User data on a server | Questions and answers | Questions and answers, passed through | None |

## Recommendation

**Option B.** It matches what the project has become:
- **The data belongs in a file.** It's reviewed reference data built centrally, so it's shipped, not served.
- **Only the LLM needs real hardware.** That's the one part that genuinely does.
- **Question-time ingestion moves into a central pipeline.** That's the same place hand review happens, and it also
  removes the per-effect review-agent calls from the user's question path.

**Option C is worth measuring, not deciding blind.** The project has no evaluation harness yet: the `qa_test_cases`
table exists but is unused. A small set of questions with known correct answers, run against the 8B model and a few
small candidate models, would turn "probably lower quality" into a number. If a small model turns out good enough,
B's data pipeline carries straight over to C, because the data file is identical.

**Option A stays the fallback** if the SQLite port or on-device orchestration turns out too costly: it's the
quickest to ship, at the price of running a server.

## Suggested order of work (for Option B)

Each phase is useful even if the next one never happens:

1. **Evaluation harness.** Fill `qa_test_cases` and score answers. It's needed to compare LLMs for Option B, and to
   judge Option C.
2. **Central data pipeline.** Pre-ingest the card pool into Postgres with the parser and checks, and remove
   question-time ingestion from the answer path. This helps the current desktop setup too.
3. **SQLite export and port.** Build the data file from the pipeline and port the repos. Run the existing test suite
   against both databases, or against SQLite only if Postgres is retired.
4. **LLM proxy.** Authentication, rate limiting, and the chosen LLM provider.
5. **The app itself.** This is the frontend spec, extended beyond local development.

## Decisions needed from the maintainer

1. **App technology.** Native Android (Kotlin), a cross-platform framework, or a web app wrapped as an APK (the
   existing React/Vite plan inside a WebView). This decides where the Python orchestration runs: rewritten for the
   device, or behind the proxy (see below).
2. **Where the orchestration code runs in Option B.** The orchestration layer (matching, KNOWN FACTS, confidence,
   verification) is Python. On a Kotlin or web app it either has to be **rewritten for the device** or **run on the
   server next to the LLM**. The second choice makes the server hold the orchestration too, which moves Option B
   close to Option A for the logic, while the data still ships to the device. This is the largest unknown in the work
   estimate.
3. **LLM provider behind the proxy.** Self-hosted Ollama on a GPU server (fixed cost, current model) or a hosted API
   (cost per question, a different model, prompts need re-checking).
4. **Postgres after the port.** Keep it for development and the central pipeline, with SQLite only for shipping, or
   move everything to SQLite.
5. **Data update channel.** New data only with app updates, or downloadable separately.

## Out of scope

The UI design, the app store release process, accounts and payments, and localization.
