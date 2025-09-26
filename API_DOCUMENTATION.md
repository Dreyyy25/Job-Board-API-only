# Job Board API Documentation

## Base URL
```
http://localhost:8000/api/v1/
```

## Authentication
- **Basic Authentication** supported
- **Session Authentication** for web clients
- Most endpoints require authentication except registration and login

**Authentication Header:**
```http
Authorization: Basic <base64-encoded-credentials>
```

---

## 🔐 **Authentication Endpoints**

### Register New User
```http
POST /api/v1/accounts/register/
```

**Request Body:**
```json
{
    "user_type": "job_seeker",
    "email": "john.doe@example.com",
    "password": "securepass123",
    "date_of_birth": "1990-05-15",
    "contact_number": "+1234567890",
    "sex": "M"
}
```

**Response (201 Created):**
```json
{
    "message": "User created successfully",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "email": "john.doe@example.com"
}
```

### User Login
```http
POST /api/v1/accounts/login/
```

**Request Body:**
```json
{
    "email": "john.doe@example.com",
    "password": "securepass123"
}
```

**Response (200 OK):**
```json
{
    "message": "Login successful",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "email": "john.doe@example.com",
    "user_type": "job_seeker"
}
```

---

## 👤 **User Management**

### User Accounts
```http
GET    /api/v1/accounts/users/               # List all users
POST   /api/v1/accounts/users/               # Create user
GET    /api/v1/accounts/users/{id}/          # Get specific user
PUT    /api/v1/accounts/users/{id}/          # Update user
DELETE /api/v1/accounts/users/{id}/          # Delete user
```

**User Type Options:**
- `job_seeker`: For individuals looking for jobs
- `company`: For businesses posting jobs

**Note**: User types are now built-in choices rather than separate database records. Use the string values directly in requests.

---

## 👨‍💼 **Job Seekers Management**

### Seeker Profiles
```http
GET    /api/v1/seekers/profiles/             # List seeker profiles
POST   /api/v1/seekers/profiles/             # Create profile
GET    /api/v1/seekers/profiles/{id}/        # Get specific profile
PUT    /api/v1/seekers/profiles/{id}/        # Update profile
DELETE /api/v1/seekers/profiles/{id}/        # Delete profile
```

**Create Seeker Profile:**
```json
{
    "user_account": "123e4567-e89b-12d3-a456-426614174000",
    "first_name": "John",
    "last_name": "Doe",
    "contact_details": "Available for interviews on weekdays",
    "goals": "Seeking a full-time Python developer position",
    "resume_url": "https://example.com/resume.pdf"
}
```

### Education Records
```http
GET    /api/v1/seekers/education/            # List education records
POST   /api/v1/seekers/education/            # Add education
GET    /api/v1/seekers/education/{id}/       # Get specific education
PUT    /api/v1/seekers/education/{id}/       # Update education
DELETE /api/v1/seekers/education/{id}/       # Delete education
```

**Add Education:**
```json
{
    "user_account": "123e4567-e89b-12d3-a456-426614174000",
    "institute_university_name": "Harvard University",
    "degree_type": "Bachelor",
    "field_of_study": "Computer Science",
    "academic_details": "Focus on software engineering and algorithms",
    "percentage": 85.5,
    "start_date": "2016-09-01",
    "end_date": "2020-05-15",
    "is_current": false
}
```

### Experience Records
```http
GET    /api/v1/seekers/experience/           # List work experience
POST   /api/v1/seekers/experience/           # Add experience
GET    /api/v1/seekers/experience/{id}/      # Get specific experience
PUT    /api/v1/seekers/experience/{id}/      # Update experience
DELETE /api/v1/seekers/experience/{id}/      # Delete experience
```

**Add Experience:**
```json
{
    "user_account": "123e4567-e89b-12d3-a456-426614174000",
    "company_name": "Tech Solutions Inc",
    "position": "Junior Python Developer",
    "description": "Developed web applications using Django framework",
    "job_location_city": "New York",
    "job_location_country": "USA",
    "start_date": "2020-06-01",
    "end_date": "2022-12-31"
}
```

### Skills Management
```http
GET    /api/v1/seekers/skills/               # List all skills
POST   /api/v1/seekers/skills/               # Create new skill
GET    /api/v1/seekers/seeker-skills/        # List user skills with levels
POST   /api/v1/seekers/seeker-skills/        # Add skill to user
```

**Create Skill:**
```json
{
    "skill_name": "Python"
}
```

**Add User Skill:**
```json
{
    "user_account": "123e4567-e89b-12d3-a456-426614174000",
    "skill_set": "python-skill-uuid-here",
    "skill_level": "Advanced"
}
```

### Seeker Dashboard
```http
GET    /api/v1/seekers/dashboard/{user_id}/  # Get complete seeker data
```

