## Overview
This API provides endpoints for managing a job application platform where employers can post jobs and freelancers can apply for them.

## Models

### `User`
Custom user model with two types: Employer and Freelancer
- UUID-based primary key
- Email authentication
- Required fields: username, first_name, last_name, user_type

### `Job`
Job posting model
- UUID-based primary key
- Fields: title, description, category, salary_range
- Status options: OPEN, CLOSED
- Associated with employer
- Timestamps for creation and updates

### `JobApplication`
Job application model
- UUID-based primary key
- Links freelancer and job
- Includes cover letter
- Status options: PENDING, ACCEPTED, REJECTED
- Timestamp for application
- Unique constraint: one application per freelancer per job

## API Endpoints

### Authentication
All endpoints except registration require authentication.

### User Management

#### Base URL
```http
http://localhost:8000/api
```
#### Register New User
```http
POST /api/register/
```
- Permission: AllowAny
- Fields: email, username, password, first_name, last_name, user_type

#### List Users
```http
GET /api/users/
```
- Permission: IsAuthenticated
- Employers see freelancers only
- Freelancers see employers only
- Query params: user_type

### Jobs

#### List/Create Jobs
```http
GET /api/jobs/
POST /api/jobs/  # Employers only
```
- Search params: search (searches title, description, category)
- Create fields: title, description, category, salary_range, status

#### Retrieve/Update/Delete Job
```http
GET /api/jobs/{id}/
PUT /api/jobs/{id}/    # Employers only
PATCH /api/jobs/{id}/  # Employers only
DELETE /api/jobs/{id}/ # Employers only
```

### Job Applications

#### List/Create Applications
```http
GET /api/applications/
POST /api/applications/  # Freelancers only
```
- Employers see applications for their jobs
- Freelancers see their own applications
- Create requires: job_id, cover_letter

#### Update Application Status
```http
PATCH /api/applications/{id}/  # Employers only
```
- Status options: ACCEPTED, REJECTED
- Field: status
- Only job owner can update status

## Permission Classes

### `IsEmployerOrReadOnly`
- Allows read access to all authenticated users
- Restricts write operations to employers only

## Models Serialization

### `JobSerializer`
- Includes employer username (read-only)
- Validates job status

### `JobApplicationSerializer`
- Includes freelancer username and job ID (read-only)
- Handles application status

### `UserSerializer`
- Handles password hashing
- Excludes password from responses
- Validates user type

## Database Configuration
- PostgreSQL database
- Environment variables required:
	```json
	DB_NAME=your_database_name
	DB_USER=your_username
	DB_PASSWORD=your_password
	DB_HOST=localhost
	DB_PORT=5432
	```

## Setup
1. Create virtual environment
2. Install dependencies:
```bash
pip install -r requirements.txt
```
1. Copy `.env.example` to `.env` and configure
2. Run migrations:
```bash
python manage.py makemigrations
python manage.py migrate
```

## Authentication
Uses Django REST Framework's built-in authentication:
- Basic Authentication

All endpoints except `registration` require authentication headers.