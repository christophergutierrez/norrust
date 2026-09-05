import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

from .game_history import import_review, open_history
from .game_training_export import assign_split, export

class TrainingExportTests(unittest.TestCase):
    def test_approved_payloads_export_and_split_deterministically(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            with conn:
                conn.execute("""INSERT INTO games(game_id,cohort_id,lineage_root_id,status,config_json,
                    provenance_json,schema_version,artifact_path) VALUES('g1','c','g1','complete','{}','{}',1,'.')""")
                conn.execute("""INSERT INTO model_requests(request_id,game_id,sequence,status,prompt_blob,
                    response_blob,payload_codec,record_hash) VALUES('r1','g1',1,'completed',?,?,?,?)""",
                    (zlib.compress(b"state"), zlib.compress(b"[{\"action\":\"DoneWithImportantMoves\"}]"),
                     "zlib", "hash"))
                conn.execute("""INSERT INTO evaluation_runs(evaluation_run_id,evaluator_name,
                    evaluator_version,config_json,status) VALUES('review1','review','1','{}','complete')""")
                conn.execute("""INSERT INTO decision_evaluations(evaluation_run_id,request_id,verdict,
                    reason_codes_json,metrics_json,evidence_json) VALUES('review1','r1','approve','[]','{}','{}')""")
            out = Path(td) / "dataset"
            manifest = export(conn, str(out), "review1", split_seed=7)
            self.assertEqual(manifest["count"], 1)
            self.assertEqual(json.loads((out / f"{assign_split('g1', 7)}.jsonl").read_text())["id"], "r1")

    def test_review_import_and_rationale_filter(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            with conn:
                conn.execute("""INSERT INTO games(game_id,status,config_json,provenance_json,
                    schema_version,artifact_path) VALUES('g1','complete','{}','{}',1,'.')""")
                conn.execute("""INSERT INTO model_requests(request_id,game_id,sequence,status,
                    prompt_blob,response_blob,reasoning_blob,reasoning_source,payload_codec,record_hash)
                    VALUES('r1','g1',1,'completed',?,?,?,?,?,?)""",
                    (zlib.compress(b"state"), zlib.compress(b"move"), zlib.compress(b"because"),
                     "reviewed", "zlib", "hash"))
            reviews = Path(td) / "reviews.jsonl"
            reviews.write_text(json.dumps({"request_id": "r1", "verdict": "approve"}) + "\n")
            self.assertEqual(import_review(conn, reviews, "review2"), 1)
            out = Path(td) / "dataset"
            self.assertEqual(export(conn, str(out), "review2", rationale=True)["count"], 1)
            exported = [json.loads(line) for split in ("train", "validation", "test")
                        for line in (out / f"{split}.jsonl").read_text().splitlines()]
            self.assertEqual(exported[0]["rationale"], "because")

if __name__ == "__main__":
    unittest.main()
