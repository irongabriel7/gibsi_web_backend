import os
from flask_pymongo import PyMongo
from pymongo import MongoClient
import yaml

with open("/shared/mongo.yaml", "r") as f:
    config = yaml.safe_load(f)
    
MONGODB = config["MONGODB"]

# Allow environment override (for Docker / K8s)
MONGO_URI = os.getenv("MONGO_URI", MONGODB['mongo_uri'])
DB_NAME = os.getenv("DB_NAME", MONGODB['db_name'])

# Flask PyMongo (if used in Flask app)
mongo = PyMongo()

# ----------- For non-Flask scripts -----------
client = MongoClient(MONGO_URI)
non_flask_db = client[DB_NAME]
