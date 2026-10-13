"""

Employee Attendance & Analytics API - STARTER



Run:  uvicorn app.main:app --port 8000

Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)



This file was written quickly by a colleague who has left the company. The happy path

works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,

openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.

"""

import os
import json
import re
from bson.json_util import dumps
from datetime import datetime, time, timedelta, timezone
from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from datetime import date
from datetime import timezone, timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@app.on_event("startup")
def create_indexes():

    # Employees: employee code must be unique

    db.employees.create_index(
    [("emp_code", 1)],
    unique=True,
    name="uq_employees_emp_code"
)

    db.employees.create_index(
    [("joined_on", 1)],
    name="ix_employees_joined_on"
)




    # Attendance: one record per employee per attendance date

    db.attendance_logs.create_index(

        [("emp_code", 1), ("date", 1)],

        unique=True,

        name="uq_attendance_emp_date"

    )



    # Attendance listing: date descending, employee code ascending

    db.attendance_logs.create_index(

        [("date", -1), ("emp_code", 1)],

        name="ix_attendance_date_emp"

    )



    # Employee department filtering and sorted listing

    db.employees.create_index(

        [("department", 1), ("emp_code", 1)],

        name="ix_employees_department_emp"

    )







# --------------------------------------------------------------------------- #

# Helpers

# --------------------------------------------------------------------------- #

def get_attendance_date_for_shift(
    local_punch_in: datetime,
    shift_start: str,
    shift_end: str
) -> date:
    """Resolve the IST attendance date, including overnight shifts."""
    local_punch_in = local_punch_in.astimezone(IST)
    start_hm = tuple(map(int, shift_start.split(":")))
    end_hm = tuple(map(int, shift_end.split(":")))
    attendance_date = local_punch_in.date()

    if (
        end_hm <= start_hm
        and (local_punch_in.hour, local_punch_in.minute) < end_hm
    ):
        attendance_date -= timedelta(days=1)

    return attendance_date


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: date
) -> int:
    """Return whole minutes since shift start when more than 10 minutes late."""
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    local_in = punch_in.astimezone(IST)
    h, m = map(int, shift_start.split(":"))
    shift_start_dt = datetime.combine(
        attendance_date, time(h, m), tzinfo=IST
    )

    late_seconds = (local_in - shift_start_dt).total_seconds()
    return int(late_seconds // 60) if late_seconds > 600 else 0





def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:

    return round((punch_out - punch_in).total_seconds() / 3600, 2)





def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:

    h, m = map(int, shift_end.split(":"))

    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)

    return max(0, int((punch_out - end).total_seconds() / 60))





# --------------------------------------------------------------------------- #

# Models

# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    shift_end: str = Field(
        default="18:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    joined_on: str

    @field_validator("name", "department")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("joined_on")
    @classmethod
    def joined_on_must_be_a_real_iso_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("joined_on must be a valid YYYY-MM-DD date") from exc

        if parsed.isoformat() != value:
            raise ValueError("joined_on must be a valid YYYY-MM-DD date")
        return value

    @model_validator(mode="after")
    def shifts_must_differ(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must be different")
        return self





class PunchInIn(BaseModel):

    emp_code: str

    punched_at: Optional[int] = Field(default=None, strict=True)

    status: str = "PRESENT"





class PunchOutIn(BaseModel):

    emp_code: str

    punched_at: Optional[int] = Field(default=None, strict=True)





class RegularizeIn(BaseModel):

    reason: str

    regularized_by: str

    status: Optional[str] = None

    punch_in: Optional[int] = Field(default=None, strict=True)

    punch_out: Optional[int] = Field(default=None, strict=True)





# --------------------------------------------------------------------------- #

# Endpoints provided

# --------------------------------------------------------------------------- #



@app.get("/health")

def health():

    try:

        client.admin.command("ping")

        return {"status": "ok"}

    except PyMongoError:

        raise HTTPException(

            status_code=503,

            detail="MongoDB unavailable"

        )







@app.post("/employees", status_code=201)

def create_employee(body: EmployeeIn):

    if db.employees.find_one({"emp_code": body.emp_code}):

        raise HTTPException(409, "emp_code already exists")

    doc = body.model_dump()

    doc["created_at"] = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        # Another concurrent request may have inserted this emp_code
        # after the initial lookup; preserve the API's 409 contract.
        raise HTTPException(status_code=409, detail="emp_code already exists")

    doc.pop("_id", None)

    # The API contract requires created_at as epoch milliseconds.
    created_at = doc.get("created_at")
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        doc["created_at"] = int(created_at.timestamp() * 1000)

    return doc







@app.get("/employees")

def list_employees(

    department: Optional[str] = None,

    page: int = 1,

    page_size: int = 20

):

    if page < 1:

        raise HTTPException(status_code=422, detail="page must be >= 1")



    if page_size < 1 or page_size > 100:

        raise HTTPException(

            status_code=422,

            detail="page_size must be between 1 and 100"

        )



    query = {}

    if department is not None:

        query["department"] = department



    skip = (page - 1) * page_size



    total = db.employees.count_documents(query)



    items = list(

        db.employees.find(query, {"_id": 0})

        .sort("emp_code", 1)

        .skip(skip)

        .limit(page_size)

    )



    for item in items:

        created_at = item.get("created_at")

        if created_at is not None:

            item["created_at"] = int(

                created_at.replace(tzinfo=timezone.utc).timestamp() * 1000

            )



    return {

        "items": items,

        "total": total,

        "page": page,

        "page_size": page_size

    }







@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    employee = db.employees.find_one({"emp_code": body.emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.status not in ("PRESENT", "WFH", "ON_DUTY"):
        raise HTTPException(status_code=422, detail="Invalid punch-in status")

    if body.punched_at is not None and (
        isinstance(body.punched_at, bool)
        or not isinstance(body.punched_at, int)
        or not 100000000000 <= body.punched_at <= 4102444800000
    ):
        raise HTTPException(status_code=422, detail="punched_at must be epoch milliseconds")

    ts = (
        datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc)
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    ).replace(microsecond=0)
    local_ts = ts.astimezone(IST)
    shift_start = employee.get("shift_start", "09:30")
    shift_end = employee.get("shift_end", "18:30")
    attendance_date = get_attendance_date_for_shift(
        local_ts, shift_start, shift_end
    )
    date_str = attendance_date.isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, shift_start, attendance_date),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Already punched in for this date")

    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": int(ts.timestamp() * 1000),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": doc["late_minutes"],
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }


@app.post("/attendance/punch-out")

