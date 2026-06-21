-- SmartSaver v2.0 — Supabase schema
-- Run this in the Supabase SQL editor (Project → SQL Editor → New query).

-- 1. Enable pgvector
create extension if not exists vector;

-- 2. Items table
--    - url is the primary key (same dedup logic as ChromaDB)
--    - embedding is 768-dim (Gemini text-embedding-004)
--    - all metadata columns mirror the ChromaDB flat-dict format so the
--      rest of the codebase (orchestrator, iOS app) needs zero changes
create table if not exists public.items (
  url                    text          primary key,
  document               text          not null default '',
  embedding              vector(768),                         -- null on placeholders
  source_type            text          not null default 'article',
  title                  text          not null default '',
  category               text          not null default '',
  is_uncertain           boolean       not null default false,
  alternative_categories text          not null default '',   -- pipe-joined list
  summary                text          not null default '',
  key_insights           text          not null default '[]', -- JSON array
  price                  text          not null default '',
  location               text          not null default '',
  technologies           text          not null default '',   -- pipe-joined list
  entities_json          text          not null default '{}', -- JSON object
  status                 text          not null default 'processing',
  ingested_at            text          not null default '',
  created_at             bigint        not null default 0
);

-- 3. HNSW index for fast approximate cosine similarity search
create index if not exists items_embedding_idx
  on public.items using hnsw (embedding vector_cosine_ops);

-- 4. Row Level Security — enable + allow all (personal project, no auth yet)
alter table public.items enable row level security;

create policy "allow_all" on public.items
  for all using (true) with check (true);

-- 5. Semantic search function
--    Called by Python as: supabase.rpc("match_items", {...}).execute()
--    filter_category is optional — pass null to search across all categories.
create or replace function match_items(
  query_embedding  vector(768),
  match_count      int            default 5,
  filter_category  text           default null
)
returns table (
  url                    text,
  document               text,
  distance               double precision,
  source_type            text,
  title                  text,
  category               text,
  is_uncertain           boolean,
  alternative_categories text,
  summary                text,
  key_insights           text,
  price                  text,
  location               text,
  technologies           text,
  entities_json          text,
  status                 text,
  ingested_at            text,
  created_at             bigint
)
language sql stable
as $$
  select
    i.url,
    i.document,
    (i.embedding <=> query_embedding) as distance,
    i.source_type,
    i.title,
    i.category,
    i.is_uncertain,
    i.alternative_categories,
    i.summary,
    i.key_insights,
    i.price,
    i.location,
    i.technologies,
    i.entities_json,
    i.status,
    i.ingested_at,
    i.created_at
  from public.items i
  where
    i.embedding is not null
    and (filter_category is null or i.category = filter_category)
  order by i.embedding <=> query_embedding
  limit match_count;
$$;

grant execute on function match_items to anon, authenticated;
