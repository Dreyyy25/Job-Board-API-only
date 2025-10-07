# Job Board API Documentation

## Base URL
```
http://localhost:8000/api/v1/
```

## Authentication

**JWT Bearer Token** (Primary)
```http
Authorization: Bearer <access_token>
```

### Token Lifecycle
- **Access Token**: 60 minutes
- **Refresh Token**: 7 days
- Tokens are blacklisted on logout

---

## 📍 Endpoints Overview

### Accounts (Authentication & Users)
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/accounts/register/` | Register new user | No |
| POST | `/accounts/login/` | User login | No |
| POST | `/accounts/token/refresh/` | Refresh access token | No |
| POST | `/accounts/token/verify/` | Verify token validity | No |
| POST | `/accounts/token/blacklist/` | Logout (blacklist token) | Yes |
| GET | `/accounts/users/` | List all users | Yes |
| POST | `/accounts/users/` | Create user | Yes |
| GET | `/accounts/users/{id}/` | Get user by ID | Yes |
| PUT | `/accounts/users/{id}/` | Update user | Yes |
| PATCH | `/accounts/users/{id}/` | Partial update user | Yes |
| DELETE | `/accounts/users/{id}/` | Delete user | Yes |

### Companies
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/companies/business-streams/` | List business streams | No |
| POST | `/companies/business-streams/` | Create business stream | Yes (Admin) |
| GET | `/companies/business-streams/{id}/` | Get business stream | No |
| PUT | `/companies/business-streams/{id}/` | Update business stream | Yes (Admin) |
| DELETE | `/companies/business-streams/{id}/` | Delete business stream | Yes (Admin) |
| GET | `/companies/companies/` | List companies | Yes |
| POST | `/companies/companies/` | Create company profile | Yes |
| GET | `/companies/companies/{id}/` | Get company profile | Yes |
| PUT | `/companies/companies/{id}/` | Update company | Yes (Owner/Admin) |
| PATCH | `/companies/companies/{id}/` | Partial update company | Yes (Owner/Admin) |
| DELETE | `/companies/companies/{id}/` | Delete company | Yes (Owner/Admin) |
| GET | `/companies/companies/{id}/dashboard/` | Company dashboard | Yes (Owner/Admin) |
| GET | `/companies/company-images/` | List company images | Yes |
| POST | `/companies/company-images/` | Upload company image | Yes (Owner/Admin) |
| GET | `/companies/company-images/{id}/` | Get image | Yes |
| PUT | `/companies/company-images/{id}/` | Update image | Yes (Owner/Admin) |
| DELETE | `/companies/company-images/{id}/` | Delete image | Yes (Owner/Admin) |