def punch_out(body: PunchOutIn):

    # Check whether the employee exists

    employee = db.employees.find_one(

        {"emp_code": body.emp_code}

    )



    if not employee:

        raise HTTPException(

            status_code=404,

            detail="Employee not found"

        )



    # Use the supplied epoch milliseconds or current time

    if body.punched_at is not None:

        if (

            isinstance(body.punched_at, bool)

            or not isinstance(body.punched_at, int)

            or body.punched_at < 100000000000

            or body.punched_at > 4102444800000

        ):

            raise HTTPException(

                status_code=422,

                detail="punched_at must be epoch milliseconds"

            )



        punch_out_time = datetime.fromtimestamp(
            body.punched_at / 1000, tz=timezone.utc
        )

    else:

        punch_out_time = datetime.now(timezone.utc)



    # Store and calculate at whole-second precision

    punch_out_time = punch_out_time.replace(microsecond=0)



    # Find the most recent open attendance record

    record = db.attendance_logs.find_one(

        {

            "emp_code": body.emp_code,

            "punch_in": {"$ne": None, "$lte": punch_out_time},

            "punch_out": None

        },

        sort=[("punch_in", -1)]

    )



    if not record:
        # If an open punch-in exists but the supplied punch-out instant is
        # not after it, report the contract's 422 instead of a misleading 404.
        latest_open_record = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$ne": None},
                "punch_out": None
            },
            sort=[("punch_in", -1)]
        )
        if latest_open_record:
            latest_punch_in = latest_open_record["punch_in"]
            if latest_punch_in.tzinfo is None:
                latest_punch_in = latest_punch_in.replace(tzinfo=timezone.utc)
            if punch_out_time <= latest_punch_in.astimezone(timezone.utc):
                raise HTTPException(
                    status_code=422,
                    detail="Punch-out must be after punch-in and within 24 hours"
                )

        raise HTTPException(
            status_code=404,
            detail="No open punch-in record found"
        )



   
    punch_in_time = record["punch_in"]

    # MongoDB may return a naive datetime.
    # Treat naive stored values as UTC.
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    # Ensure both datetimes use UTC.
    punch_in_time = punch_in_time.astimezone(timezone.utc)
    punch_out_time = punch_out_time.astimezone(timezone.utc)

    # Reject invalid punch-out times
    duration_seconds = (
        punch_out_time - punch_in_time
    ).total_seconds()




    if duration_seconds <= 0 or duration_seconds > 24 * 3600:

        raise HTTPException(

            status_code=422,

            detail="Punch-out must be after punch-in and within 24 hours"

        )



    # Calculate work hours using half-up rounding

    from decimal import Decimal, ROUND_HALF_UP



    work_hours = float(

        (Decimal(str(duration_seconds)) / Decimal("3600"))

        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    )



    # Calculate overtime relative to the employee's shift

    shift_start = employee.get("shift_start", "09:30")

    shift_end = employee.get("shift_end", "18:30")



    start_h, start_m = map(int, shift_start.split(":"))

    end_h, end_m = map(int, shift_end.split(":"))



    # Shift times are defined in IST. Build the shift end from the
    # attendance date (the shift's start date), not from the UTC punch-in.
    shift_end_time = datetime.combine(
        date.fromisoformat(record["date"]),
        time(end_h, end_m),
        tzinfo=IST
    )

    # Overnight shift: its end falls on the day after the attendance date.
    if (end_h, end_m) <= (start_h, start_m):
        shift_end_time += timedelta(days=1)

    # Compare absolute instants in UTC so the IST offset is applied correctly.
    shift_end_time_utc = shift_end_time.astimezone(timezone.utc)
    overtime_elapsed = int(
        (punch_out_time - shift_end_time_utc).total_seconds() // 60
    )



    overtime_minutes = (

        overtime_elapsed if overtime_elapsed >= 30 else 0

    )



    half_day = work_hours < 4.50



    # Atomic update prevents concurrent punch-outs from both succeeding

    result = db.attendance_logs.update_one(

        {

            "_id": record["_id"],

            "punch_out": None

        },

        {

            "$set": {

                "punch_out": punch_out_time,

                "work_hours": work_hours,

                "overtime_minutes": overtime_minutes,

                "half_day": half_day

            }

        }

    )



    if result.modified_count != 1:

        raise HTTPException(

            status_code=409,

            detail="Attendance record was already punched out"

        )



    # Return the attendance record without MongoDB's internal _id

    updated = db.attendance_logs.find_one(

        {"_id": record["_id"]},

        {"_id": 0}

    )



    def to_epoch_ms(value):
        if value is None:
            return None

        # PyMongo may return BSON datetimes as naive UTC values.
        # Attach UTC explicitly before converting to epoch milliseconds.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return int(value.timestamp() * 1000)



    return {

        "emp_code": updated["emp_code"],

        "date": updated["date"],

        "status": updated["status"],

        "punch_in": to_epoch_ms(updated.get("punch_in")),

        "punch_out": to_epoch_ms(updated.get("punch_out")),

        "work_hours": updated.get("work_hours"),

        "late_minutes": updated.get("late_minutes", 0),

        "overtime_minutes": updated.get("overtime_minutes", 0),

        "half_day": updated.get("half_day", False),

        "history": updated.get("history", [])

    }









@app.get("/attendance")

def list_attendance(

    emp_code: Optional[str] = None,

    date_from: Optional[str] = None,

    date_to: Optional[str] = None,

    status: Optional[str] = None,

    page: int = 1,

    page_size: int = 20

):

    from datetime import date



    if page < 1:

        raise HTTPException(status_code=422, detail="page must be >= 1")



    if page_size < 1 or page_size > 100:

        raise HTTPException(

            status_code=422,

            detail="page_size must be between 1 and 100"

        )



    query = {}



    if emp_code:

        query["emp_code"] = emp_code



    if status:

        if status not in ("PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"):

            raise HTTPException(status_code=422, detail="Invalid status")

        query["status"] = status



    for field, value in (

        ("date_from", date_from),

        ("date_to", date_to)

    ):

        if value is not None:

            try:

                date.fromisoformat(value)

            except ValueError:

                raise HTTPException(

                    status_code=422,

                    detail=f"{field} must be YYYY-MM-DD"

                )



    if date_from and date_to and date_from > date_to:

        raise HTTPException(

            status_code=422,

            detail="date_from must be <= date_to"

        )



    if date_from or date_to:

        query["date"] = {}

        if date_from:

            query["date"]["$gte"] = date_from

        if date_to:

            query["date"]["$lte"] = date_to



    total = db.attendance_logs.count_documents(query)

    skip = (page - 1) * page_size



    records = list(

        db.attendance_logs.find(query, {"_id": 0})

        .sort([("date", -1), ("emp_code", 1)])

        .skip(skip)

        .limit(page_size)

    )



    def to_epoch_ms(value):

        if value is None:

            return None

        if value.tzinfo is None:

            value = value.replace(tzinfo=timezone.utc)

        return int(value.timestamp() * 1000)



    items = []



    for record in records:

        record["punch_in"] = to_epoch_ms(record.get("punch_in"))

        record["punch_out"] = to_epoch_ms(record.get("punch_out"))



        history = record.get("history", [])

        for entry in history:

            entry["at"] = to_epoch_ms(entry.get("at"))

            for change in entry.get("changes", {}).values():

                for key in ("from", "to"):

                    if isinstance(change.get(key), datetime):

                        change[key] = to_epoch_ms(change[key])



        record.setdefault("work_hours", None)

        record.setdefault("late_minutes", 0)

        record.setdefault("overtime_minutes", 0)

        record.setdefault("half_day", False)

        record.setdefault("history", [])



        items.append(record)



    return {

        "items": items,

        "total": total,

        "page": page,

        "page_size": page_size

    }





