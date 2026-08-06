# Job Board API Documentation

## Base URL
```
http://localhost:8000/api/v1/
```

## Overview

This API provides 82 endpoints organized into 4 main modules:
- **Accounts** (14 endpoints) - Authentication, token management, and user accounts
- **Companies** (17 endpoints) - Business streams, company profiles, and images
- **Jobs** (27 endpoints) - Job types, locations, posts, applications, and skills
- **Seekers** (27 endpoints) - Seeker profiles, education, experience, and skills

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
| GET | `/accounts/me/` | Get current user info | Yes |
| PUT | `/accounts/me/` | Update current user | Yes |
| PATCH | `/accounts/me/` | Partial update current user | Yes |
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
| GET | `/companies/profile/` | List companies | Yes |
| POST | `/companies/profile/` | Create company profile | Yes |
| GET | `/companies/profile/{id}/` | Get company profile | Yes |
| PUT | `/companies/profile/{id}/` | Update company | Yes (Owner/Admin) |
| PATCH | `/companies/profile/{id}/` | Partial update company | Yes (Owner/Admin) |
| DELETE | `/companies/profile/{id}/` | Delete company | Yes (Owner/Admin) |
| GET | `/companies/dashboard/{user_id}/` | Company dashboard | Yes (Owner/Admin) |
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
| POST | `/jobs/job-locations/` | Create job location | Yes |
| GET | `/jobs/job-locations/{id}/` | Get job location | No |
| PUT | `/jobs/job-locations/{id}/` | Update job location | Yes |
| DELETE | `/jobs/job-locations/{id}/` | Delete job location | Yes |
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
| GET | `/seekers/profiles/` | List seeker profiles | Yes |
| POST | `/seekers/profiles/` | Create profile | Yes |
| GET | `/seekers/profiles/{id}/` | Get profile | Yes |
| PUT | `/seekers/profiles/{id}/` | Update profile | Yes (Owner/Admin) |
| PATCH | `/seekers/profiles/{id}/` | Partial update profile | Yes (Owner/Admin) |
| DELETE | `/seekers/profiles/{id}/` | Delete profile | Yes (Owner/Admin) |
| GET | `/seekers/dashboard/{user_id}/` | Seeker dashboard | Yes (Owner) |
| GET | `/seekers/education/` | List education records | Yes |
| POST | `/seekers/education/` | Add education | Yes |
| GET | `/seekers/education/{id}/` | Get education | Yes |
| PUT | `/seekers/education/{id}/` | Update education | Yes (Owner/Admin) |
| DELETE | `/seekers/education/{id}/` | Delete education | Yes (Owner/Admin) |
| GET | `/seekers/experience/` | List experience records | Yes |
| POST | `/seekers/experience/` | Add experience | Yes |
| GET | `/seekers/experience/{id}/` | Get experience | Yes |
| PUT | `/seekers/experience/{id}/` | Update experience | Yes (Owner/Admin) |
| DELETE | `/seekers/experience/{id}/` | Delete experience | Yes (Owner/Admin) |
| GET | `/seekers/skills/` | List all skills | No |
| POST | `/seekers/skills/` | Create skill | Yes (Admin) |
| GET | `/seekers/skills/{id}/` | Get skill | No |
| PUT | `/seekers/skills/{id}/` | Update skill | Yes (Admin) |
| DELETE | `/seekers/skills/{id}/` | Delete skill | Yes (Admin) |
| GET | `/seekers/seeker-skills/` | List user skills | Yes |
| POST | `/seekers/seeker-skills/` | Add skill to profile | Yes |
| GET | `/seekers/seeker-skills/{id}/` | Get user skill | Yes |
| PUT | `/seekers/seeker-skills/{id}/` | Update skill level | Yes (Owner/Admin) |
| DELETE | `/seekers/seeker-skills/{id}/` | Remove skill | Yes (Owner/Admin) |

---

## 🔑 Authentication Examples

