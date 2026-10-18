"""MongoDB storage. Public documents retain the existing API's string IDs and timestamps."""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pymongo import MongoClient, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from .focus import in_scope
from .models import Job, now


class Store:
    def __init__(self, url: str):
        self.client = MongoClient(
            url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            timeoutMS=10000,
        )
        self.db = self.client.get_default_database(default="job_scraper")
        self.owner = uuid4().hex
        self.owns_lease = False
        try:
            self.ping()
            self.db.jobs.create_index([("source", 1), ("source_id", 1)], unique=True)
            self.db.jobs.create_index([("eligible", 1), ("fetched_at", -1), ("id", 1)])
            self.db.runs.create_index([("started_at", -1)])
        except Exception:
            self.client.close()
            raise

    def ping(self):
        self.db.command("ping")

    def acquire(self):
        # Initialize separately: MongoDB disallows $expr in an upsert predicate.
        # Only the conditional find-and-update below can acquire ownership.
        try:
            self.db.leases.update_one(
                {"_id": "collector"},
                {"$setOnInsert": {"owner": "", "expires_at": datetime(1970, 1, 1, tzinfo=UTC)}},
                upsert=True,
            )
        except DuplicateKeyError:
            pass  # A concurrent initializer created the same lease document.
        document = self.db.leases.find_one_and_update(
            {
                "_id": "collector",
                "$or": [
                    {"owner": self.owner},
                    {"$expr": {"$lte": ["$expires_at", "$$NOW"]}},
                ],
            },
            [{"$set": {"owner": self.owner, "expires_at": {"$add": ["$$NOW", 60000]}}}],
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise RuntimeError("Database already in use; run exactly one server worker")
        self.owns_lease = True

    def renew(self):
        result = self.db.leases.update_one(
            {"_id": "collector", "owner": self.owner, "$expr": {"$gt": ["$expires_at", "$$NOW"]}},
            [{"$set": {"expires_at": {"$add": ["$$NOW", 60000]}}}],
        )
        if result.matched_count != 1:
            raise RuntimeError("Database ownership lost")

    def close(self):
        try:
            if self.owns_lease:
                self.db.leases.delete_one({"_id": "collector", "owner": self.owner})
        finally:
            self.client.close()

    def check_owner(self):
        if self.owns_lease:
            self.renew()

    def recover(self):
        self.check_owner()
        self.db.runs.update_many(
            {"status": "running"}, {"$set": {"status": "interrupted", "finished_at": now()}}
        )

    def start_run(self, sources: list[str]) -> str:
        self.check_owner()
        run_id = uuid4().hex
        self.db.runs.insert_one(
            {
                "_id": run_id,
                "id": run_id,
                "status": "running",
                "started_at": now(),
                "finished_at": None,
                "sources": sources,
                "results": {},
            }
        )
        return run_id

    def update_run(self, run_id: str, results: dict, status: str = "running"):
        self.check_owner()
        self.db.runs.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "results": results,
                    "status": status,
                    "finished_at": None if status == "running" else now(),
                }
            },
        )

    def runs(self, limit=20):
        return list(self.db.runs.find({}, {"_id": 0}).sort("started_at", -1).limit(limit))

    def run(self, run_id):
        return self.db.runs.find_one({"_id": run_id}, {"_id": 0})

    def attempts(self) -> dict[str, str]:
        return {row["_id"]: row["attempted_at"] for row in self.db.source_attempts.find({})}

    def mark_attempt(self, source: str):
        self.check_owner()
        self.db.source_attempts.update_one(
            {"_id": source}, {"$set": {"attempted_at": now()}}, upsert=True
        )

    def save(self, jobs: list[Job]) -> dict:
        self.check_owner()
        operations = []
        for job in jobs:
            document = job.model_dump(mode="json")
            first_seen = document.pop("first_seen_at")
            operations.append(
                UpdateOne(
                    {"_id": job.id},
                    {
                        "$set": {**document, "eligible": in_scope(job)},
                        "$setOnInsert": {"first_seen_at": first_seen},
                    },
                    upsert=True,
                )
            )
        inserted = self.db.jobs.bulk_write(operations).upserted_count if operations else 0
        return {"inserted": inserted, "updated": len(jobs) - inserted}

    def job(self, job_id):
        return self.db.jobs.find_one({"_id": job_id, "eligible": True}, {"_id": 0, "eligible": 0})

    def jobs(
        self,
        *,
        q=None,
        source=None,
        remote=None,
        since=None,
        limit=50,
        offset=0,
        include_expired=False,
    ):
        clauses = [{"eligible": True}]
        for key, value in (("source", source), ("remote", remote)):
            if value is not None:
                clauses.append({key: value})
        if q:
            # Search text is literal, never a caller-supplied regex/operator.
            pattern = {"$regex": re.escape(q), "$options": "i"}
            clauses.append({"$or": [{"title": pattern}, {"company": pattern}]})
        if since:
            clauses.append({"fetched_at": {"$gte": since}})
        if not include_expired:
            clauses.append({"$or": [{"expires_at": None}, {"expires_at": {"$gt": now()}}]})
        query = {"$and": clauses}
        items = (
            self.db.jobs.find(query, {"_id": 0, "eligible": 0})
            .sort([("fetched_at", -1), ("id", 1)])
            .skip(offset)
            .limit(limit)
        )
        return {
            "items": list(items),
            "total": self.db.jobs.count_documents(query),
            "limit": limit,
            "offset": offset,
        }

    def prune(self, retention_days):
        self.check_owner()
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        self.db.jobs.delete_many({"fetched_at": {"$lt": cutoff}})
        self.db.runs.delete_many({"finished_at": {"$type": "string", "$lt": cutoff}})