@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeIn

):
    # Validate date
    try:

        attendance_date = datetime.strptime(date, "%Y-%m-%d").date()

        if attendance_date.isoformat() != date:

            raise ValueError

    except ValueError:

        raise HTTPException(

            status_code=422,

            detail="date must be YYYY-MM-DD"

        )



    # Validate request fields

    if not 5 <= len(body.reason.strip()) <= 200:

        raise HTTPException(

            status_code=422,

            detail="reason must be between 5 and 200 characters"

        )



    if not 1 <= len(body.regularized_by.strip()) <= 50:

        raise HTTPException(

            status_code=422,

            detail="regularized_by must be between 1 and 50 characters"

        )



    allowed_statuses = {

        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"

    }



    if body.status is not None and body.status not in allowed_statuses:

        raise HTTPException(

            status_code=422,

            detail="Invalid attendance status"

        )



    employee = db.employees.find_one({"emp_code": emp_code})

    if not employee:

        raise HTTPException(status_code=404, detail="Employee not found")



    record = db.attendance_logs.find_one({

        "emp_code": emp_code,

        "date": date

    })



    if not record:

        raise HTTPException(

            status_code=404,

            detail="Attendance record not found"

        )



    old_status = record.get("status", "PRESENT")

    new_status = body.status if body.status is not None else old_status



    def normalize_datetime(value):

        if value is None:

            return None

        if value.tzinfo is None:

            # Existing naive MongoDB datetimes are interpreted as UTC

            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc).replace(microsecond=0)



    old_in = normalize_datetime(record.get("punch_in"))

    old_out = normalize_datetime(record.get("punch_out"))





    def parse_epoch(value, field_name):

        if value is None:

            return None



        if (

            isinstance(value, bool)

            or not isinstance(value, int)

            or value < 100000000000

            or value > 4102444800000

        ):

            raise HTTPException(

                status_code=422,

                detail=f"{field_name} must be epoch milliseconds"

            )



        return datetime.fromtimestamp(

            value / 1000,

            tz=timezone.utc

        ).replace(microsecond=0)



    new_in = (

        parse_epoch(body.punch_in, "punch_in")

        if body.punch_in is not None else old_in

    )

    new_out = (

        parse_epoch(body.punch_out, "punch_out")

        if body.punch_out is not None else old_out

    )



    # ABSENT and LEAVE must not have punch times

    if new_status in ("ABSENT", "LEAVE"):

        if body.punch_in is not None or body.punch_out is not None:

            raise HTTPException(

                status_code=422,

                detail="ABSENT/LEAVE cannot include punch times"

            )

        new_in = None

        new_out = None



    # Presence statuses require punch-in

    elif new_in is None:

        raise HTTPException(

            status_code=422,

            detail="Presence status requires punch_in"

        )



    if new_in is not None and new_in.tzinfo is None:

        new_in = new_in.replace(tzinfo=timezone.utc)



    if new_out is not None and new_out.tzinfo is None:

        new_out = new_out.replace(tzinfo=timezone.utc)



    if new_in is not None:

        new_in = new_in.replace(microsecond=0)



        # Validate the R1 attendance date, including after-midnight punches
        # that belong to the previous day's overnight shift.
        local_in = new_in.astimezone(IST)
        shift_start_for_date = employee.get("shift_start", "09:30")
        shift_end_for_date = employee.get("shift_end", "18:30")
        expected_attendance_date = get_attendance_date_for_shift(
            local_in, shift_start_for_date, shift_end_for_date
        )

        if expected_attendance_date != attendance_date:
            raise HTTPException(
                status_code=422,
                detail="punch_in must belong to the attendance date"
            )



    if new_out is not None:

        new_out = new_out.replace(microsecond=0)



        if new_in is None:

            raise HTTPException(

                status_code=422,

                detail="punch_out requires punch_in"

            )



        duration = (new_out - new_in).total_seconds()

        if duration <= 0 or duration > 24 * 3600:

            raise HTTPException(

                status_code=422,

                detail="punch_out must be after punch_in and within 24 hours"

            )



    # Build a history entry containing only changed fields

    changes = {}



    def epoch_ms(value):
        if value is None:
            return None

        # PyMongo may return naive datetimes that represent UTC.
        # Attach UTC explicitly to avoid a local-time offset on Windows.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return int(value.timestamp() * 1000)



    if new_status != old_status:

        changes["status"] = {"from": old_status, "to": new_status}



    if new_in != old_in:

        changes["punch_in"] = {

            "from": epoch_ms(old_in),

            "to": epoch_ms(new_in)

        }



    if new_out != old_out:

        changes["punch_out"] = {

            "from": epoch_ms(old_out),

            "to": epoch_ms(new_out)

        }



    if not changes:

        raise HTTPException(

            status_code=422,

            detail="Request does not change attendance"

        )







    # Recompute derived fields

    late_minutes = 0

    work_hours = None

    overtime_minutes = 0

    half_day = False



    if new_in is not None and new_status in ("PRESENT", "WFH", "ON_DUTY"):

        shift_start = employee.get("shift_start", "09:30")

        shift_end = employee.get("shift_end", "18:30")



        sh, sm = map(int, shift_start.split(":"))

        eh, em = map(int, shift_end.split(":"))



        local_in = new_in.astimezone(IST)

        local_out = (

            new_out.astimezone(IST)

            if new_out is not None

            else None

        )



        # Shift start is defined on the attendance date (R1).
        shift_start_dt = datetime.combine(
            attendance_date, time(sh, sm), tzinfo=IST
        )

        # Late calculation: strictly more than 10 minutes late

        late_seconds = (local_in - shift_start_dt).total_seconds()

        if late_seconds > 600:

            late_minutes = int(late_seconds // 60)

        else:

            late_minutes = 0





        if new_out is not None:

            # Calculate actual work duration

            duration_seconds = (new_out - new_in).total_seconds()



            if duration_seconds <= 0:

                raise HTTPException(

                    status_code=422,

                    detail="punch_out must be after punch_in"

                )



            raw_hours = Decimal(str(duration_seconds)) / Decimal("3600")

            work_hours = float(

                raw_hours.quantize(

                    Decimal("0.01"),

                    rounding=ROUND_HALF_UP

                )

            )



            half_day = work_hours < 4.50



            # Shift end is anchored to the shift's attendance date.
            shift_end_dt = datetime.combine(
                attendance_date, time(eh, em), tzinfo=IST
            )

            if (eh, em) <= (sh, sm):
                shift_end_dt += timedelta(days=1)



            shift_end_utc = shift_end_dt.astimezone(timezone.utc)



            overtime_seconds = (

                new_out - shift_end_utc

            ).total_seconds()



            # Overtime applies only when at least 30 minutes

            if overtime_seconds >= 1800:

                overtime_minutes = int(overtime_seconds // 60)



    now = datetime.now(timezone.utc).replace(microsecond=0)



    update_fields = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day
    }

    # Audit every derived value that changes as a result of correcting
    # status or punch times, not only the directly edited input fields.
    old_derived_values = {
        "work_hours": record.get("work_hours"),
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False)
    }
    for field, old_value in old_derived_values.items():
        new_value = update_fields[field]
        if old_value != new_value:
            changes[field] = {
                "from": old_value,
                "to": new_value
            }

    history_entry = {

        "at": now,

        "by": body.regularized_by.strip(),

        "reason": body.reason.strip(),

        "changes": changes

    }



    # Update only if the record still matches the version we read.

    # This avoids silently overwriting concurrent changes.

    result = db.attendance_logs.update_one(

        {

            "_id": record["_id"],

            "status": old_status,

            "punch_in": old_in,

            "punch_out": old_out

        },

        {

            "$set": update_fields,

            "$push": {"history": history_entry}

        }

    )



    if result.modified_count != 1:

        raise HTTPException(

            status_code=409,

            detail="Attendance changed concurrently; retry the request"

        )



    updated = db.attendance_logs.find_one(

        {"_id": record["_id"]},

        {"_id": 0}

    )



    def convert_history(entry):

        entry["at"] = epoch_ms(entry.get("at"))

        for change in entry.get("changes", {}).values():

            for key in ("from", "to"):

                if isinstance(change.get(key), datetime):

                    change[key] = epoch_ms(change[key])

        return entry



    updated["punch_in"] = epoch_ms(updated.get("punch_in"))

    updated["punch_out"] = epoch_ms(updated.get("punch_out"))

    updated["history"] = [

        convert_history(entry) for entry in updated.get("history", [])

    ]
    return updated

