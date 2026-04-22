# Job Board API

A comprehensive REST API for a job board platform where companies can post jobs and job seekers can search and apply for positions.

## Features

- **User Management** - Authentication and authorization for job seekers and companies
- **Company Profiles** - Business information, industry categorization, and company images
- **Job Seeker Profiles** - Personal information, education, work experience, and skills
- **Job Postings** - Create, search, and filter job opportunities
- **Application System** - Apply for jobs and track application status

## Tech Stack

- **Framework**: Django 5.2.5 + Django REST Framework 3.16.1
- **Database**: PostgreSQL
- **Authentication**: JWT (Simple JWT 5.5.1)

## Project Structure

```
jobApp/
├── apps/
│   ├── accounts/     # User authentication and management
│   ├── companies/    # Company profiles and business streams
│   ├── seekers/      # Job seeker profiles, education, experience, skills
│   └── jobs/         # Job postings, applications, and requirements
├── jobApp/           # Django project settings
├── config.py         # Centralized env-var access (imported by settings)
└── pyproject.toml    # Dependencies (managed by uv)
```

## Quick Start

### Prerequisites

- Python 3.13.5+
- PostgreSQL 17+

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd jobApp
   ```

2. **Install dependencies with [uv](https://docs.astral.sh/uv/)**

   If you don't have uv installed yet, see the [install guide](https://docs.astral.sh/uv/getting-started/installation/).

   ```bash
   uv sync
   ```

   This reads `pyproject.toml` + `uv.lock`, provisions Python 3.13 (pinned in `.python-version`), creates `.venv/`, and installs all dependencies.

   Activate the venv or prefix commands with `uv run`:

   ```bash
   # Windows (PowerShell)
   .venv\Scripts\activate

   # macOS/Linux
   source .venv/bin/activate
   ```

3. **Set up environment variables**

   Create a `.env` file in the project root. All values in this file are read by `config.py` and injected into Django settings:

   ```bash
   # Database
   DB_NAME=your_db_name
   DB_USER=your_username
   DB_PASSWORD=your_password
   DB_HOST=your_db_host #by default: localhost
   DB_PORT=your_db_port #by default: 5432

   # Django
   SECRET_KEY=your-secret-key-here

   # Deployment
   DEBUG=true
   ALLOWED_HOSTS=localhost,127.0.0.1
   ADMIN_URL=admin/
   ```

   **Picking a settings module**

   The settings package exposes three environment modules:

   | Module | When used |
   | --- | --- |
   | `jobApp.settings.development` | Default for `manage.py` (except `test`). DEBUG=True, loose CORS, no HTTPS redirect. |
   | `jobApp.settings.production` | Default for `wsgi.py` / `asgi.py`. DEBUG=False, strict security, fail-fast assertions. |
   | `jobApp.settings.test` | Auto-picked when running `manage.py test`. Fast MD5 hasher, ALLOWED_HOSTS locked to `testserver`. |

   Override with `DJANGO_SETTINGS_MODULE`:

   ```bash
   DJANGO_SETTINGS_MODULE=jobApp.settings.production uv run python manage.py migrate
   ```

4. **Run migrations**
   ```bash
   uv run python manage.py makemigrations
   uv run python manage.py migrate
   ```

5. **Create superuser**
   ```bash
   uv run python manage.py createsuperuser
   ```

6. **Start development server**
   ```bash
   uv run python manage.py runserver
   ```

The API will be available at: `http://localhost:8000/api/v1/`

## API Documentation

📖 **Complete API documentation available in [API_DOCUMENTATION.md](API_DOCUMENTATION.md)**

### Postman Collections

Import the provided Postman collections for easy API testing:
- `Job Board API.postman_collection.json`

## API Conventions

### Pagination

All list endpoints return:

```json
{
  "count": 123,
  "next": "http://host/api/v1/jobs/job-posts/?page=2",
  "previous": null,
  "results": [/* items */]
}
```

Override the page size with `?page_size=N` (max 100).

### Search, filter, ordering (jobs)

- `?search=<term>` — matches job title, description, and company name
- `?ordering=-created_at` — sort; valid fields: `created_at`, `salary_max`, `salary_min`, `deadline_date`
- Filters: `job_type`, `company`, `salary_type`, `is_published`, `city`, `country`, `salary_min_gte`, `salary_max_lte`, `deadline_before`, `required_skill`

## Security

- JWT-based authentication
- Custom permission classes for resource access control
- Password validation and hashing
- CORS configuration