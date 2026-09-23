"""Core privacy, review, and cutoff checks. Run: python -m unittest portal/test_server.py"""

import http.cookiejar
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from portal import server


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_state, cls.original_db, cls.original_cache = server.STATE, server.DB, server.CACHE
        server.STATE = Path(cls.temp.name) / "state"
        server.DB = server.STATE / "reviews.sqlite3"
        server.CACHE = server.STATE / "media_cache"
        server.init_db()
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.PortalHandler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=5)
        server.STATE, server.DB, server.CACHE = cls.original_state, cls.original_db, cls.original_cache
        cls.temp.cleanup()

    def client(self, name):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.request(opener, "/api/session", "POST", {"name": name, "passphrase": "test-passphrase"})
        return opener

    def request(self, opener, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "X-Portal-Request": "1"} if body is not None else {}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_private_payload_and_person_9_selection(self):
        client = self.client("privacy-check")
        status, people = self.request(client, "/api/people")
        self.assertEqual(status, 200)
        self.assertEqual(next(p["total"] for p in people["people"] if p["person"] == 9), 310)
        status, listing = self.request(client, "/api/people/9/questions")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["questions"]), 310)
        status, question = self.request(client, "/api/questions/4231")
        self.assertEqual(status, 200)
        self.assertEqual(question["person"], 9)
        self.assertEqual(len(question["choices"]), 4)
        self.assertTrue(question["evidence_spans"])
        self.assertFalse({"correct_answer", "correct_option_index", "choice_types", "answer_evidence", "is_answerable"} & question.keys())
        self.assertEqual(set(question["evidence_spans"][0]), {"video_id", "start", "end", "modalities", "within_cutoff"})
        self.assertTrue(all(r["recording_start_unix"] < question["question_time_unix"] for r in question["recordings"]))
        status, _ = self.request(client, "/data/json/all_qa.json")
        self.assertEqual(status, 404)
        status, _ = self.request(client, "/data/video/Person_9/Person_9_session_1_04112026_glasses_1283.mp4")
        self.assertEqual(status, 404)

    def test_draft_submission_and_reviewer_isolation(self):
        first = self.client("reviewer-one")
        second = self.client("reviewer-two")
        question_id = 4232
        payload = {"clarity": None, "answerability": None, "evidence_correctness": None,
                   "predicted_choice": None, "issues": [], "other_issue": "", "feedback": "in progress",
                   "edit_evidence": True, "edited_spans": [{"video_id": "Person_9_session_1_04112026_glasses_1283",
                                                      "start": None, "end": None, "modalities": []}]}
        status, saved = self.request(first, f"/api/questions/{question_id}/review", "POST",
                                     {"payload": payload, "version": 0, "submit": False})
        self.assertEqual(status, 200)
        self.assertEqual(saved["version"], 1)
        status, own = self.request(first, f"/api/questions/{question_id}/review")
        self.assertEqual(own["review"]["payload"]["feedback"], "in progress")
        status, other = self.request(second, f"/api/questions/{question_id}/review")
        self.assertIsNone(other["review"])
        status, _ = self.request(first, f"/api/questions/{question_id}/review", "POST",
                                 {"payload": payload, "version": 1, "submit": True})
        self.assertEqual(status, 400)
        payload.update({"clarity": "Clear", "answerability": "Answerable",
                        "evidence_correctness": "Partly sufficient or needs revision", "predicted_choice": 2,
                        "edited_spans": [{"video_id": "Person_9_session_1_04112026_glasses_1283",
                                          "start": 5, "end": 8, "modalities": ["Video"]}]})
        status, result = self.request(first, f"/api/questions/{question_id}/review", "POST",
                                      {"payload": payload, "version": 1, "submit": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "submitted")
        status, _ = self.request(first, f"/api/questions/{question_id}/review", "POST",
                                 {"payload": payload, "version": 2, "submit": False})
        self.assertEqual(status, 409)

    def test_transcript_is_capped(self):
        client = self.client("transcript-check")
        status, question = self.request(client, "/api/questions/4233")
        self.assertEqual(status, 200)
        audio_span = next(span for span in question["evidence_spans"] if "Audio" in span["modalities"])
        video_id = audio_span["video_id"]
        recording = next(r for r in question["recordings"] if r["video_id"] == video_id)
        self.assertTrue(recording["transcript_available"])
        status, result = self.request(client, f"/api/questions/4233/transcript?video={video_id}&from={audio_span['start']}&to={audio_span['end']}")
        self.assertEqual(status, 200)
        self.assertGreater(len(result["rows"]), 0)
        self.assertTrue(all(row["end"] <= recording["allowed_until"] - server.SAFETY_SECONDS for row in result["rows"]))

    def test_actual_media_clip_stops_before_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            old_data, old_cache = server.DATA, server.CACHE
            old_starts = server.VIDEO_STARTS.copy()
            server.DATA = Path(directory) / "data"
            server.CACHE = Path(directory) / "cache"
            server.CACHE.mkdir()
            video_id = "Person_9_session_99_04112026_glasses_1283"
            server.VIDEO_STARTS[video_id] = 1000
            path = server.DATA / "video" / "Person_9" / f"{video_id}.mp4"
            path.parent.mkdir(parents=True)
            try:
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=c=blue:s=320x180:r=12", "-t", "3", "-c:v", "libx264", "-pix_fmt",
                                "yuv420p", "-y", str(path)], check=True, timeout=30)
                item = {"subject": 9, "video_ids": [video_id], "start_time": 1000,
                        "question_evidence": {"time_spans": [{"video_id": video_id,
                            "video_start_time_unix": 1000, "start_time": 1.5}]}}
                clip = server.clipped_media(item, video_id, 0)
                duration = server.video_duration(clip)
                self.assertLessEqual(duration, 1.35)
                self.assertGreater(duration, .9)
                with self.assertRaises(FileNotFoundError):
                    server.clipped_media(item, video_id, 1)
            finally:
                server.DATA, server.CACHE = old_data, old_cache
                server.VIDEO_STARTS.clear()
                server.VIDEO_STARTS.update(old_starts)


if __name__ == "__main__":
    unittest.main()