### 1. Register User (Job Seeker)
```http
POST /api/v1/accounts/register/
Content-Type: application/json

{
  "user_type": "job_seeker",
  "email": "jobseeker@example.com",
  "password": "SmokeTest12345",
  "date_of_birth": "1995-03-15",
  "contact_number": "+1234567890",
  "sex": "M",
  "user_image_url": "https://example.com/profile.jpg"
}
```

**Response:**
```json
{
  "message": "User created successfully",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "jobseeker@example.com",
    "user_type": "job_seeker"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
  }
}
```

### 2. Register User (Company)
```http
POST /api/v1/accounts/register/
Content-Type: application/json

{
  "user_type": "company",
  "email": "company@techsolutions.com",
  "password": "SecurePass456!x",
  "contact_number": "+1-555-0100"
}
```

### 3. Login
```http
POST /api/v1/accounts/login/
Content-Type: application/json

{
  "email": "jobseeker@example.com",
  "password": "SmokeTest12345"
}
```

**Response:**
```json
{
  "message": "Login successful",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "jobseeker@example.com",
    "user_type": "job_seeker"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
  }
}
```

### 4. Refresh Token

The refresh token never travels in a request or response body — `register`/
`login` set it as an httpOnly cookie scoped to `/api/v1/accounts/`, and this
endpoint reads **only** that cookie (a body, if sent, is ignored). Browsers
attach the cookie automatically; the response rotates it via `Set-Cookie`.

```http
POST /api/v1/accounts/token/refresh/
Cookie: refresh_token=eyJ0eXAiOiJKV1QiLCJhbGc...
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### 5. Verify Token
```http
POST /api/v1/accounts/token/verify/
Content-Type: application/json

