# Main

# Health Tracker

A Django app for keeping a daily log of steps, water, sleep, habits, and
goals — with reminders that know when to stay quiet. Runs on SQLite with
zero setup for local development.

## Features

**Health logging**
- Daily log of steps, water (ml), sleep (hours), and resting heart rate.
- Personalized daily targets for steps/water/sleep, derived from your age
  and weight where available, with sensible adult defaults otherwise
  (`health/recommendations.py`). These are general wellness guidelines, not
  medical advice.
- In-browser step counter using the device accelerometer (best-effort;
  needs a phone with motion sensors and a permission grant), and a
  quick-add water logger.

**Habits**
- Daily habits with a completion streak.

**Goals**
- Manual goals (title, target, current value, deadline).
- **Auto-tracked goals**: link a steps/water/sleep goal to your daily logs,
  or a weight goal to your profile, and its progress updates itself instead
  of needing manual entry. Turning this on immediately syncs the goal from
  your latest data; turning it off (or choosing the `custom` category)
  hands control back to manual updates.

**Reminders**
- One-off or repeating (hourly/daily/weekly) reminders, delivered by email
  via a management command you run on a schedule.
- **Quiet hours**: set a start/end time on your profile and hourly
  reminders go silent during that window instead of pinging overnight.
  A skipped reminder still reschedules itself, so you get one reminder
  once quiet hours end rather than a pile-up of missed pings.
- **Skip if goal met**: link a reminder to a metric (steps/water/sleep) and
  it won't send once you've already hit today's target for that metric.

**Dashboard**
- At-a-glance view of today's steps (as a ring), water, sleep, and habit
  completion.

**API**
- A REST API (Django REST Framework) covering health logs, habits, habit
  logs, goals, and reminders, under `/api/`. Mirrors the same validation
  rules as the web UI (e.g. an auto-tracked goal's `current_value` can't be
  overwritten directly through the API either).

## Requirements

- Python 3.11+
- Django 6.1
- Django REST Framework 3.18

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Then visit `http://127.0.0.1:8000/`, register an account, and fill in your
profile (date of birth, height, weight) to get personalized health targets.

## Sending reminders

Reminders don't send themselves — a scheduler needs to call:

```bash
python manage.py send_due_reminders
```

periodically (e.g. every 5 minutes via cron, Task Scheduler, or your
hosting platform's scheduled-job feature). With the default console email
backend this just prints emails to the terminal running the dev server;
point `MAILERS['default']` in `config/settings.py` at a real backend (SMTP,
etc.) to send actual email.

## Project layout

```
accounts/    user profiles — bio, height/weight, quiet hours
health/      daily logs, recommended targets, step/water tracking endpoints
habits/      daily habits and completion streaks
goals/       manual and auto-tracked goals
reminders/   one-off/repeating reminders, quiet hours + goal-aware skipping
dashboard/   the at-a-glance home page
api/         Django REST Framework endpoints for the apps above
config/      Django project settings, root URLconf
```

Each app owns its own `models.py`, `views.py`, `forms.py`, `urls.py`, and
`tests.py`. Templates live centrally under `templates/<app_name>/`, and
static assets under `static/css/` and `static/js/`.

## Running tests

```bash
python manage.py test
```

## Configuration notes

- **Database**: SQLite by default (`db.sqlite3`, zero setup). Set a
  `DB_NAME` environment variable (plus `DB_USER`, `DB_PASSWORD`, `DB_HOST`,
  `DB_PORT`) to switch to PostgreSQL instead.
- **Time zone**: stored and processed in UTC; quiet hours and "today's"
  log entries are evaluated in the server's local time via Django's
  timezone utilities.
- **Auth**: Django's built-in session auth for the web app; DRF's session
  authentication for the API (so logging into the site also authenticates
  API requests from the same browser).
