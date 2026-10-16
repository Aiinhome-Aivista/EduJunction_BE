import sys
import os

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.dbConnection import get_session
from model.models import ExamSubmission
from helper.guest_exam_sync_helper import populate_guest_exam_evaluations

def run_backfill():
    with get_session() as session:
        subs = session.query(ExamSubmission).all()
        repaired = 0
        for sub in subs:
            if not sub.evaluations and sub.answers:
                print(f"Repairing submission {sub.id} (exam: {sub.exam_id})...")
                populate_guest_exam_evaluations(
                    session=session,
                    exam=sub.exam,
                    submission=sub,
                    raw_answers=sub.answers,
                )
                repaired += 1
        session.commit()
        print(f"Successfully repaired {repaired} submission(s)!")

if __name__ == "__main__":
    run_backfill()
