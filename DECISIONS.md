# Technical Decisions

This document records the main implementation choices made to follow the contract in `openapi.yaml` and the MongoDB shapes in `DATA_MODEL.md`.

## 1. Employee identity and attendance key

The API uses the customer-supplied `emp_code` as the public employee identifier; MongoDB's internal `_id` is not exposed. Employees have a unique `emp_code` index. Attendance records use the natural key `(emp_code, date)`, enforced by a unique compound index, because the contract allows at most one attendance record per employee per attendance date.

## 2. Indexes and query shapes

Indexes are created at startup with stable names so startup can be repeated safely:

- `uq_employees_emp_code` — employee-code uniqueness.
- `ix_employees_joined_on` — joining-date filters.
- `ix_employees_department_emp` — department filtering and employee-code lookup.
- `uq_attendance_emp_date` — unique employee/date attendance key and matching lookups.
- `ix_attendance_date_emp` — date-based attendance listing and sorting.

The explain endpoint returns MongoDB's `executionStats` explain result for its supported operation. Index selection and execution time depend on the actual dataset and server; results from a small development dataset are useful smoke-test evidence, not a large-scale performance guarantee.

## 3. Duplicate requests and concurrent updates

Employee creation and punch-in handle duplicate-key errors as HTTP 409 in addition to normal request validation. The unique indexes are the final protection against simultaneous requests creating duplicate employee codes or employee/date attendance records.

Punch-out updates only a record whose `punch_out` is still null, so two concurrent punch-out requests cannot both successfully close the same open record. Attendance regularization uses a conditional update against the values read earlier, and appends the audit entry atomically with `$push`. If another request changes the record first, the later request returns HTTP 409 instead of silently replacing the first update or losing its history.

## 4. Time and attendance calculations

BSON datetimes represent instants in MongoDB; the HTTP API accepts and returns epoch milliseconds. Because PyMongo may return naive UTC datetimes, serialization explicitly treats those values as UTC. Calendar dates and shift times remain strings, and shift rules are calculated in IST.

- Attendance dates for overnight shifts are anchored to the date the shift started.
- Lateness is recorded only when punch-in is strictly more than 10 minutes after shift start; whole minutes are measured from shift start.
- Overtime is recorded only when punch-out is at least 30 minutes after shift end.
- Work hours use decimal half-up rounding to two places. `half_day` is true when rounded work hours are below 4.50.
- Attendance instants are truncated to whole-second precision as specified by the contract.

These calculations are applied when the relevant attendance operation occurs. Analytics use the stored derived values, as required by the data model.

## 5. Audit history

Punch-in and punch-out do not add manual-correction history entries. A successful regularization appends one entry containing the actor, reason, timestamp, and before/after values for fields that actually changed. If recalculating a correction changes derived fields such as `work_hours`, `late_minutes`, `overtime_minutes`, or `half_day`, those changes are included in the same audit entry. History is updated atomically with the correction.

## 6. Analytics definitions

- Monthly employee metrics count weekdays only for working days and present days; half-day records contribute 0.5. Leave, late, and overtime metrics use the stored record values specified by the contract.
- Department headcount includes employees who joined on or before the end of the reporting period, even if they have no attendance documents.
- Department trend returns one row per requested calendar date. A working day with headcount but no attendance has a zero attendance rate; weekends and dates with zero headcount have a null rate. The trailing seven-row moving average ignores null rates and uses only dates within the requested range.
- The late leaderboard uses standard competition ranking, so equal totals share a rank and the next rank is skipped. Department filtering is applied before ranking, the limit applies to rank so ties at the cutoff remain included, and `emp_code` breaks ordering ties deterministically.

## 7. Validation and error behavior

Pydantic and endpoint-level checks reject invalid employee details, timestamps, date ranges, statuses, and pagination values with HTTP 422. Missing employees, departments, or attendance records return the contract's 404 errors. Duplicate or conflicting writes return HTTP 409. The health endpoint pings MongoDB and returns HTTP 503 when the database cannot be reached.

## 8. Scaling approach

For the assignment's larger dataset, first evaluate explain plans and examined-document counts using representative seeded data, especially for date filters, aggregation lookups, sorting, and window stages. Retain bounded pagination and verify there are no unwanted collection scans on the required explain paths. Optimize demonstrated bottlenecks before adding complexity; consider sharding only if measured workload and deployment constraints justify it.

## Verification boundary

Manual smoke tests and explain checks were run against a small MongoDB Atlas test dataset. They do not replace a full automated regression suite or prove performance at 100x data volume. See `REVIEW.md` for the observed API results and known verification limits.