def build_employee_monthly_pipeline(
    emp_code: str,
    month_start: date,
    next_month: date
):
    """Build the shared database aggregation for employee monthly analytics."""
    return [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lt": next_month.isoformat()
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {
                                        "$in": [
                                            {
                                                "$dayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date"
                                                    }
                                                }
                                            },
                                            [2, 3, 4, 5, 6]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$late_minutes", 0]},
                                    0
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
):
    # Check whether employee exists.
    employee = db.employees.find_one(
        {"emp_code": emp_code},
        {"_id": 0, "emp_code": 1, "joined_on": 1}
    )

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Find the selected month's date range.
    year, month_number = map(int, month.split("-"))
    month_start = date(year, month_number, 1)

    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)

    last_day = (next_month - date.resolution).day
    joined_on = date.fromisoformat(employee["joined_on"])

    # Count weekdays from the later of joining date and month start.
    first_day = max(month_start, joined_on)
    working_days = 0

    current_day = first_day
    while current_day < next_month:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += date.resolution

    
    # Use the same aggregation builder as the explain endpoint.
    pipeline = build_employee_monthly_pipeline(
        emp_code, month_start, next_month
    )
    records = list(db.attendance_logs.aggregate(pipeline))


    summary = records[0] if records else {}

    present_days = summary.get("present_days", 0)
    attendance_pct = None

    if working_days > 0:
        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal("100") /
             Decimal(working_days)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": summary.get("leave_days", 0),
        "late_count": summary.get("late_count", 0),
        "total_late_minutes": summary.get("total_late_minutes", 0),
        "total_overtime_minutes": summary.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }



