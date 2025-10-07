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
- **Database**: PostgreSQL (production) / SQLite (development)
- **Authentication**: JWT (Simple JWT 5.5.1)
- **API Format**: JSON

## Project Structure

```
jobApp/
├── apps/
│   ├── accounts/     # User authentication and management
│   ├── companies/    # Company profiles and business streams
│   ├── seekers/      # Job seeker profiles, education, experience, skills
│   └── jobs/         # Job postings, applications, and requirements
├── jobApp/           # Django project settings
└── requirements.txt  # Dependencies
```

## Quick Start

### Prerequisites

- Python 3.8+
- PostgreSQL 12+ (optional for development)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd jobApp
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   
   Create a `.env` file in the project root:
   ```bash
   # Database
   DB_NAME=jobboard_db
   DB_USER=your_username
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432
   
   # Django
   SECRET_KEY=your-secret-key-here
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   ```

5. **Run migrations**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

6. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start development server**
   ```bash
   python manage.py runserver
   ```

The API will be available at: `http://localhost:8000/api/v1/`

## API Documentation

📖 **Complete API documentation available in [API_DOCUMENTATION.md](API_DOCUMENTATION.md)**

### Postman Collections

Import the provided Postman collections for easy API testing:
- `Accounts API.postman_collection.json` - Authentication and user management
- `Companies API.postman_collection.json` - Company profiles and business streams
- `Jobs API.postman_collection.json` - Job postings and applications
- `Seekers API.postman_collection.json` - Seeker profiles, education, experience, skills

## Security

- JWT-based authentication
- Custom permission classes for resource access control
- Password validation and hashing
- CORS configuration
- Token blacklisting on logout

See [SECURITY.md](SECURITY.md) for detailed security implementation.

## License

[Add your license here]

## Contact

[Add your contact information here]