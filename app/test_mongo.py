
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

uri = os.getenv("MONGO_URI")
db_name = os.getenv("MONGO_DB", "attendance_db")

if not uri:
    raise RuntimeError("MONGO_URI .env file mein nahi mili")

client = MongoClient(uri, serverSelectionTimeoutMS=10000)

try:
    client.admin.command("ping")
    print("MongoDB connected successfully!")
    print("Database:", db_name)
finally:
    client.close()