{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

---

## 👤 User Management

### 6. Get Current User Info
```http
GET /api/v1/accounts/me/
Authorization: Bearer <access-token>
```

### 7. Update Current User
```http
PUT /api/v1/accounts/me/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "contact_number": "+1-555-9999",
  "user_image_url": "https://example.com/new-profile.jpg"
}
```

### 8. List All Users (Admin Only)
```http
GET /api/v1/accounts/users/
Authorization: Bearer <access-token>
```

### 9. Get Specific User
```http
GET /api/v1/accounts/users/{user-id}/
Authorization: Bearer <access-token>
```

### 10. Update User
```http
PUT /api/v1/accounts/users/{user-id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_type": "job_seeker",
  "email": "updated@example.com",
  "date_of_birth": "1995-03-15",
  "contact_number": "+1234567890",
  "sex": "F",
  "user_image_url": "https://example.com/profile.jpg"
}
```

### 11. Delete User
```http
DELETE /api/v1/accounts/users/{user-id}/
Authorization: Bearer <access-token>
```

---

## 🏢 Companies Module

### 12. Create Business Stream (Admin Only)
```http
POST /api/v1/companies/business-streams/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "business_stream_name": "Information Technology"
}
```

### 13. List Business Streams
```http
GET /api/v1/companies/business-streams/
```

### 14. Get Business Stream
```http
GET /api/v1/companies/business-streams/{id}/
```

### 15. Update Business Stream (Admin Only)
```http
PUT /api/v1/companies/business-streams/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "business_stream_name": "Technology & Software"
}
```

### 16. Delete Business Stream (Admin Only)
```http
DELETE /api/v1/companies/business-streams/{id}/
Authorization: Bearer <access-token>
```

### 17. Create Company Profile
```http
POST /api/v1/companies/profile/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "550e8400-e29b-41d4-a716-446655440000",
  "company_name": "Tech Solutions Inc",
  "business_stream": "business-stream-uuid",
  "profile_description": "Leading software development company specializing in AI and cloud solutions",
  "company_website_url": "https://techsolutions.com",
  "contact_email": "info@techsolutions.com",
  "status": "active"
}
```

**Note:** The `user_account` is automatically set to the current user in the backend.

### 18. List Companies
```http
GET /api/v1/companies/profile/
Authorization: Bearer <access-token>
```

### 19. Get Company Profile
```http
GET /api/v1/companies/profile/{id}/
Authorization: Bearer <access-token>
```

### 20. Update Company Profile
```http
PUT /api/v1/companies/profile/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "550e8400-e29b-41d4-a716-446655440000",
  "company_name": "Tech Solutions International",
  "business_stream": "business-stream-uuid",
  "profile_description": "Updated description",
  "company_website_url": "https://techsolutions.com",
  "contact_email": "contact@techsolutions.com",
  "status": "active"
}
```

### 21. Partial Update Company
```http
PATCH /api/v1/companies/profile/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "contact_email": "newcontact@techsolutions.com",
  "status": "inactive"
}
```

### 22. Delete Company
```http
DELETE /api/v1/companies/profile/{id}/
Authorization: Bearer <access-token>
```

### 23. Get Company Dashboard
```http
GET /api/v1/companies/dashboard/{user-id}/
Authorization: Bearer <access-token>
```

**Response:**
```json
{
  "company": {
    "id": "company-uuid",
    "company_name": "Tech Solutions Inc",
    "business_stream": "business-stream-uuid",
    ...
  },
  "images": [
    {
      "id": "image-uuid",
      "company": "company-uuid",
      "image_url": "https://example.com/logo.png",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

### 24. Upload Company Image
```http
POST /api/v1/companies/company-images/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "company": "company-uuid",
  "image_url": "https://example.com/company-logo.png"
}
```

### 25. List Company Images
```http
GET /api/v1/companies/company-images/
Authorization: Bearer <access-token>
```

### 26. Get Company Image
```http
GET /api/v1/companies/company-images/{id}/
Authorization: Bearer <access-token>
```

### 27. Update Company Image
```http
PUT /api/v1/companies/company-images/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "company": "company-uuid",
  "image_url": "https://example.com/new-logo.png"
}
```

### 28. Delete Company Image
```http
DELETE /api/v1/companies/company-images/{id}/
Authorization: Bearer <access-token>
```

---

## 💼 Jobs Module

### 29. Create Job Type (Admin Only)
```http
POST /api/v1/jobs/job-types/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "job_type_name": "Full-time",
  "description": "Full-time employment position"
}
```

### 30. List Job Types
```http
GET /api/v1/jobs/job-types/
```

### 31. Get Job Type
```http
GET /api/v1/jobs/job-types/{id}/
```

### 32. Update Job Type (Admin Only)
```http
PUT /api/v1/jobs/job-types/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "job_type_name": "Full-time",
  "description": "Permanent full-time employment"
}
```

### 33. Delete Job Type (Admin Only)
```http
DELETE /api/v1/jobs/job-types/{id}/
Authorization: Bearer <access-token>
```

### 34. Create Job Location
```http
POST /api/v1/jobs/job-locations/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "street_address": "123 Tech Street",
  "city": "San Francisco",
  "country": "United States",
  "zip": "94102",
  "country_code": "US"
}
```

### 35. List Job Locations
```http
GET /api/v1/jobs/job-locations/
```

### 36. Get Job Location
```http
GET /api/v1/jobs/job-locations/{id}/
```

### 37. Update Job Location
```http
PUT /api/v1/jobs/job-locations/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "street_address": "456 Innovation Ave",
  "city": "San Francisco",
  "country": "United States",
  "zip": "94103",
  "country_code": "US"
}
```

### 38. Delete Job Location
```http
DELETE /api/v1/jobs/job-locations/{id}/
Authorization: Bearer <access-token>
```

### 39. Create Job Post (Company Only)
```http
POST /api/v1/jobs/job-posts/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "company": "company-uuid",
  "job_type": "job-type-uuid",
  "job_location": "location-uuid",
  "job_title": "Senior Python Developer",
  "job_description": "We are seeking an experienced Python developer to join our team...",
  "job_description_hidden": "Internal notes about the position",
  "salary_min": "80000.00",
  "salary_max": "120000.00",
  "salary_type": "yearly",
  "deadline_date": "2025-12-31",
  "is_published": true,
  "is_active": true
}
```

**Note:** The `company` is automatically set based on the authenticated user's company profile.

**Salary Type Options:** `hourly`, `monthly`, `yearly`

### 40. List/Search Job Posts
```http
GET /api/v1/jobs/job-posts/
```

**Query Parameters:**
- `search` - Search in job title and description (e.g., `?search=python`)
- `city` - Filter by city name (e.g., `?city=San Francisco`)
- Combined: `?search=developer&city=New York`

### 41. Get Job Post Details
```http
GET /api/v1/jobs/job-posts/{id}/
```

### 42. Update Job Post
```http
PUT /api/v1/jobs/job-posts/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "company": "company-uuid",
  "job_type": "job-type-uuid",
  "job_location": "location-uuid",
  "job_title": "Senior Python Developer (Updated)",
  "job_description": "Updated job description...",
  "salary_min": "90000.00",
  "salary_max": "130000.00",
  "salary_type": "yearly",
  "deadline_date": "2025-12-31",
  "is_published": true,
  "is_active": true
}
```

### 43. Partial Update Job Post
```http
PATCH /api/v1/jobs/job-posts/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "salary_max": "140000.00",
  "is_active": false
}
```

### 44. Delete Job Post
```http
DELETE /api/v1/jobs/job-posts/{id}/
Authorization: Bearer <access-token>
```

### 45. Apply for Job (Job Seeker Only)
```http
POST /api/v1/jobs/apply/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "job_post": "job-post-uuid",
  "cover_letter": "Dear Hiring Manager,\n\nI am writing to express my strong interest in the Senior Python Developer position...",
  "application_status": "pending"
}
```

**Note:** The `user_account` is validated to match the authenticated user.

**Response:**
```json
{
  "message": "Application submitted successfully",
  "data": {
    "id": "application-uuid",
    "user_account": "user-uuid",
    "job_post": "job-post-uuid",
    "application_date": "2025-10-17T14:30:00Z",
    "application_status": "pending",
    "cover_letter": "Dear Hiring Manager...",
    "updated_at": "2025-10-17T14:30:00Z"
  }
}
```

### 46. List Job Applications
```http
GET /api/v1/jobs/job-applications/
Authorization: Bearer <access-token>
```

**Note:** 
- Job seekers see only their own applications
- Companies see applications to their job posts
- Admins see all applications

### 47. Get Job Application
```http
GET /api/v1/jobs/job-applications/{id}/
Authorization: Bearer <access-token>
```

### 48. Update Application Status
```http
PATCH /api/v1/jobs/job-applications/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "application_status": "reviewed"
}
```

**Application Status Options:** `pending`, `reviewed`, `accepted`, `rejected`, `withdrawn`

### 49. Get Applications for Specific Job (Company/Admin)
```http
GET /api/v1/jobs/applications/job/{job-id}/
Authorization: Bearer <access-token>
```

### 50. Get Applications by User (User/Admin)
```http
GET /api/v1/jobs/applications/user/{user-id}/
Authorization: Bearer <access-token>
```

### 51. Add Job Skill Requirement (Company/Admin)
```http
POST /api/v1/jobs/job-skills/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "job_post": "job-post-uuid",
  "skill_set": "skill-uuid",
  "skill_level": "Advanced",
  "is_required": true
}
```

**Skill Levels:** `Beginner`, `Intermediate`, `Advanced`, `Expert`

### 52. List Job Skills
```http
GET /api/v1/jobs/job-skills/
Authorization: Bearer <access-token>
```

### 53. Get Job Skill
```http
GET /api/v1/jobs/job-skills/{id}/
Authorization: Bearer <access-token>
```

### 54. Update Job Skill
```http
PUT /api/v1/jobs/job-skills/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "job_post": "job-post-uuid",
  "skill_set": "skill-uuid",
  "skill_level": "Expert",
  "is_required": false
}
```

### 55. Delete Job Skill
```http
DELETE /api/v1/jobs/job-skills/{id}/
Authorization: Bearer <access-token>
```

---

## 👨‍💼 Seekers Module

### 56. Create Seeker Profile (Job Seeker Only)
```http
POST /api/v1/seekers/profiles/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "first_name": "John",
  "last_name": "Doe",
  "contact_details": "Email: john.doe@example.com\nPhone: +1-555-0123",
  "goals": "Seeking a challenging role in software development where I can leverage my Python expertise",
  "resume_url": "https://example.com/resumes/john-doe.pdf"
}
```

**Note:** The `user_account` is automatically set to the current user. Must be a job_seeker type user.

### 57. List Seeker Profiles
```http
GET /api/v1/seekers/profiles/
Authorization: Bearer <access-token>
```

### 58. Get Seeker Profile
```http
GET /api/v1/seekers/profiles/{user-account-id}/
Authorization: Bearer <access-token>
```

**Note:** The primary key is the user_account UUID.

### 59. Update Seeker Profile
```http
PUT /api/v1/seekers/profiles/{user-account-id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "first_name": "John",
  "last_name": "Doe",
  "contact_details": "Updated contact information",
  "goals": "Updated career goals",
  "resume_url": "https://example.com/resumes/john-doe-updated.pdf"
}
```

### 60. Partial Update Seeker Profile
```http
PATCH /api/v1/seekers/profiles/{user-account-id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "resume_url": "https://example.com/resumes/new-resume.pdf",
  "goals": "Looking for senior-level opportunities"
}
```

### 61. Delete Seeker Profile
```http
DELETE /api/v1/seekers/profiles/{user-account-id}/
Authorization: Bearer <access-token>
```

### 62. Get Seeker Dashboard
```http
GET /api/v1/seekers/dashboard/{user-id}/
Authorization: Bearer <access-token>
```

**Response:**
```json
{
  "profile": {
    "user_account": "user-uuid",
    "first_name": "John",
    "last_name": "Doe",
    ...
  },
  "education": [
    {
      "id": "education-uuid",
      "degree_type": "Bachelor",
      ...
    }
  ],
  "experience": [
    {
      "id": "experience-uuid",
      "company_name": "Tech Corp",
      ...
    }
  ],
  "skills": [
    {
      "id": "skill-uuid",
      "skill_set": "skill-set-uuid",
      "skill_level": "Advanced"
    }
  ]
}
```

### 63. Add Education Record
```http
POST /api/v1/seekers/education/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "institute_university_name": "Stanford University",
  "degree_type": "Bachelor",
  "field_of_study": "Computer Science",
  "academic_details": "Focus on Artificial Intelligence and Machine Learning",
  "percentage": "3.85",
  "start_date": "2013-09-01",
  "end_date": "2017-06-15"
}
```

**Degree Type Options:** `High School`, `Associate`, `Bachelor`, `Master`, `PhD`, `Certificate`, `Diploma`

**Note:** The `user_account` is automatically set to the current user.

### 64. List Education Records
```http
GET /api/v1/seekers/education/
Authorization: Bearer <access-token>
```

### 65. Get Education Record
```http
GET /api/v1/seekers/education/{id}/
Authorization: Bearer <access-token>
```

### 66. Update Education Record
```http
PUT /api/v1/seekers/education/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "institute_university_name": "Stanford University",
  "degree_type": "Master",
  "field_of_study": "Computer Science",
  "academic_details": "Specialized in Machine Learning",
  "percentage": "3.90",
  "start_date": "2017-09-01",
  "end_date": "2019-06-15"
}
```

### 67. Delete Education Record
```http
DELETE /api/v1/seekers/education/{id}/
Authorization: Bearer <access-token>
```

### 68. Add Experience Record
```http
POST /api/v1/seekers/experience/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "company_name": "Tech Innovations Inc",
  "position": "Senior Python Developer",
  "description": "Led development of RESTful APIs using Django and FastAPI. Mentored junior developers and conducted code reviews.",
  "job_location_city": "San Francisco",
  "job_location_country": "United States",
  "start_date": "2020-01-15",
  "end_date": "2023-08-30"
}
```

**Note:** Leave `end_date` as `null` for current positions. The `user_account` is automatically set to the current user.

### 69. List Experience Records
```http
GET /api/v1/seekers/experience/
Authorization: Bearer <access-token>
```

### 70. Get Experience Record
```http
GET /api/v1/seekers/experience/{id}/
Authorization: Bearer <access-token>
```

### 71. Update Experience Record
```http
PUT /api/v1/seekers/experience/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "company_name": "Tech Innovations Inc",
  "position": "Lead Python Developer",
  "description": "Updated description",
  "job_location_city": "San Francisco",
  "job_location_country": "United States",
  "start_date": "2020-01-15",
  "end_date": null
}
```

### 72. Delete Experience Record
```http
DELETE /api/v1/seekers/experience/{id}/
Authorization: Bearer <access-token>
```

### 73. Create Skill (Admin Only)
```http
POST /api/v1/seekers/skills/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "skill_name": "Python"
}
```

### 74. List All Skills
```http
GET /api/v1/seekers/skills/
```

### 75. Get Skill
```http
GET /api/v1/seekers/skills/{id}/
```

### 76. Update Skill (Admin Only)
```http
PUT /api/v1/seekers/skills/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "skill_name": "Python 3.x"
}
```

### 77. Delete Skill (Admin Only)
```http
DELETE /api/v1/seekers/skills/{id}/
Authorization: Bearer <access-token>
```

### 78. Add Skill to Seeker Profile
```http
POST /api/v1/seekers/seeker-skills/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "skill_set": "skill-uuid",
  "skill_level": "Advanced"
}
```

**Skill Levels:** `Beginner`, `Intermediate`, `Advanced`, `Expert`

**Note:** The `user_account` is automatically set to the current user.

### 79. List Seeker Skills
```http
GET /api/v1/seekers/seeker-skills/
Authorization: Bearer <access-token>
```

### 80. Get Seeker Skill
```http
GET /api/v1/seekers/seeker-skills/{id}/
Authorization: Bearer <access-token>
```

### 81. Update Seeker Skill Level
```http
PUT /api/v1/seekers/seeker-skills/{id}/
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "user_account": "user-uuid",
  "skill_set": "skill-uuid",
  "skill_level": "Expert"
}
```

### 82. Delete Seeker Skill
```http
DELETE /api/v1/seekers/seeker-skills/{id}/
Authorization: Bearer <access-token>
```

---

---

## 📊 Field Choices Reference

### User Account Fields

**User Types** (UserAccount.user_type)
- `job_seeker` - Job Seeker
- `company` - Company

**Sex/Gender** (UserAccount.sex)
- `M` - Male
- `F` - Female
- `Other` - Other

---

### Company Fields

**Company Status** (Company.status)
- `active` - Active
- `inactive` - Inactive
- `suspended` - Suspended

---

### Job Fields

**Salary Types** (JobPost.salary_type)
- `hourly` - Hourly
- `monthly` - Monthly
- `yearly` - Yearly

**Application Status** (JobPostActivity.application_status)
- `pending` - Pending (default)
- `reviewed` - Reviewed
- `accepted` - Accepted
- `rejected` - Rejected
- `withdrawn` - Withdrawn

**Skill Levels** (JobPostSkillSet.skill_level & SeekerSkillSet.skill_level)
- `Beginner` - Beginner
- `Intermediate` - Intermediate
- `Advanced` - Advanced
- `Expert` - Expert

---

### Seeker Fields

**Degree Types** (EducationData.degree_type)
- `High School` - High School
- `Associate` - Associate Degree
- `Bachelor` - Bachelor Degree
- `Master` - Master Degree
- `PhD` - PhD
- `Certificate` - Certificate
- `Diploma` - Diploma

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
    "password": "SmokeTest12345",
    "user_type": "job_seeker"
  }'

# Login
curl -X POST http://localhost:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SmokeTest12345"
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
- **Pagination:** List endpoints return `{count, next, previous, results}`. Default `page_size=20`, max `100`. Override via `?page_size=N&page=M`.
- Most endpoints require authentication via JWT Bearer token