@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None
):
    # Validate month and calculate its date range.
    year, month_number = map(int, month.split("-"))
    month_start = date(year, month_number, 1)

    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)

    month_end = next_month - date.resolution

    # Start with employees who have joined by month-end.
    employee_match = {
        "joined_on": {"$lte": month_end.isoformat()}
    }

    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},

        # Join each employee with their attendance for this month.
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", month_start.isoformat()]},
                                    {"$lt": ["$date", next_month.isoformat()]}
                                ]
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },

        # Summarize each employee's records before grouping by department.
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$addToSet": "$emp_code"},

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {
                                        "$in": [
                                            {
                                                "$dayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$logs.date"
                                                    }
                                                }
                                            },
                                            [2, 3, 4, 5, 6]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },

                "work_hours_values": {
                    "$push": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {"$ne": ["$logs.work_hours", None]}
                                ]
                            },
                            "$logs.work_hours",
                            None
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                },

                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0
                        ]
                    }
                }
            }
        },

        # Calculate the average over attendance records, not employees.
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": {"$size": "$headcount"},
                "present_days": 1,
                "avg_work_hours": {
                    "$let": {
                        "vars": {
                            "valid_hours": {
                                "$filter": {
                                    "input": "$work_hours_values",
                                    "as": "hours",
                                    "cond": {"$ne": ["$$hours", None]}
                                }
                            }
                        },
                        "in": {
                            "$cond": [
                                {"$gt": [{"$size": "$$valid_hours"}, 0]},
                                {"$avg": "$$valid_hours"},
                                None
                            ]
                        }
                    }
                },
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1
            }
        },

        {"$sort": {"department": 1}}
    ]

    items = list(db.employees.aggregate(pipeline))

    for item in items:
        value = item.get("avg_work_hours")
        if value is not None:
            item["avg_work_hours"] = float(
                Decimal(str(value)).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
             )

    return {
    "month": month,
    "items": items
    }



def build_late_leaderboard_pipeline(
    month_start: date,
    next_month: date,
    limit: int,
    department: Optional[str] = None
):
    """Build the shared ranking pipeline for endpoint and explain."""
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lt": next_month.isoformat()
                },
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {"rank": {"$rank": {}}}
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])
    return pipeline


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None
):
    year, month_number = map(int, month.split("-"))
    month_start = date(year, month_number, 1)
    next_month = (
        date(year + 1, 1, 1)
        if month_number == 12
        else date(year, month_number + 1, 1)
    )

    pipeline = build_late_leaderboard_pipeline(
        month_start, next_month, limit, department
    )
    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items
    }


