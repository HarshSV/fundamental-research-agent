-- Ask Navrist persistent chat memory. There is no per-user login (single
-- shared SITE_PASSWORD, see auth.py) so history is keyed by a client-generated
-- anonymous session_id (stored in the browser's localStorage) rather than a
-- real user id. Run once in Supabase's SQL Editor, same as 001_schema.sql.
-- Safe to re-run (IF NOT EXISTS).

create table if not exists chat_messages (
    id               bigint generated always as identity primary key,
    session_id       text not null,
    role             text not null,           -- 'user' | 'assistant'
    content          text not null,
    symbol           text,                    -- company on screen when the message was sent, if any
    created_at       timestamptz not null default now()
);
create index if not exists idx_chat_messages_session on chat_messages(session_id, created_at desc);

alter table chat_messages enable row level security;
