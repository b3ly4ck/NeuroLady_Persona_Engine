# Chat context-assembly template (v1)

Versioned prompt asset for the chat runner (architecture.md §4.2). The Conversation Orchestrator
(F-002) builds the `messages` array sent to `POST /v1/chat/completions` from these parts, in this
**priority order** (highest priority is never trimmed first):

1. **System prompt — the persona** (`role: "system"`): identity (name, profession, age, locale),
   current-era characteristics, Big Five (`PERSONA.big_five`), communication style
   (`PERSONA.comm_settings_json`), and today's plan/mood when available. Hard rule baked in here:
   she never reveals she is an AI/bot/model and never drops into assistant register
   (F-002 FR-002-08 / NFR-002-10).
2. **Relevant persona biography layers** (system context): semantically retrieved from memory
   (F-004) for the current message, at the right scope.
3. **User memory** (system context): categorized structured `USER_FACT`s + semantically retrieved
   past statements for **this user only** (F-004; per-user isolation).
4. **Relationship summary** (system context): the `(user, persona)` state that colors tone
   (F-005).
5. **Recent raw conversation history** (`role: "user"|"assistant"` turns): the last N messages of
   the live dialogue passed through **verbatim** — a hard requirement (F-002 FR-002-04). This block
   is retained even when older/optional context is trimmed to fit `CHAT_N_CTX`.
6. **The current user message** (`role: "user"`).

Until F-004/F-005 are wired, the Orchestrator assembles only (1) + (5) + (6) — persona system
prompt plus recent raw history plus the new message. That is the thin F-002 vertical slice; layers
2–4 are added as those features land, without changing this contract.

Decoding (temperature, top_p, etc.) comes from the persona's `comm_settings_json`; the runner
exposes them as standard OpenAI request fields.