def build_department_trend_pipeline(
    department: str,
    from_date: date,
    to_date: date
):
    start_str = from_date.isoformat()
    end_str = to_date.isoformat()

    start_bound = datetime.combine(
        from_date, time.min, tzinfo=timezone.utc
    )
    end_bound = datetime.combine(
        to_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc
    )

    pipeline = [
        {
            "$match": {
                "department": department
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", start_str]},
                                    {"$lte": ["$date", end_str]}
                                ]
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": {
                    "$ifNull": ["$logs.date", None]
                },
                "employees": {"$addToSet": "$emp_code"},
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$logs.status",
                                    ["PRESENT", "WFH", "ON_DUTY"]
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },
                "headcount": {"$sum": 1}
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "present_count": 1,
                "late_count": 1,
                "headcount": 1
            }
        },
        {
            "$match": {
                "date": {"$ne": None}
            }
        },
        {
            "$addFields": {
                "date_value": {
                    "$dateFromString": {
                        "dateString": "$date"
                    }
                }
            }
        },
        
        {
            "$densify": {
                "field": "date_value",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_bound, end_bound]
                }
            }
        },

        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date_value"
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"trend_date": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {
                                "$lte": ["$joined_on", "$$trend_date"]
                            }
                        }
                    },
                    {"$count": "count"}
                ],
                "as": "headcount_result"
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_result.count", 0]},
                        0
                    ]
                },
                "is_working_day": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": "$date_value"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$date_value"}, 6]}
                    ]
                },
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]}
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]}
                            ]
                        },
                        {
                            "$round": [
                                {"$divide": ["$present_count", "$headcount"]},
                                4
                            ]
                        },
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date_value": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0]
                        }
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1
            }
        },
        {"$sort": {"date": 1}}
    ]


    return pipeline


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to")
):
    

    # Validate the requested date range.
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'"
        )

    if (to_date - from_date).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )

    # Ensure that the department exists.
    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )
    pipeline = build_department_trend_pipeline(
        department,
        from_date,
        to_date
    )

    items = list(db.employees.aggregate(pipeline))

    # If no attendance documents exist in the entire range, the pipeline's
    # null-date group is filtered before $densify and returns no rows.
    # Build the (at most 92) requested calendar rows so the API still returns
    # one row per day, with zero attendance and the correct daily headcount.
    if not items:
        joined_employees = list(
            db.employees.find(
                {
                    "department": department,
                    "joined_on": {"$lte": to_date.isoformat()}
                },
                {"_id": 0, "joined_on": 1}
            ).sort("joined_on", 1)
        )
        joined_dates = [employee["joined_on"] for employee in joined_employees]
        joined_index = 0
        calendar_dates = [
            from_date + timedelta(days=offset)
            for offset in range((to_date - from_date).days + 1)
        ]

        items = []
        for current_date in calendar_dates:
            date_str = current_date.isoformat()
            while (
                joined_index < len(joined_dates)
                and joined_dates[joined_index] <= date_str
            ):
                joined_index += 1

            is_working_day = current_date.weekday() < 5
            headcount = joined_index
            attendance_rate = (
                0.0 if is_working_day and headcount > 0 else None
            )
            items.append({
                "date": date_str,
                "is_working_day": is_working_day,
                "headcount": headcount,
                "present_count": 0,
                "late_count": 0,
                "attendance_rate": attendance_rate,
                "moving_avg_7d": None
            })

        # Match MongoDB's trailing seven-document average, ignoring null rates.
        for index, item in enumerate(items):
            window_rates = [
                row["attendance_rate"]
                for row in items[max(0, index - 6):index + 1]
                if row["attendance_rate"] is not None
            ]
            item["moving_avg_7d"] = (
                sum(window_rates) / len(window_rates)
                if window_rates else None
            )

    # Round reported rates to four decimal places, half-up.
    for item in items:
        for field in ("attendance_rate", "moving_avg_7d"):
            value = item.get(field)
            if value is not None:
                item[field] = float(
                    Decimal(str(value)).quantize(
                        Decimal("0.0001"),
                        rounding=ROUND_HALF_UP
                    )
                )

    return {
        "department": department,
        "items": items
    }
    
    
