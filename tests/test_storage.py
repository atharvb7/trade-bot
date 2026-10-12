from datetime import datetime
from pathlib import Path

from bot.storage import DecisionRecord, make_session_factory


def test_db_created_and_roundtrip(tmp_path: Path) -> None:
    Session = make_session_factory(f"sqlite:///{tmp_path}/t.db")
    with Session() as s:
        s.add(
            DecisionRecord(
                mode="paper",
                ts=datetime(2026, 1, 1, 10),
                symbol="ITC",
                setup="orb",
                direction="long",
                entry=1.0,
                stop=0.9,
                target=1.15,
                final_status="rejected_ml",
                rejection_reason="ml_prob<0.6",
            )
        )
        s.commit()
        assert s.query(DecisionRecord).count() == 1
