-- AttendSense database schema for Supabase (Postgres 15+).
-- Run once in Supabase Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Safe to re-run: every statement is idempotent.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists teachers (
    teacher_id    bigint generated always as identity primary key,
    username      text not null unique check (username = lower(username)),
    name          text not null,
    password_hash text not null,
    created_at    timestamptz not null default now()
);

create table if not exists students (
    student_id      bigint generated always as identity primary key,
    roll_no         text not null unique check (roll_no = upper(roll_no)),
    name            text not null,
    -- list of 128-d dlib embeddings, one per enrollment photo
    face_embeddings jsonb not null default '[]'::jsonb,
    -- 256-d Resemblyzer embedding, null when the student skipped voice
    voice_embedding jsonb,
    consent_at      timestamptz not null,
    created_at      timestamptz not null default now()
);

create table if not exists subjects (
    subject_id   bigint generated always as identity primary key,
    teacher_id   bigint not null references teachers(teacher_id) on delete cascade,
    subject_code text not null,
    name         text not null,
    section      text not null default '',
    -- random code students type or scan; separate from subject_code so two
    -- teachers can both teach "CS101" without colliding
    join_code    text not null unique,
    join_open    boolean not null default true,
    target_pct   numeric(5,2) not null default 75 check (target_pct between 0 and 100),
    created_at   timestamptz not null default now(),
    unique (teacher_id, subject_code, section)
);

create table if not exists enrollments (
    subject_id  bigint not null references subjects(subject_id) on delete cascade,
    student_id  bigint not null references students(student_id) on delete cascade,
    enrolled_at timestamptz not null default now(),
    primary key (subject_id, student_id)
);

-- One row per class meeting. Grouping rows by timestamp would be fragile;
-- an explicit session makes counting classes and editing a past class exact.
create table if not exists sessions (
    session_id bigint generated always as identity primary key,
    subject_id bigint not null references subjects(subject_id) on delete cascade,
    started_at timestamptz not null default now(),
    method     text not null check (method in ('face', 'voice', 'manual', 'mixed'))
);

create table if not exists attendance (
    session_id bigint not null references sessions(session_id) on delete cascade,
    student_id bigint not null references students(student_id) on delete cascade,
    status     text not null check (status in ('present', 'absent')),
    source     text not null check (source in ('face', 'voice', 'manual')),
    confidence real,
    edited     boolean not null default false,
    primary key (session_id, student_id)
);

create index if not exists idx_subjects_teacher on subjects(teacher_id);
create index if not exists idx_enrollments_student on enrollments(student_id);
create index if not exists idx_sessions_subject on sessions(subject_id, started_at);
create index if not exists idx_attendance_student on attendance(student_id);

-- ---------------------------------------------------------------------------
-- Flat view used by every dashboard and export.
-- security_invoker = true makes the view obey the caller's RLS, so it cannot
-- be used to read around the policies below.
-- ---------------------------------------------------------------------------

create or replace view attendance_records with (security_invoker = true) as
select
    a.session_id,
    se.started_at,
    se.method,
    su.subject_id,
    su.subject_code,
    su.name    as subject_name,
    su.section,
    su.teacher_id,
    st.student_id,
    st.name    as student_name,
    st.roll_no,
    a.status,
    a.source,
    a.confidence
from attendance a
join sessions se on se.session_id = a.session_id
join subjects su on su.subject_id = se.subject_id
join students st on st.student_id = a.student_id;

-- ---------------------------------------------------------------------------
-- Save a whole class session atomically: either the session and every
-- attendance row are written, or nothing is.
-- rows: [{"student_id": 1, "status": "present", "source": "face", "confidence": 0.8}, ...]
-- ---------------------------------------------------------------------------

create or replace function record_session(p_subject_id bigint, p_method text, p_rows jsonb)
returns bigint
language plpgsql
as $$
declare
    v_session_id bigint;
begin
    insert into sessions(subject_id, method)
    values (p_subject_id, p_method)
    returning session_id into v_session_id;

    insert into attendance(session_id, student_id, status, source, confidence)
    select v_session_id,
           (r->>'student_id')::bigint,
           r->>'status',
           r->>'source',
           nullif(r->>'confidence', '')::real
    from jsonb_array_elements(p_rows) as r;

    return v_session_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- Security
-- The Streamlit server talks to Supabase with the *secret* (service_role) key,
-- which bypasses RLS. Enabling RLS with no policies means the public anon key
-- can read or write nothing, so leaking it exposes no biometric data.
-- ---------------------------------------------------------------------------

alter table teachers    enable row level security;
alter table students    enable row level security;
alter table subjects    enable row level security;
alter table enrollments enable row level security;
alter table sessions    enable row level security;
alter table attendance  enable row level security;

revoke all on function record_session(bigint, text, jsonb) from public, anon, authenticated;
grant execute on function record_session(bigint, text, jsonb) to service_role;
