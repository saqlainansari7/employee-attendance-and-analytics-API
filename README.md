# Employee Attendance & Analytics API

A REST API built with **FastAPI** and **MongoDB** to manage employee records, track attendance, regularize attendance entries, and generate employee and department analytics.

## Features

- Employee creation and paginated employee listing
- Employee punch-in and punch-out
- Attendance listing with filters and pagination
- Attendance regularization with change history
- Monthly employee attendance analytics
- Department-wise monthly summary
- Late-arrival leaderboard with ranking
- Department attendance trends with a 7-day moving average
- MongoDB query execution plans for performance analysis
- Database indexes for frequently queried fields
- Health endpoint to check API and database connectivity

## Tech Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic
- Uvicorn
- python-dotenv

## Prerequisites

- Python 3.11+
- MongoDB local instance or MongoDB Atlas account
- Git

## Project Setup

### 1. Clone the repository

```bash
git clone https://github.com/saqlainansari7/employee-attendance-and-analytics-API.git
cd employee-attendance-and-analytics-API
```

### 2. Create and activate a virtual environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb+srv://<username>:<password>@<cluster-url>/
MONGO_DB=attendance_db
```

Replace the placeholders with your MongoDB connection details. URL-encode special characters in the database password when required.

For local MongoDB, you can use:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

**Security:** Never commit `.env`, database credentials, or other secrets to GitHub.

### 5. Run the application

```bash
uvicorn app.main:app --port 8000
```

The API will be available at:

- Base URL: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

The application creates the configured MongoDB indexes during startup.

## API Endpoints

### Health

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API and MongoDB connectivity |

### Employees

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees with optional department filtering and pagination |

Example:

```http
GET /employees?department=Engineering&page=1&page_size=20
```

### Attendance

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/attendance/punch-in` | Record an employee's punch-in |
| POST | `/attendance/punch-out` | Record punch-out and calculate work duration |
| GET | `/attendance` | List attendance records with filters and pagination |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize an existing attendance record |

Example:

```http
GET /attendance?date_from=2026-10-01&date_to=2026-10-31&page=1&page_size=20
```

Attendance timestamps supplied through the API use epoch milliseconds.

### Employee Analytics

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve an employee's monthly attendance metrics |

Example:

```http
GET /analytics/employees/EMP1001/monthly?month=2026-10
```

### Department Analytics

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/analytics/departments/summary` | Retrieve department-wise monthly metrics |
| GET | `/analytics/departments/{department}/trend` | Retrieve daily attendance trends for a department |

Department summary example:

```http
GET /analytics/departments/summary?month=2026-10
```

Department trend example:

```http
GET /analytics/departments/Engineering/trend?from=2026-10-01&to=2026-10-07
```

The trend endpoint includes daily records, working-day indicators, headcount, attendance rate, and a 7-day moving average.

### Late-arrival Leaderboard

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/analytics/leaderboard/late` | Rank employees by total late minutes for a month |

Example:

```http
GET /analytics/leaderboard/late?month=2026-10&limit=10&department=Engineering
```

### Query Explain

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution statistics |

Supported endpoint names:

- `attendance_list`
- `employee_monthly`
- `department_summary`
- `late_leaderboard`
- `department_trend`

Example:

```http
GET /admin/explain/department_trend?department=Engineering&from=2026-10-01&to=2026-10-07
```

Use the parameters required by the selected endpoint. Explain output includes MongoDB execution-plan information useful for checking index usage and query performance.

## Data Storage

The API uses the `attendance_db` database by default.

| Collection | Purpose |
|---|---|
| `employees` | Employee details, department, shift timings, and joining date |
| `attendance_logs` | Attendance status, punch timestamps, work hours, late minutes, overtime, and regularization history |

Sample data files and the seeding utility are not included in this submission. Configure your own MongoDB database and provide the required environment variables before starting the API.

## Pagination

Paginated endpoints use `page` and `page_size`.

- `page` starts at 1.
- `page_size` must be between 1 and 100.
- Invalid pagination values return HTTP 422.

## Error Handling

The API uses HTTP status codes to communicate outcomes, including:

- `404 Not Found` — requested employee, attendance record, or department is missing
- `409 Conflict` — duplicate employee code or conflicting attendance operation
- `422 Unprocessable Entity` — invalid input or date range
- `503 Service Unavailable` — MongoDB is unavailable

## Database Indexes

The application creates indexes for employee lookup, joining-date queries, department filtering, attendance uniqueness, and attendance listing. These indexes help support common filtering, sorting, and aggregation operations.

## Development Notes

- Keep database credentials in environment variables.
- Do not commit `.env` or `.venv`.
- Use the interactive Swagger documentation to explore and test endpoints.
- Run automated tests before submitting changes.
- Validate analytics edge cases and query plans against the assignment's OpenAPI contract.
