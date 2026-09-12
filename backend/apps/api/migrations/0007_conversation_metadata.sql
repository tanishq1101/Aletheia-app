-- Sprint 5: conversations.
--
-- The tables themselves landed in 0001; nothing had written to them because
-- answering was stateless. Persisting an answer needs somewhere to keep the
-- facts that make it auditable — whether the evidence was sufficient, which
-- model produced it, and how many candidates were considered. Those belong to
-- the message, not to any single citation.

ALTER TABLE messages
    ADD COLUMN metadata JSONB;

-- Every read is "the messages in this conversation, oldest first".
CREATE INDEX IF NOT EXISTS messages_conversation_created_idx
    ON messages (conversation_id, created_at);

CREATE INDEX IF NOT EXISTS conversations_project_created_idx
    ON conversations (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS citations_message_idx
    ON citations (message_id);
