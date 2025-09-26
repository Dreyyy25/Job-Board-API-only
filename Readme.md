# Job Board API

## Overview
This API provides a comprehensive job board platform where companies can post jobs and job seekers can apply for positions. The system supports multiple user types, detailed profiles, skill matching, and application tracking.

## Project Structure
```
jobApp/
├── apps/
│   ├── accounts/     # User management and authentication
│   ├── companies/    # Company profiles and business streams
│   ├── seekers/      # Job seeker profiles, education, experience
│   └── jobs/         # Job postings, applications, skill requirements
├── jobApp/           # Main Django project settings
└── requirements.txt  # Project dependencies
```

## Models Overview

### **Accounts App**
#### `UserAccount` 
Main user model with authentication and user type management
- UUID-based primary key
- Email-based authentication
- Built-in user type choices: 'job_seeker', 'company'
- Fields: email, password, user_type, date_of_birth, contact_number, sex, user_image_url
- Timestamps for creation and updates
- Simplified design using Django choices instead of separate UserType table

### **Companies App**
#### `BusinessStream`
Business categories/industries
- UUID-based primary key
- Unique business category names (Technology, Healthcare, etc.)

#### `Company`
Company profiles for business users
- UUID-based primary key
- One-to-one relationship with UserAccount
- Fields: company_name, business_stream, profile_description, website, contact_email
- Status options: active, inactive, suspended

#### `CompanyImages`
Multiple images for company profiles
- UUID-based primary key
- Multiple images per company
- Image URL storage

### **Seekers App**
#### `SeekerProfile`
Job seeker personal information
- User account as primary key (OneToOne)
- Fields: first_name, last_name, contact_details, goals, resume_url

#### `EducationData`
Educational background records
- UUID-based primary key
- Multiple education records per user
- Fields: institute_name, degree_type, field_of_study, percentage, dates
- Degree types: High School, Associate, Bachelor, Master, PhD, Certificate, Diploma

#### `ExperienceData`
Work experience records
- UUID-based primary key
- Multiple experience records per user
- Fields: company_name, position, description, location, dates

#### `SkillSet`
Master list of available skills
- UUID-based primary key
- Unique skill names

#### `SeekerSkillSet`
Job seeker skills with proficiency levels
- UUID-based primary key
- Links users to skills with levels
- Skill levels: Beginner, Intermediate, Advanced, Expert
- Unique constraint: one skill level per user per skill

### **Jobs App**
#### `JobType`
Employment types
- UUID-based primary key
- Types: Full-time, Part-time, Contract, Freelance

#### `JobLocation`
Job location details
- UUID-based primary key
- Fields: street_address, city, country, zip, country_code

#### `JobPost`
Main job posting model
- UUID-based primary key
- Links to Company, JobType, JobLocation
- Fields: job_title, job_description, salary range, deadline_date
- Salary types: hourly, monthly, yearly
- Status flags: is_published, is_active

#### `JobPostActivity`
Job applications from seekers
- UUID-based primary key
- Links UserAccount (applicant) to JobPost
- Application status: pending, reviewed, accepted, rejected, withdrawn
- Includes cover letter and timestamps
- Unique constraint: one application per user per job

#### `JobPostSkillSet`
Skill requirements for jobs
- UUID-based primary key
- Links JobPost to required skills
- Skill levels and required/optional flags

## API Documentation

For detailed API documentation including endpoints, request/response examples, and testing guides, see:

📖 **[API_DOCUMENTATION.md](API_DOCUMENTATION.md)**

### Quick API Overview
- **Base URL**: `http://localhost:8000/api/v1/`
- **Authentication**: Basic Authentication and Session Authentication
- **Format**: JSON requests and responses
- **40+ Endpoints** across 4 main modules: Accounts, Seekers, Companies, Jobs

## Database Configuration
- **PostgreSQL** database (recommended for production)
- **SQLite** support (for development)
- **UUID Primary Keys** for enhanced security
- **Proper Foreign Key Relationships** between models

### Environment Variables
Create a `.env` file in the project root:
```bash
# Database Configuration
DB_NAME=jobboard_db
DB_USER=your_username  
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Django Settings
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

## Installation & Setup

### Prerequisites
- Python 3.8+
- PostgreSQL 12+ (optional, can use SQLite for development)
- Git

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd jobApp
   ```

2. **Create virtual environment**
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

