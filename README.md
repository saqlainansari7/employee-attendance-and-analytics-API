# Employee Attendance & Analytics API

A FastAPI and MongoDB REST API for employee management, attendance capture, manual attendance correction, and workforce analytics. This repository implements the HROne engineering assignment contract defined in `openapi.yaml` and `DATA_MODEL.md`.

## Features

- Create employees and list them with department filtering and pagination.
- Record punch-in and punch-out events; calculate late minutes, work hours, overtime, and half-day status.
- List attendance by employee, date range, and status.
- Correct attendance records while preserving an append-only audit history of fields that actually changed.
- Generate employee monthly metrics, department monthly summaries, late-arrival rankings, and daily department trends.
- Inspect MongoDB execution plans for supported endpoints with `executionStats`.
- Create required MongoDB indexes idempotently at application startup.

## Technology

- Python 3.11+
- FastAPI and Pydantic
- PyMongo
- MongoDB (local instance or Atlas)
- Uvicorn and python-dotenv

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/saqlainansari7/employee-attendance-and-analytics-API.git
cd employee-attendance-and-analytics-API
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure MongoDB

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb+srv://<username>:<password>@<cluster-url>/
MONGO_DB=attendance_db
```

For a local MongoDB instance, use:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

Replace placeholders with your own connection details. URL-encode special characters in the password when needed. Existing process environment variables take precedence over values in `.env`.

**Security:** Never commit `.env`, database credentials, virtual environments, or database dumps.

### 5. Start the API

Run the assignment command:

```bash
uvicorn app.main:app --port 8000
```

Local URLs:

- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Readiness check: http://127.0.0.1:8000/health

At startup, the application creates the indexes it needs. `/health` returns `{"status":"ok"}` only when MongoDB responds to a ping.

## API endpoints

All instants in requests and responses use integer epoch milliseconds. Calendar dates use `YYYY-MM-DD`, month filters use `YYYY-MM`, and shift times use 24-hour `HH:MM` in IST. Employee records are identified by `emp_code`; MongoDB's internal `_id` is not part of the API.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API and MongoDB readiness |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees; optional `department`, `page`, `page_size` |
| POST | `/attendance/punch-in` | Create an attendance record for punch-in |
| POST | `/attendance/punch-out` | Punch out and compute attendance values |
| GET | `/attendance` | List attendance; optional `emp_code`, `date_from`, `date_to`, `status`, pagination |
| PATCH | `/attendance/{emp_code}/{date}` | Correct a record and append to its history |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly metrics for one employee |
| GET | `/analytics/departments/summary` | Department monthly summary |
| GET | `/analytics/leaderboard/late` | Rank employees by total late minutes |
| GET | `/analytics/departments/{department}/trend` | Daily department attendance trend and 7-day moving average |
| GET | `/admin/explain/{endpoint}` | MongoDB execution plan for a supported query or aggregation |

### Example requests

List Engineering employees:

```http
GET /employees?department=Engineering&page=1&page_size=20
```

List October attendance:

```http
GET /attendance?date_from=2026-10-01&date_to=2026-10-31&page=1&page_size=20
```

Get employee monthly analytics:

```http
GET /analytics/employees/EMP1001/monthly?month=2026-10
```

Get the Engineering department summary:

```http
GET /analytics/departments/summary?month=2026-10&department=Engineering
```

Get a seven-day department trend:

```http
GET /analytics/departments/Engineering/trend?from=2026-10-01&to=2026-10-07
```

Get the late leaderboard:

```http
GET /analytics/leaderboard/late?month=2026-10&limit=10&department=Engineering
```

Explain a department trend query:

```http
GET /admin/explain/department_trend?department=Engineering&from=2026-10-01&to=2026-10-07
```

The explain endpoint supports `attendance_list`, `employee_monthly`, `department_summary`, `late_leaderboard`, and `department_trend`. Supply the parameters required for the selected endpoint. The response is MongoDB's raw explain output with execution statistics; results depend on the database contents and indexes.

## Business rules implemented

- Shift calculations and attendance dates use IST. Overnight shifts belong to the date on which the shift started.
- The lateness grace period is 10 minutes. Late minutes are recorded only when the punch-in is strictly more than 10 minutes after shift start; the value is measured from shift start and floored to whole minutes.
- Overtime is recorded only when the punch-out is at least 30 whole minutes beyond shift end.
- Work hours are calculated from punch timestamps and rounded to two decimal places using half-up rounding. `half_day` is true when the rounded hours are below 4.50.
- `PRESENT`, `WFH`, and `ON_DUTY` count as presence. Monthly present-day metrics count weekdays only; weekend records can still contribute to late and overtime totals.
- Headcount includes employees whose `joined_on` is on or before the end of the relevant reporting period, including employees without attendance logs.
- Attendance correction history records only manual corrections and contains a before/after pair for each field that actually changed.
- Pagination starts at page 1; `page_size` is limited to 100.

For the authoritative route schemas and full R1–R10 rules, see [`openapi.yaml`](openapi.yaml). For MongoDB document structure and field types, see [`DATA_MODEL.md`](DATA_MODEL.md).

## MongoDB indexes

The application creates these indexes at startup (if they do not already exist):

| Collection | Index | Purpose |
|---|---|---|
| `employees` | `uq_employees_emp_code` (unique) | Enforce unique employee codes |
| `employees` | `ix_employees_joined_on` | Support joining-date filters |
| `employees` | `ix_employees_department_emp` | Department filtering and employee-code lookup |
| `attendance_logs` | `uq_attendance_emp_date` (unique compound) | Enforce one record per employee per attendance date and support lookup |
| `attendance_logs` | `ix_attendance_date_emp` | Support date-based attendance queries and sorting |

Duplicate-key errors are translated to HTTP 409 for duplicate employee creation and duplicate punch-ins. The unique attendance index is the final safeguard against two records for the same `emp_code` and attendance date.

## Verification notes

Manual checks were performed against a small MongoDB Atlas test dataset. Observed checks included the health endpoint, employee and attendance pagination, employee monthly analytics, department summary, an empty-range department trend, regular and overnight shift calculations, regularization history, validation errors, duplicate handling, and explain plans showing index use for the exercised queries.

These are manual smoke-test observations, not a comprehensive automated regression suite or a performance guarantee for a large seeded dataset. See [`REVIEW.md`](REVIEW.md) for the recorded evidence and limitations.

## Repository files

- `app/main.py` — FastAPI application and MongoDB operations
- `openapi.yaml` — assignment API contract and business rules
- `DATA_MODEL.md` — MongoDB schema and seeded-data expectations
- `DECISIONS.md` — implementation decisions and trade-offs
- `REVIEW.md` — code review observations and verification evidence
- `requirements.txt` — Python dependencies

Sample data and a seed utility are not included. Configure your own MongoDB database using `MONGO_URI` and `MONGO_DB` before running the application.
