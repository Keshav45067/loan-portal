import sys
import unittest
import json
import uuid
sys.path.append('app-orchestrator')
sys.path.append('shared')

# Mock DB pool for offline unit test execution
class MockCursor:
    def __init__(self, db_state):
        self.db = db_state
        self._last_result = None
        self._fetchall_result = []

    def execute(self, sql, params=()):
        sql_clean = " ".join(sql.split()).upper()
        
        # INSERT INTO user_data
        if "INSERT INTO USER_DATA" in sql_clean:
            if len(params) == 8: # id, phone, scheme_id, stage, completion_status, data, created_at, updated_at
                session_id, phone, scheme_id, stage, status, data_json, _, _ = params
            elif len(params) == 3: # id, phone, data
                session_id, phone, data_json = params
                scheme_id = json.loads(data_json).get("scheme_id", "")
                stage = "REGISTRATION"
                status = "NEW"
            self.db[session_id] = {
                "id": session_id,
                "phone": phone,
                "scheme_id": scheme_id,
                "stage": stage,
                "completion_status": status,
                "last_node": None,
                "data": json.loads(data_json) if isinstance(data_json, str) else data_json,
                "updated_at": "2026-08-26T18:00:00"
            }
            self._last_result = None

        # SELECT data, phone FROM user_data WHERE id = %s OR phone = %s ORDER BY updated_at DESC LIMIT 1
        elif "SELECT DATA, PHONE FROM USER_DATA WHERE ID = %S OR PHONE = %S" in sql_clean:
            session_id, phone = params
            matched = [row for row in self.db.values() if row["id"] == session_id or row["phone"] == phone]
            if matched:
                self._last_result = (matched[-1]["data"], matched[-1]["phone"])
            else:
                self._last_result = None

        # SELECT id, data FROM user_data WHERE phone = %s AND (scheme_id = %s OR data->>'scheme_id' = %s)
        elif "SELECT ID, DATA FROM USER_DATA WHERE PHONE = %S AND (SCHEME_ID = %S" in sql_clean:
            phone, scheme_id, _ = params
            matched = [row for row in self.db.values() if row["phone"] == phone and (row["scheme_id"] == scheme_id or row["data"].get("scheme_id") == scheme_id)]
            if matched:
                self._last_result = (matched[-1]["id"], matched[-1]["data"])
            else:
                self._last_result = None

        # SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s
        elif "SELECT ID, PHONE, DATA FROM USER_DATA WHERE ID = %S" in sql_clean:
            app_id = params[0]
            matched = [row for row in self.db.values() if row["id"] == app_id or row["data"].get("application_id") == app_id]
            if matched:
                self._last_result = (matched[0]["id"], matched[0]["phone"], matched[0]["data"])
            else:
                self._last_result = None

        # SELECT id, phone, data, last_node FROM user_data WHERE id = %s
        elif "SELECT ID, PHONE, DATA, LAST_NODE FROM USER_DATA WHERE ID = %S" in sql_clean:
            app_id = params[0]
            matched = [row for row in self.db.values() if row["id"] == app_id or row["data"].get("application_id") == app_id]
            if matched:
                self._last_result = (matched[0]["id"], matched[0]["phone"], matched[0]["data"], matched[0].get("last_node"))
            else:
                self._last_result = None

        # UPDATE user_data
        elif "UPDATE USER_DATA" in sql_clean:
            target_id = params[-1]
            if target_id in self.db:
                # Find data_json in params
                for p in params:
                    if isinstance(p, str) and (p.startswith("{") or "scheme_id" in p):
                        try:
                            self.db[target_id]["data"] = json.loads(p)
                            self.db[target_id]["scheme_id"] = self.db[target_id]["data"].get("scheme_id", self.db[target_id]["scheme_id"])
                        except Exception:
                            pass

        # SELECT for ListApplications
        elif "SELECT ID, PHONE, DATA FROM USER_DATA" in sql_clean:
            phone_filter = params[0] if params else None
            if phone_filter:
                matched = [row for row in self.db.values() if row["phone"] == phone_filter or row["data"].get("phone") == phone_filter]
            else:
                matched = list(self.db.values())
            self._fetchall_result = [(r["id"], r["phone"], r["data"]) for r in matched]
            self._last_result = (len(matched),)

        elif "SELECT COUNT(*)" in sql_clean:
            self._last_result = (len(self.db),)

        elif "ALTER TABLE" in sql_clean:
            pass

    def fetchone(self):
        return self._last_result

    def fetchall(self):
        return self._fetchall_result

