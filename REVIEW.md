# Code Review & Verification

## Scope
Reviewed `app/main.py` against `openapi.yaml` and `DATA_MODEL.md`, focusing on API contract behavior, attendance calculations, correction history, analytics, pagination, indexes, and explain output.

## Findings and Fixes

### 1. Employee input and uniqueness
- Added request validation for employee code, email, name, department, shift times, joining date, and different shift start/end values.
- Duplicate employee codes return HTTP 409, including the database duplicate-key race path.
- Manual checks: invalid email returned 422; duplicate employee code returned 409.

### 2. Timestamp serialization and attendance calculations
- API timestamps are returned as epoch milliseconds; stored BSON datetimes are treated as UTC when serialized.
- Manual checks covered regular and overnight shifts, overtime calculation, regularization, and recording derived-field changes in history.
- Attendance listing showed integer epoch-millisecond values for `punch_in`, `punch_out`, and history timestamps.

### 3. Analytics contract
- Department summary and employee monthly analytics were exercised with October 2026 data.
- Department trend was exercised over an empty attendance range and returned the requested calendar dates.
- Empty result sets are not automatically failures; expected output depends on matching attendance data.

## Manual API Evidence

| Check | Observed result | Assessment |
|---|---|---|
| `GET /health` | `{"status":"ok"}` | Pass |
| `GET /employees?page=1&page_size=5` | `total=8`, `page=1`, `page_size=5`; `created_at` values are epoch milliseconds | Pass |
| `GET /attendance?page=1&page_size=5` | `total=4`; timestamp and history time values are epoch milliseconds | Pass |
| `GET /analytics/departments/summary?month=2026-10&department=Engineering` | `headcount=5`, `present_days=3`, `avg_work_hours=9.66`, `late_count=0`, `total_late_minutes=0`, `leave_count=0`, `on_duty_count=0` | Pass for observed data |
| `GET /analytics/employees/EMP1001/monthly?month=2026-10` | `working_days=22`, `present_days=0`, `total_overtime_minutes=50`, `attendance_pct=0` | Pass for observed data |
| Department trend for Engineering, 2026-10-20 through 2026-10-26 | Explain output showed seven densified dates and index usage for department and attendance lookups | Pass |
| Department summary explain for October 2026 / Engineering | Used `ix_employees_department_emp` and `uq_attendance_emp_date`; no collection scans reported | Pass |
| Late leaderboard explain for October 2026 / Engineering | Used `ix_attendance_date_emp`; 4 index keys and 4 documents examined, 1 ms reported; `late_count` is present in the pipeline | Pass for observed data |
| Employee monthly explain | Shared aggregation pipeline used by the endpoint and explain path; index scan observed on the sample database | Pass for observed data |

Additional manual edge checks included duplicate punch-in handling, invalid pagination, an invalid trend date range, unknown employee handling, and an overnight-shift regularization scenario.

## Limitations

- These are manual checks against the currently configured MongoDB Atlas database and its small test dataset, not an automated regression suite.
- Explain timings and examined-document counts reflect this dataset only; they do not establish performance under the assignment's larger grading dataset.
- The concurrent duplicate-create and concurrent punch-in protection paths rely on database unique indexes, but a simultaneous-request race test has not been recorded here.
- Before submission, run the grader or a repeatable test suite against the assignment's supported MongoDB version and seeded data if available.

## Conclusion

The observed smoke tests and explain checks are consistent with the expected API behavior for the cases listed above. This review is not a claim that every OpenAPI edge case or large-dataset performance requirement has been independently verified.