4. **Environment configuration**
   ```bash
   cp .env.example .env
   # Edit .env file with your database credentials
   ```

5. **Database setup**
   ```bash
   # Create database migrations
   python manage.py makemigrations accounts
   python manage.py makemigrations companies  
   python manage.py makemigrations seekers
   python manage.py makemigrations jobs
   
   # Apply migrations
   python manage.py migrate
   ```

6. **Create initial data**
   ```bash
   python manage.py shell
   ```
   ```python
   # In Django shell - create business streams
   from apps.companies.models import BusinessStream
   BusinessStream.objects.create(business_stream_name='Technology')
   BusinessStream.objects.create(business_stream_name='Healthcare')
   BusinessStream.objects.create(business_stream_name='Finance')
   
   # Create job types
   from apps.jobs.models import JobType
   JobType.objects.create(job_type_name='Full-time', description='Full-time employment')
   JobType.objects.create(job_type_name='Part-time', description='Part-time employment')
   JobType.objects.create(job_type_name='Contract', description='Contract work')
   JobType.objects.create(job_type_name='Freelance', description='Freelance work')
   ```

7. **Create superuser (optional)**
   ```bash
   python manage.py createsuperuser
   ```

8. **Run development server**
   ```bash
   python manage.py runserver
   ```

The API will be available at `http://localhost:8000/api/v1/`

## Testing

### Using curl
```bash
# Test registration
curl -X POST http://localhost:8000/api/v1/accounts/register/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123", "user_type": "job_seeker"}'

# Test login
curl -X POST http://localhost:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'

# Get job posts
curl -X GET http://localhost:8000/api/v1/jobs/job-posts/ \
  -H "Authorization: Basic <base64-encoded-credentials>"
```

### Using Postman
1. Import the API endpoints into Postman
2. Set up Basic Authentication with user credentials
3. Test CRUD operations on different endpoints

## Deployment

### Production Considerations
- Set `DEBUG=False` in settings
- Use strong `SECRET_KEY`
- Configure proper `ALLOWED_HOSTS`
- Set up proper database with connection pooling
- Use environment variables for sensitive data
- Set up proper logging
- Configure static file serving
- Use HTTPS in production

### Dependencies
```
Django==5.2.5
djangorestframework==3.16.1
djangorestframework-simplejwt==5.5.1
psycopg2-binary==2.9.10
PyJWT==2.10.1
python-dotenv==1.1.1
```

## API Features

### Core Functionality
- **User Management**: Registration, login, profile management with built-in user types
- **Company Profiles**: Business information, images, industry categorization
- **Job Seeker Profiles**: Personal info, education, experience, skills
- **Job Posting**: Create, search, filter job opportunities
- **Application System**: Apply for jobs, track application status
- **Skill Matching**: Link jobs with required skills and proficiency levels

### Advanced Features
- **Search & Filtering**: Full-text search on job titles and descriptions
- **UUID Primary Keys**: Enhanced security and scalability
- **Comprehensive Validation**: Input sanitization and business logic validation
- **Relationship Management**: Proper foreign key relationships between models
- **Dashboard Endpoints**: Consolidated data views for users and companies
- **Application Tracking**: Status management for job applications

### Technical Features
- **RESTful API Design**: Standard HTTP methods and status codes
- **Django REST Framework**: Robust serialization and viewsets
- **PostgreSQL Support**: Production-ready database with UUID support
- **Authentication**: Multiple authentication methods supported
- **Error Handling**: Comprehensive error responses with validation details
- **Modular Architecture**: Organized in separate Django apps for maintainability

## Contributing

### Development Guidelines
1. Follow PEP 8 style guidelines
2. Write comprehensive docstrings
3. Add unit tests for new features
4. Use meaningful commit messages
5. Update documentation for API changes

### Code Structure
- **Models**: Define in respective app models.py
- **Serializers**: Handle data validation and transformation
- **Views**: Implement business logic and API endpoints
- **URLs**: Organize routing in app-specific urls.py files

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions or issues:
1. Check the API documentation above
2. Review error responses for validation details  
3. Ensure proper authentication headers are included
4. Verify UUID formats in requests

## Version History

### v1.0.0
- Initial API implementation
- User management system
- Company and job seeker profiles
- Job posting and application system
- Basic search and filtering
- UUID-based primary keys
- Comprehensive validation