**Response Example:**
```json
{
    "profile": {
        "user_account": "123e4567-e89b-12d3-a456-426614174000",
        "first_name": "John",
        "last_name": "Doe",
        "goals": "Seeking a full-time Python developer position"
    },
    "education": [
        {
            "id": "edu-uuid-here",
            "institute_university_name": "Harvard University",
            "degree_type": "Bachelor",
            "field_of_study": "Computer Science"
        }
    ],
    "experience": [
        {
            "id": "exp-uuid-here",
            "company_name": "Tech Solutions Inc",
            "position": "Junior Python Developer"
        }
    ],
    "skills": [
        {
            "skill_set": "python-skill-uuid",
            "skill_level": "Advanced"
        }
    ]
}
```

---

## 🏢 **Companies Management**

### Business Streams
```http
GET    /api/v1/companies/business-streams/   # List business categories
POST   /api/v1/companies/business-streams/   # Create category
GET    /api/v1/companies/business-streams/{id}/ # Get specific category
PUT    /api/v1/companies/business-streams/{id}/ # Update category
DELETE /api/v1/companies/business-streams/{id}/ # Delete category
```

**Create Business Stream:**
```json
{
    "business_stream_name": "Technology"
}
```

### Company Profiles
```http
GET    /api/v1/companies/companies/          # List company profiles
POST   /api/v1/companies/companies/          # Create company profile
GET    /api/v1/companies/companies/{id}/     # Get specific company
PUT    /api/v1/companies/companies/{id}/     # Update company
DELETE /api/v1/companies/companies/{id}/     # Delete company
```

**Create Company Profile:**
```json
{
    "user_account": "company-user-uuid-here",
    "company_name": "TechCorp Solutions",
    "business_stream": "tech-stream-uuid-here",
    "profile_description": "Leading software development company specializing in web applications",
    "company_website_url": "https://techcorp.com",
    "contact_email": "info@techcorp.com",
    "status": "active"
}
```

### Company Images
```http
GET    /api/v1/companies/company-images/     # List company images
POST   /api/v1/companies/company-images/     # Upload company image
GET    /api/v1/companies/company-images/{id}/ # Get specific image
DELETE /api/v1/companies/company-images/{id}/ # Delete image
```

**Add Company Image:**
```json
{
    "company": "company-uuid-here",
    "image_url": "https://example.com/company-logo.png"
}
```

### Company Dashboard
```http
GET    /api/v1/companies/dashboard/{user_id}/ # Get complete company data
```

---

## 💼 **Jobs Management**

### Job Types & Locations
```http
GET    /api/v1/jobs/job-types/               # List job types
POST   /api/v1/jobs/job-types/               # Create job type
GET    /api/v1/jobs/job-locations/           # List job locations
POST   /api/v1/jobs/job-locations/           # Create job location
```

**Create Job Type:**
```json
{
    "job_type_name": "Full-time",
    "description": "Full-time employment position"
}
```

**Create Job Location:**
```json
{
    "street_address": "123 Tech Street",
    "city": "New York",
    "country": "USA",
    "zip": "10001",
    "country_code": "US"
}
```

### Job Posts
```http
GET    /api/v1/jobs/job-posts/               # List jobs (with search)
POST   /api/v1/jobs/job-posts/               # Create job post
GET    /api/v1/jobs/job-posts/{id}/          # Get specific job
PUT    /api/v1/jobs/job-posts/{id}/          # Update job
DELETE /api/v1/jobs/job-posts/{id}/          # Delete job
```

**Search Parameters:**
- `?search=python` - Search in title and description
- `?city=New York` - Filter by city

**Create Job Post:**
```json
{
    "company": "company-uuid-here",
    "job_type": "job-type-uuid-here",
    "job_location": "job-location-uuid-here",
    "job_title": "Senior Python Developer",
    "job_description": "We are looking for an experienced Python developer to join our team. You will be responsible for developing web applications using Django framework.",
    "salary_min": 80000.00,
    "salary_max": 120000.00,
    "salary_type": "yearly",
    "deadline_date": "2024-03-31",
    "is_published": true,
    "is_active": true
}
```

### Job Applications
```http
GET    /api/v1/jobs/job-applications/        # List applications
POST   /api/v1/jobs/job-applications/        # Create application
POST   /api/v1/jobs/apply/                   # Apply for job (simplified)
GET    /api/v1/jobs/applications/job/{job_id}/ # Applications for specific job
GET    /api/v1/jobs/applications/user/{user_id}/ # User's applications
```

**Apply for Job:**
```json
{
    "user_account": "123e4567-e89b-12d3-a456-426614174000",
    "job_post": "job-post-uuid-here",
    "cover_letter": "Dear Hiring Manager, I am excited to apply for the Senior Python Developer position. With 5 years of experience in Django development, I believe I would be a great fit for your team."
}
```

**Response:**
```json
{
    "message": "Application submitted successfully"
}
```

### Job Skill Requirements
```http
GET    /api/v1/jobs/job-skills/              # List job skill requirements
POST   /api/v1/jobs/job-skills/              # Add skill requirement to job
```

**Add Job Skill Requirement:**
```json
{
    "job_post": "job-post-uuid-here",
    "skill_set": "python-skill-uuid-here",
    "skill_level": "Advanced",
    "is_required": true
}
```

---

## 📊 **Data Validation Rules**

### User Account Validation
- **Email**: Must be unique and valid format
- **Password**: Minimum 6 characters, no leading/trailing spaces
- **Phone**: Only digits, +, spaces, dashes allowed (minimum 10 digits)
- **User Type**: Must be valid choice (job_seeker or company)