### Jobs
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/jobs/job-types/` | List job types | No |
| POST | `/jobs/job-types/` | Create job type | Yes (Admin) |
| GET | `/jobs/job-types/{id}/` | Get job type | No |
| PUT | `/jobs/job-types/{id}/` | Update job type | Yes (Admin) |
| DELETE | `/jobs/job-types/{id}/` | Delete job type | Yes (Admin) |
| GET | `/jobs/job-locations/` | List job locations | No |
| POST | `/jobs/job-locations/` | Create job location | Yes (Admin) |
| GET | `/jobs/job-locations/{id}/` | Get job location | No |
| PUT | `/jobs/job-locations/{id}/` | Update job location | Yes (Admin) |
| DELETE | `/jobs/job-locations/{id}/` | Delete job location | Yes (Admin) |
| GET | `/jobs/job-posts/` | List/search jobs | No |
| POST | `/jobs/job-posts/` | Create job post | Yes (Company) |
| GET | `/jobs/job-posts/{id}/` | Get job details | No |
| PUT | `/jobs/job-posts/{id}/` | Update job | Yes (Poster/Admin) |
| PATCH | `/jobs/job-posts/{id}/` | Partial update job | Yes (Poster/Admin) |
| DELETE | `/jobs/job-posts/{id}/` | Delete job | Yes (Poster/Admin) |
| POST | `/jobs/apply/` | Apply for job | Yes (Seeker) |
| GET | `/jobs/job-applications/` | List applications | Yes |
| GET | `/jobs/job-applications/{id}/` | Get application | Yes |
| PATCH | `/jobs/job-applications/{id}/` | Update application status | Yes |
| GET | `/jobs/applications/job/{job_id}/` | Applications by job | Yes (Company/Admin) |
| GET | `/jobs/applications/user/{user_id}/` | Applications by user | Yes (User/Admin) |
| GET | `/jobs/job-skills/` | List job skill requirements | Yes |
| POST | `/jobs/job-skills/` | Add skill requirement | Yes (Poster/Admin) |
| GET | `/jobs/job-skills/{id}/` | Get job skill | Yes |
| PUT | `/jobs/job-skills/{id}/` | Update job skill | Yes (Poster/Admin) |
| DELETE | `/jobs/job-skills/{id}/` | Delete job skill | Yes (Poster/Admin) |

### Seekers
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/seekers/seeker-profiles/` | List seeker profiles | Yes |
| POST | `/seekers/seeker-profiles/` | Create profile | Yes |
| GET | `/seekers/seeker-profiles/{id}/` | Get profile | Yes |
| PUT | `/seekers/seeker-profiles/{id}/` | Update profile | Yes (Owner/Admin) |
| PATCH | `/seekers/seeker-profiles/{id}/` | Partial update profile | Yes (Owner/Admin) |
| DELETE | `/seekers/seeker-profiles/{id}/` | Delete profile | Yes (Owner/Admin) |
| GET | `/seekers/seeker-profiles/{id}/dashboard/` | Seeker dashboard | Yes (Owner) |
| GET | `/seekers/education-details/` | List education records | Yes |
| POST | `/seekers/education-details/` | Add education | Yes |
| GET | `/seekers/education-details/{id}/` | Get education | Yes |
| PUT | `/seekers/education-details/{id}/` | Update education | Yes (Owner/Admin) |
| DELETE | `/seekers/education-details/{id}/` | Delete education | Yes (Owner/Admin) |
| GET | `/seekers/experience-details/` | List experience records | Yes |
| POST | `/seekers/experience-details/` | Add experience | Yes |
| GET | `/seekers/experience-details/{id}/` | Get experience | Yes |
| PUT | `/seekers/experience-details/{id}/` | Update experience | Yes (Owner/Admin) |
| DELETE | `/seekers/experience-details/{id}/` | Delete experience | Yes (Owner/Admin) |
| GET | `/seekers/skill-sets/` | List all skills | No |
| POST | `/seekers/skill-sets/` | Create skill | Yes (Admin) |
| GET | `/seekers/skill-sets/{id}/` | Get skill | No |
| PUT | `/seekers/skill-sets/{id}/` | Update skill | Yes (Admin) |
| DELETE | `/seekers/skill-sets/{id}/` | Delete skill | Yes (Admin) |
| GET | `/seekers/seeker-skills/` | List user skills | Yes |
| POST | `/seekers/seeker-skills/` | Add skill to profile | Yes |
| GET | `/seekers/seeker-skills/{id}/` | Get user skill | Yes |
| PUT | `/seekers/seeker-skills/{id}/` | Update skill level | Yes (Owner/Admin) |
| DELETE | `/seekers/seeker-skills/{id}/` | Remove skill | Yes (Owner/Admin) |

---

## 🔑 Authentication Examples

### Register User
```http
POST /api/v1/accounts/register/
Content-Type: application/json

{
  "user_type": "job_seeker",
  "email": "user@example.com",
  "password": "password123",
  "date_of_birth": "1990-01-15",
  "contact_number": "+1234567890",
  "sex": "M"
}
```

**Response:**
```json
{
  "message": "User created successfully",
  "user": {
    "id": "uuid-here",
    "email": "user@example.com",
    "user_type": "job_seeker"
  },
  "tokens": {
    "refresh": "refresh-token-here",
    "access": "access-token-here"
  }
}
```

### Login
```http
POST /api/v1/accounts/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

### Refresh Token
```http
POST /api/v1/accounts/token/refresh/
Content-Type: application/json

