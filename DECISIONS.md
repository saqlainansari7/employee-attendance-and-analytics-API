# Technical Decisions

## 1. Indexes
I created a unique index on `employees.emp_code` to prevent duplicate employees and a unique compound index on `attendance_logs.emp_code` and `date` to prevent duplicate daily attendance. Additional indexes support date-based attendance queries and department-based employee lookups. These indexes improve query efficiency while maintaining data integrity.

## 2. Concurrent Identical Punch-Ins
If two identical punch-in requests arrive simultaneously, the unique compound index ensures that only one attendance record can be created. The duplicate-key error should be handled and returned as an appropriate HTTP response instead of creating duplicate records.

## 3. Leaderboard Ties
Employees with the same total late minutes should receive the same rank. The leaderboard should use ranking semantics that preserve ties, with `emp_code` as a deterministic secondary sort key for consistent ordering.

## 4. Department Summary Counts
Department headcount should include employees who joined on or before the end of the requested month. Employees without attendance logs should still contribute to headcount, while attendance metrics should be calculated only from applicable attendance records.

## 5. Scaling to 100x Data
I would first inspect query execution plans and verify index usage with representative data. I would optimize aggregation pipelines, avoid unnecessary document processing, and ensure pagination is bounded. If the dataset outgrows a single database deployment, I would evaluate hardware scaling, workload monitoring, archival policies, and sharding based on measured bottlenecks.