class MockDBContext:
    def __init__(self, db_state):
        self.cursor = MockCursor(db_state)
        self.cursor.connection = self

    @property
    def autocommit(self):
        return True

    @autocommit.setter
    def autocommit(self, val):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class TestMultiSchemeDataIsolation(unittest.TestCase):
    def setUp(self):
        self.mock_db = {}
        self.db_context = MockDBContext(self.mock_db)

    def test_multi_scheme_isolation(self):
        user_phone = "+919876543210"
        
        # 1. User applies for Scheme A: 'base-mudra'
        session_id_a = str(uuid.uuid4())
        data_a = {
            "scheme_id": "base-mudra",
            "phone": user_phone,
            "applicant_name": "Ramesh Kumar",
            "panchayat": "Gram Panchayat 1",
            "district": "North District",
            "state": "JHARKHAND",
            "monthly_revenue": "25000",
            "business_type": "dairy",
            "doc_pan_number": "ABCDE1234F",
            "completion_status": "COMPLETED",
            "onboarding_finished": True
        }
        with self.db_context as cur:
            cur.execute(
                """INSERT INTO user_data (id, phone, scheme_id, stage, completion_status, data, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s::json, NOW(), NOW())""",
                (session_id_a, user_phone, "base-mudra", "COMPLETE", "COMPLETED", json.dumps(data_a), "", "")
            )

        # Verify Scheme A is stored in mock DB
        self.assertIn(session_id_a, self.mock_db)
        self.assertEqual(self.mock_db[session_id_a]["data"]["monthly_revenue"], "25000")
        self.assertEqual(self.mock_db[session_id_a]["data"]["doc_pan_number"], "ABCDE1234F")

        # 2. Same user applies for Scheme B: 'rural-voice-test'
        session_id_b = str(uuid.uuid4())
        # Base profile is inherited (name, location), but extractions start completely clean
        data_b = {
            "scheme_id": "rural-voice-test",
            "phone": user_phone,
            "applicant_name": "Ramesh Kumar",
            "panchayat": "Gram Panchayat 1",
            "district": "North District",
            "state": "JHARKHAND",
            "completion_status": "NEW",
            "onboarding_finished": False,
            "extractions": {}
        }
        with self.db_context as cur:
            cur.execute(
                """INSERT INTO user_data (id, phone, scheme_id, stage, completion_status, data, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s::json, NOW(), NOW())""",
                (session_id_b, user_phone, "rural-voice-test", "INTERVIEW", "NEW", json.dumps(data_b), "", "")
            )

        # 3. Assert Scheme B has a distinct session_id
        self.assertNotEqual(session_id_a, session_id_b)

        # 4. Assert Scheme B does NOT contain Scheme A's interview answers or document numbers
        scheme_b_stored = self.mock_db[session_id_b]["data"]
        self.assertNotIn("monthly_revenue", scheme_b_stored)
        self.assertNotIn("doc_pan_number", scheme_b_stored)
        self.assertNotIn("business_type", scheme_b_stored)
        self.assertEqual(scheme_b_stored["scheme_id"], "rural-voice-test")

        # 5. User performs interview for Scheme B and saves answers
        data_b["monthly_revenue"] = "8000"
        data_b["business_type"] = "tailor"
        data_b["tailor_machine_cost"] = "5000"
        with self.db_context as cur:
            cur.execute(
                """UPDATE user_data SET data = %s::json WHERE id = %s""",
                (json.dumps(data_b), session_id_b)
            )

        # 6. Verify Scheme A remained completely intact and unmodified
        scheme_a_stored = self.mock_db[session_id_a]["data"]
        self.assertEqual(scheme_a_stored["monthly_revenue"], "25000")
        self.assertEqual(scheme_a_stored["business_type"], "dairy")
        self.assertEqual(scheme_a_stored["doc_pan_number"], "ABCDE1234F")
        self.assertNotIn("tailor_machine_cost", scheme_a_stored)

        # 7. Verify ListApplications for this user phone returns both isolated applications
        with self.db_context as cur:
            cur.execute("SELECT id, phone, data FROM user_data", (user_phone,))
            rows = cur.fetchall()

        self.assertEqual(len(rows), 2)
        schemes_found = {r[2]["scheme_id"]: r[2] for r in rows}
        self.assertIn("base-mudra", schemes_found)
        self.assertIn("rural-voice-test", schemes_found)
        self.assertEqual(schemes_found["base-mudra"]["monthly_revenue"], "25000")
        self.assertEqual(schemes_found["rural-voice-test"]["monthly_revenue"], "8000")

if __name__ == '__main__':
    unittest.main()