{
  "refresh": "refresh-token-here"
}
```

### Logout
```http
POST /api/v1/accounts/token/blacklist/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "refresh": "refresh-token-here"
}
```

---

## 💼 Common Request Examples

### Create Company Profile
```http
POST /api/v1/companies/companies/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "company_name": "Tech Solutions Inc",
  "business_stream": "business-stream-uuid",
  "profile_description": "Leading software company",
  "company_website_url": "https://techsolutions.com",
  "contact_email": "info@techsolutions.com",
  "status": "active"
}
```

### Post a Job
```http
POST /api/v1/jobs/job-posts/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "job_type": "job-type-uuid",
  "job_location": "location-uuid",
  "job_title": "Senior Python Developer",
  "job_description": "We're looking for an experienced Python developer...",
  "salary_min": 80000.00,
  "salary_max": 120000.00,
  "salary_type": "yearly",
  "deadline_date": "2025-12-31",
  "is_published": true,
  "is_active": true
}
```

### Search Jobs
```http
GET /api/v1/jobs/job-posts/?search=python&city=New York
Authorization: Bearer <access-token>
```

**Query Parameters:**
- `search` - Search in job title and description
- `city` - Filter by city name

### Apply for Job
```http
POST /api/v1/jobs/apply/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "job_post": "job-uuid",
  "cover_letter": "Dear Hiring Manager, I am interested..."
}
```

### Create Seeker Profile
```http
POST /api/v1/seekers/seeker-profiles/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "first_name": "John",
  "last_name": "Doe",
  "date_of_birth": "1995-03-15",
  "gender": "Male",
  "bio": "Passionate software engineer...",
  "contact_number": "+1-555-0123"
}
```

### Add Education
```http
POST /api/v1/seekers/education-details/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "seeker_profile": "profile-uuid",
  "major": "Computer Science",
  "university_name": "Stanford University",
  "starting_date": "2013-09-01",
  "completion_date": "2017-06-15",
  "degree_type": "Bachelor's Degree",
  "gpa": 3.8,
  "description": "Focus on software engineering..."
}
```

### Add Work Experience
```http
POST /api/v1/seekers/experience-details/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "seeker_profile": "profile-uuid",
  "job_title": "Senior Python Developer",
  "company_name": "Tech Innovations Inc",
  "starting_date": "2020-01-15",
  "completion_date": null,
  "is_current_job": true,
  "description": "Leading development of RESTful APIs..."
}
```

### Add Skill to Profile
```http
POST /api/v1/seekers/seeker-skills/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "seeker_profile": "profile-uuid",
  "skill_set": "skill-uuid",
  "skill_level": "Advanced"
}
```

**Skill Levels:** `Beginner`, `Intermediate`, `Advanced`, `Expert`

---

## 📊 Field Choices

### User Types
- `job_seeker`
- `company`

### Degree Types
- `High School`
- `Associate's Degree`
- `Bachelor's Degree`
- `Master's Degree`
- `Doctorate`
- `Certificate`
- `Bootcamp`

### Application Status
- `pending`
- `reviewed`
- `accepted`
- `rejected`
- `withdrawn`

### Salary Types
- `hourly`
- `monthly`
- `yearly`

### Company Status
- `active`
- `inactive`
- `suspended`

---

## ❌ Error Responses

**400 Bad Request**
```json
{
  "email": ["This email is already registered"],
  "password": ["Password must be at least 6 characters long"]
}
```

**401 Unauthorized**
```json
{
  "detail": "Authentication credentials were not provided."
}
```

**403 Forbidden**
```json
{
  "detail": "You do not have permission to perform this action."
}
```

**404 Not Found**
```json
{
  "detail": "Not found."
}
```

**409 Conflict**
```json
{
  "error": "You have already applied for this job"
}
```

---

## 🔧 Testing with cURL

### Register and Login
```bash
# Register
curl -X POST http://localhost:8000/api/v1/accounts/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123",
    "user_type": "job_seeker"
  }'

# Login
curl -X POST http://localhost:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123"
  }'
```

### Use JWT Token
```bash
# Set token variable
TOKEN="your-access-token-here"

# Search jobs
curl -X GET "http://localhost:8000/api/v1/jobs/job-posts/?search=python" \
  -H "Authorization: Bearer $TOKEN"

# Apply for job
curl -X POST http://localhost:8000/api/v1/jobs/apply/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_account": "user-uuid",
    "job_post": "job-uuid",
    "cover_letter": "I am interested..."
  }'
```

---

## 📦 Postman Collections

Import the provided collections for organized API testing:

- **Accounts API** - Authentication and user management
- **Companies API** - Company profiles and business streams  
- **Jobs API** - Job postings, applications, and requirements
- **Seekers API** - Profiles, education, experience, and skills

Each collection includes:
- Pre-configured requests with sample data
- Auto-save scripts for IDs and tokens
- Nested folder organization
- Collection variables for easy testing

---

## 📝 Notes

- All IDs use UUID format
- Dates use `YYYY-MM-DD` format
- DateTimes use ISO 8601 format
- All responses are in JSON format
- List endpoints support pagination
- Most endpoints require authentication via JWT Bearer token