### Job Post Validation
- **Job Title**: Required, maximum 200 characters
- **Job Description**: Required
- **Salary Range**: If provided, min must be less than max
- **Company**: Must be valid company UUID

### Application Validation
- **Duplicate Prevention**: One application per user per job
- **Valid References**: User and job post must exist
- **Status Updates**: Only job owner can update application status

---

## ❌ **Error Responses**

### 400 Bad Request
```json
{
    "email": ["This email is already registered"],
    "password": ["Password must be at least 6 characters long"]
}
```

### 401 Unauthorized
```json
{
    "error": "Invalid credentials"
}
```

### 404 Not Found
```json
{
    "error": "Profile not found"
}
```

### 409 Conflict
```json
{
    "error": "You have already applied for this job"
}
```

---

## 🔧 **Testing Examples**

### Using cURL

**Register a user:**
```bash
curl -X POST http://localhost:8000/api/v1/accounts/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123",
    "user_type": "job_seeker"
  }'
```

**Login:**
```bash
curl -X POST http://localhost:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123"
  }'
```

**Search jobs:**
```bash
curl -X GET "http://localhost:8000/api/v1/jobs/job-posts/?search=python&city=New York" \
  -H "Authorization: Basic <base64-encoded-credentials>"
```

**Apply for a job:**
```bash
curl -X POST http://localhost:8000/api/v1/jobs/apply/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Basic <base64-encoded-credentials>" \
  -d '{
    "user_account": "user-uuid-here",
    "job_post": "job-uuid-here",
    "cover_letter": "I am interested in this position..."
  }'
```

### Using Python requests

```python
import requests
import base64

# Base URL
BASE_URL = "http://localhost:8000/api/v1"

# Authentication
def get_auth_header(email, password):
    credentials = base64.b64encode(f"{email}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}

# Register user
response = requests.post(f"{BASE_URL}/accounts/register/", json={
    "email": "john@example.com",
    "password": "password123",
    "user_type": "job_seeker"
})

# Login and get user info
login_response = requests.post(f"{BASE_URL}/accounts/login/", json={
    "email": "john@example.com",
    "password": "password123"
})

# Search jobs (authenticated)
headers = get_auth_header("john@example.com", "password123")
jobs = requests.get(f"{BASE_URL}/jobs/job-posts/?search=python", headers=headers)

# Apply for job
application = requests.post(f"{BASE_URL}/jobs/apply/", 
    headers=headers,
    json={
        "user_account": "user-uuid",
        "job_post": "job-uuid",
        "cover_letter": "I'm interested in this position"
    }
)
```

---

## 📋 **Common Workflows**

### Complete Job Seeker Registration Flow
1. `POST /api/v1/accounts/register/` - Register account
2. `POST /api/v1/seekers/profiles/` - Create profile
3. `POST /api/v1/seekers/education/` - Add education
4. `POST /api/v1/seekers/experience/` - Add experience
5. `POST /api/v1/seekers/seeker-skills/` - Add skills
6. `GET /api/v1/seekers/dashboard/{user_id}/` - View complete profile

### Complete Company Registration Flow
1. `POST /api/v1/accounts/register/` - Register account
2. `POST /api/v1/companies/companies/` - Create company profile
3. `POST /api/v1/companies/company-images/` - Add company images
4. `POST /api/v1/jobs/job-posts/` - Post jobs
5. `GET /api/v1/companies/dashboard/{user_id}/` - View company data

### Job Application Process
1. `GET /api/v1/jobs/job-posts/?search=keyword` - Search jobs
2. `GET /api/v1/jobs/job-posts/{id}/` - View job details
3. `POST /api/v1/jobs/apply/` - Apply for job
4. `GET /api/v1/jobs/applications/user/{user_id}/` - Track applications

---

## 📝 **Response Formats**

### Success Responses
- **200 OK**: Request successful, data returned
- **201 Created**: Resource created successfully
- **204 No Content**: Request successful, no data returned

### Error Response Format
```json
{
    "error": "Error message",
    "details": {
        "field_name": ["Validation error message"]
    }
}
```

### Pagination (for list endpoints)
```json
{
    "count": 25,
    "next": "http://localhost:8000/api/v1/jobs/job-posts/?page=2",
    "previous": null,
    "results": [...]
}
```

---

## 🎯 **Quick Reference**

### Required Fields by Endpoint
- **User Registration**: `email`, `password`, `user_type`
- **Job Post**: `company`, `job_type`, `job_location`, `job_title`, `job_description`
- **Job Application**: `user_account`, `job_post`
- **Seeker Profile**: `user_account`, `first_name`, `last_name`
- **Company Profile**: `user_account`, `company_name`, `business_stream`

### UUID Format
All IDs use UUID format: `550e8400-e29b-41d4-a716-446655440000`

### Date Formats
- **Date**: `YYYY-MM-DD` (e.g., `2024-03-31`)
- **DateTime**: `YYYY-MM-DDTHH:MM:SSZ` (e.g., `2024-03-31T14:30:00Z`)