# AttendSense: Intelligent AI Attendance & Analytics Dashboard

Take classroom attendance from **one photo** or **one voice roll-call**, review it, save it, and track every
student against the attendance target.

- **Teachers** create subjects, share a QR join link, take attendance with face or voice recognition (or by hand),
  correct past classes, and analyse trends, defaulters and weekday patterns. Everything exports to Excel.
- **Students** sign in with roll number + face + a head-turn liveness check, join subjects by code or QR, and see
  exactly how many classes they need to attend (or can still miss) to stay above target.

Built with Python 3.11, Streamlit, dlib, Resemblyzer, Supabase (Postgres) and Altair. The landing page is
static HTML on Vercel.

**Designed and built by [Sourabh Singh](https://github.com/Sourabh16).**

---

## Repository layout

```
app/                      Streamlit application (deployed to Streamlit Community Cloud)
  app.py                  entry point + router
  requirements.txt        pinned runtime dependencies
  packages.txt            apt packages for Streamlit Cloud
  .streamlit/             theme config + secrets template
  src/
    config.py             every threshold and setting in one place
    services.py           cached ML models + recognition workflows
    core/                 pure logic, no Streamlit, fully unit-tested
      face.py             detection, embeddings, matching, liveness geometry, drawing
      voice.py            speaker embeddings, silence splitting, matching
      attendance.py       merge results into an editable draft and back
      analytics.py        percentages, 75% calculator, summaries, Excel export
      security.py         bcrypt, validation, join codes, login throttling
    db/                   data access
      base.py             Repository interface (the contract)
      supabase_repo.py    production backend
      sqlite_repo.py      local/offline backend, same schema
    screens/              UI: home, teacher/*, student/*
    ui/components.py      theme + shared widgets
supabase/schema.sql       tables, view, atomic save function, row-level security
landing/                  static marketing site (deployed to Vercel)
scripts/seed_demo.py      generates a realistic demo semester
tests/                    55 pytest tests (logic, database contract, headless UI flows)
docs/                     project report (Word)
```

## Run it locally (no accounts needed)

```bash
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
python scripts/seed_demo.py --reset      # optional: demo teacher "demo" / "demo1234"
streamlit run app/app.py
```

Without Supabase secrets the app uses a local SQLite database at `app/local_data/attendsense.db` and shows a
banner saying so. Run the tests with `pytest` and the linter with `ruff check app tests scripts`.

## Deploy

### 1. Supabase (database)
1. Create a free project at [supabase.com](https://supabase.com). Choose the Mumbai region (closest to India).
2. **SQL Editor → New query** → paste all of `supabase/schema.sql` → **Run**.
3. **Project Settings → API Keys**: copy the project URL and a **secret** key (`sb_secret_…`, or the legacy
   `service_role` key). Never use the publishable/anon key: the schema deliberately gives it no access.

### 2. Streamlit Community Cloud (app)
1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub → **Create app** → this repository.
2. Main file path: `app/app.py`. **Advanced settings → Python 3.11**.
3. Secrets (same format as `app/.streamlit/secrets.toml.example`):
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "sb_secret_..."
   APP_URL = "https://<your-app>.streamlit.app"
   ```
4. Deploy. The first build takes several minutes (dlib, PyTorch CPU).

### 3. Vercel (landing page)
1. Set the app URL in `landing/config.js`.
2. [vercel.com](https://vercel.com) → **Add New → Project** → import this repository →
   **Root Directory: `landing`**, Framework preset **Other**, no build command → **Deploy**.

## How recognition works

| Step | Face | Voice |
|---|---|---|
| Enrollment | 3 selfies → three 128-d dlib embeddings, checked to be the same person and not already registered | ~5 s clip → one 256-d Resemblyzer embedding |
| Candidates | only students enrolled in the selected subject | same |
| Matching | Euclidean distance to each student's closest sample; one-to-one greedy assignment, most confident first; threshold 0.50 | cosine similarity per spoken segment; threshold 0.72 |
| Uncertain cases | runner-up within 0.04 → "needs review", not auto-marked | runner-up within 0.03 → ignored |
| Output | annotated photo + editable review table | segment table + editable review table |

Student sign-in is **1:1 verification**: roll number, then a frontal photo, then a head-turned photo. Both photos
must match that student, and the nose-position offset must change by at least 0.15 between them.

## Design highlights

| Area | How AttendSense does it |
|---|---|
| Face enrollment | 3 photos per student, checked to be the same person and not already registered |
| Matching | closed set: only students enrolled in the subject, no training step |
| Crowded photos | one-to-one assignment, so a student can't be counted twice; look-alikes flagged for review |
| Student login | roll no + 1:1 face check + head-turn liveness, rate-limited |
| Join codes | random 6-character code, pausable and regenerable |
| Time | stored in UTC, shown in IST |
| Classes | explicit `sessions` table; each class saved by one atomic database function |
| Review | editable before saving; past classes can be corrected |
| Analytics | KPIs, trend, heatmap, weekday profile, defaulters, 75% calculator, Excel/CSV |
| Security | RLS on all tables, secret key server-side only, bcrypt, validation, HTML escaping |
| Privacy | consent, templates instead of photos, re-enroll, delete account |
| Engineering | 55 tests, CI, pinned dependencies, SQLite fallback, demo data generator |
| Landing | static site on Vercel, no server needed |

## Limitations (honest)

- Liveness is a head-turn challenge, not anti-spoofing hardware: a video replayed on a phone could pass.
- dlib's HOG detector misses very small or strongly turned faces. Take 2-3 photos from different corners for
  large rooms.
- Voice roll-call works best in a quiet room with one speaker at a time.
- Thresholds were chosen from dlib's and Resemblyzer's published operating points, not tuned on your classroom.
  The strictness sliders exist for that reason.
- The repository's student list and attendance live in one Supabase project. Multi-institution tenancy is out
  of scope.