@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to")
):
    if endpoint not in {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    }:
        raise HTTPException(status_code=422, detail="Unsupported endpoint")

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if date_from:
            query["date"] = {"$gte": date_from.isoformat()}
        if date_to:
            query.setdefault("date", {})["$lte"] = date_to.isoformat()
        if status:
            query["status"] = status

        
        result = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1, "emp_code": 1},
                "skip": (page - 1) * page_size,
                "limit": page_size
            },
            "verbosity": "executionStats"
        })

        return json.loads(dumps(result))


    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="month must be YYYY-MM")

        year, month_number = map(int, month.split("-"))
        start = date(year, month_number, 1)
        next_month = (
            date(year + 1, 1, 1)
            if month_number == 12
            else date(year, month_number + 1, 1)
        )

        pipeline = build_employee_monthly_pipeline(
            emp_code, start, next_month
        )

        result = db.command({
    "explain": {
        "aggregate": "attendance_logs",
        "pipeline": pipeline,
        "cursor": {}
    },
    "verbosity": "executionStats"
})

        return json.loads(dumps(result))

    if endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="month must be YYYY-MM")

        year, month_number = map(int, month.split("-"))
        month_start = date(year, month_number, 1)

        if month_number == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month_number + 1, 1)

        month_end = next_month - date.resolution

        employee_match = {
            "joined_on": {"$lte": month_end.isoformat()}
        }

        if department is not None:
            employee_match["department"] = department

        pipeline = [
            {"$match": employee_match},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"employee_code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {
                                            "$eq": [
                                                "$emp_code",
                                                "$$employee_code"
                                            ]
                                        },
                                        {
                                            "$gte": [
                                                "$date",
                                                month_start.isoformat()
                                            ]
                                        },
                                        {
                                            "$lt": [
                                                "$date",
                                                next_month.isoformat()
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "logs"
                }
            },
            {
                "$unwind": {
                    "path": "$logs",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$addToSet": "$emp_code"},
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$logs.status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {
                                            "$in": [
                                                {
                                                    "$dayOfWeek": {
                                                        "$dateFromString": {
                                                            "dateString": "$logs.date"
                                                        }
                                                    }
                                                },
                                                [2, 3, 4, 5, 6]
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "$cond": [
                                        {"$eq": ["$logs.half_day", True]},
                                        0.5,
                                        1
                                    ]
                                },
                                0
                            ]
                        }
                    },
                    "work_hours_values": {
                        "$push": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$logs.status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {"$ne": ["$logs.work_hours", None]}
                                    ]
                                },
                                "$logs.work_hours",
                                None
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                                1,
                                0
                            ]
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                    },
                    "leave_count": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$logs.status", "LEAVE"]},
                                1,
                                0
                            ]
                        }
                    },
                    "on_duty_count": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$logs.status", "ON_DUTY"]},
                                1,
                                0
                            ]
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": {"$size": "$headcount"},
                    "present_days": 1,
                    "avg_work_hours": {
                        "$let": {
                            "vars": {
                                "valid_hours": {
                                    "$filter": {
                                        "input": "$work_hours_values",
                                        "as": "hours",
                                        "cond": {"$ne": ["$$hours", None]}
                                    }
                                }
                            },
                            "in": {
                                "$cond": [
                                    {"$gt": [{"$size": "$$valid_hours"}, 0]},
                                    {"$avg": "$$valid_hours"},
                                    None
                                ]
                            }
                        }
                    },
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1
                }
            },
            {"$sort": {"department": 1}}
        ]

        result = db.command({
            "explain": {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })

        return json.loads(dumps(result))



    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(
                status_code=422,
                detail="month must be YYYY-MM"
            )

        year, month_number = map(int, month.split("-"))
        month_start = date(year, month_number, 1)
        next_month = (
            date(year + 1, 1, 1)
            if month_number == 12
            else date(year, month_number + 1, 1)
        )

        pipeline = build_late_leaderboard_pipeline(
            month_start, next_month, limit, department
        )

        result = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })

        return json.loads(dumps(result))

    if endpoint == "department_trend":
        if not department or from_date is None or to_date is None:
            raise HTTPException(
                status_code=422,
                detail="department, from, and to are required"
            )

        if to_date < from_date:
            raise HTTPException(
                status_code=422,
                detail="'to' must be on or after 'from'"
            )

        if (to_date - from_date).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="Date range cannot exceed 92 days"
            )

        if not db.employees.find_one({"department": department}):
            raise HTTPException(
                status_code=404,
                detail="Department not found"
            )

        pipeline = build_department_trend_pipeline(
            department,
            from_date,
            to_date
        )

        result = db.command({
            "explain": {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })

        return json.loads(dumps(result))



    raise HTTPException(
        status_code=501,
        detail="Explain plan for this endpoint is not implemented yet"
    )