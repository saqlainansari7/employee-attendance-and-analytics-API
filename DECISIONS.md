# Technical Decisions

## 1. Indexes
I created a unique index on `employees.emp_code` and a unique compound index on `attendance_logs.emp_code` and `date` to protect data integrity. Additional indexes support department filtering and date-based attendance queries.

## 2. Concurrent Punch-Ins
Concurrent identical punch-ins are protected by the unique compound index. One insert succeeds; a duplicate-key error is translated into HTTP 409 so duplicate daily records cannot be created.

## 3. Leaderboard Ties
Employees with equal total late minutes receive the same rank. Results use `emp_code` as a secondary sort key for deterministic ordering. The limit is applied to rank so ties at the cutoff can remain included.

## 4. Department Summary
Headcount includes employees who joined on or before the end of the selected month, even when they have no attendance logs. Attendance metrics are calculated from applicable records only.

## 5. Scaling
For 100x data, I would inspect execution statistics on representative data, confirm index scans, and check for collection scans. I would then optimize measured bottlenecks, retain bounded pagination, monitor resource use, and consider sharding only if a single deployment becomes insufficient.