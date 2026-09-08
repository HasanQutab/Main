# Health Tracker



A Django app for tracking daily steps, water, sleep, habits, and goals, with smart reminders that know when to stay quiet. Uses SQLite by default for simple local development.

## Features

**Health logging**

* Daily tracking of steps, water (ml), sleep (hours), and resting heart rate.
* Personalized step, water, and sleep targets based on age and weight, with sensible defaults when information is unavailable.
* Browser-based step counter using the device accelerometer, plus quick-add water logging.

**Habits**

* Daily habits with completion tracking and streaks.

**Goals**

* Manual goals with a title, target, current value, and deadline.
* **Auto-tracked goals** that sync automatically with steps, water, sleep, or weight data.
* Automatically syncs the latest data when auto-tracking is enabled and returns to manual control when disabled.

**Reminders**

* One-off and repeating hourly, daily, or weekly email reminders.
* **Quiet hours** that silence hourly reminders during a configured time period without creating a backlog.
* **Skip if goal met** to automatically skip reminders when today's steps, water, or sleep target has been reached.

**Dashboard**

* Simple overview of today's steps, water, sleep, habits, and goal progress.

**API**

* REST API built with Django REST Framework under `/api/`.
* Supports health logs, habits, habit logs, goals, and reminders.
* Uses the same validation rules as the web application.

## Requirements

* Python 3.11+
* Django 6.1
* Django REST Framework 3.18

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`, register an account, and complete your profile to enable personalized targets.

## Sending reminders

Run the reminder command periodically:

```bash
python manage.py send_due_reminders
```

You can schedule it with cron, Task Scheduler, or your hosting provider. The default email backend prints messages to the terminal; configure `MAILERS['default']` in `config/settings.py` for real email delivery.

## Project layout

```text
accounts/    user profiles, height/weight, quiet hours
health/      daily logs, recommendations, step/water tracking
habits/      habits, completion tracking, streaks
goals/       manual and auto-tracked goals
reminders/   reminders, quiet hours, goal-aware skipping
dashboard/   main dashboard
api/         Django REST Framework endpoints
config/      Django settings and URL configuration
```

Each app contains its own `models.py`, `views.py`, `forms.py`, `urls.py`, and `tests.py`. Templates are stored under `templates/<app_name>/`, with CSS and JavaScript under `static/css/` and `static/js/`.

## Running tests

```bash
python manage.py test
```

## Configuration notes

* **Database:** SQLite by default (`db.sqlite3`). PostgreSQL can be configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`.
* **Time zone:** Uses Django's timezone utilities for logs, reminders, and quiet hours.
* **Auth:** Django session authentication for the web app and DRF session authentication for the API.
* **Health targets:** General wellness guidelines only, not medical advice.
