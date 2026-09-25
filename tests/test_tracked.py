import json

import pytest

import onbid_client
from onbid_client import TrackedError, alias_items_for, delete_tracked, load_tracked, upsert_tracked


@pytest.fixture
def tracked_file(tmp_path, monkeypatch):
    path = tmp_path / "tracked.json"
    monkeypatch.setattr(onbid_client, "TRACKED_FILE", path)
    path.write_text(
        json.dumps(
            {
                "tracked": [
                    {
                        "originalPbanc": "202503-06201-00",
                        "alias": "202503-09207-00",
                        "cltrMngNo": "2025-0300-013755",
                        "note": "기존",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_upsert_adds_new_numbers(tracked_file):
    items = upsert_tracked(
        {
            "originalPbanc": "202609-10001-00",
            "alias": "",
            "cltrMngNo": "2026-0900-000111",
            "note": "",
        }
    )
    added = items[-1]
    assert added["originalPbanc"] == "202609-10001-00"
    assert added["cltrMngNo"] == "2026-0900-000111"
    assert "2026-0900-000111" in added["note"]
    saved = json.loads(tracked_file.read_text(encoding="utf-8"))
    assert saved["tracked"][-1]["cltrMngNo"] == "2026-0900-000111"


def test_upsert_updates_existing_alias_and_item(tracked_file):
    items = upsert_tracked(
        {
            "originalPbanc": "202503-06201-00",
            "alias": "202503-09999-00",
            "cltrMngNo": "2025-0300-999999",
            "note": "번호 변경",
        },
        replace_original="202503-06201-00",
    )
    assert len(items) == 1
    assert items[0]["alias"] == "202503-09999-00"
    assert items[0]["cltrMngNo"] == "2025-0300-999999"
    assert alias_items_for(items) == {"202503-09999-00": ["2025-0300-999999", "2025-0300-013755"]}


def test_upsert_can_rename_original_number(tracked_file):
    items = upsert_tracked(
        {"originalPbanc": "202503-07000-00", "alias": "202503-09207-00", "cltrMngNo": "2025-0300-013755"},
        replace_original="202503-06201-00",
    )
    assert [item["originalPbanc"] for item in items] == ["202503-07000-00"]


def test_rejects_bad_numbers(tracked_file):
    with pytest.raises(TrackedError):
        upsert_tracked({"originalPbanc": "공고-1", "cltrMngNo": "2025-0300-013755"})
    with pytest.raises(TrackedError):
        upsert_tracked({"originalPbanc": "202503-06201-00", "cltrMngNo": "13-755"})


def test_delete_tracked(tracked_file):
    assert delete_tracked("202503-06201-00") == []
    with pytest.raises(TrackedError):
        delete_tracked("202503-06201-00")


def test_announcement_looks_up_every_item(monkeypatch):
    class FakeClient:
        def fetch_items(self, headers, onbid_pbanc_no, pbct_no):
            return [
                {"cltrMngNo": "2025-0300-013755", "onbidCltrNm": "갑", "pbctCltrStatNm": "유찰", "pbctNsq": 1},
                {"cltrMngNo": "2025-0300-013756", "onbidCltrNm": "을", "pbctCltrStatNm": "유찰", "pbctNsq": 1},
            ]

        def lookup_item(self, headers, cltr):
            return {
                "onbidCltrno": cltr[-1],
                "scrnIndctCltrMngNo": cltr,
                "onbidCltrNm": cltr,
                "pbctCltrStatNm": "수의계약가능",
                "pbancMngNo": "202503-09207-00",
            }

        def search_unf(self, headers, query):
            return {
                "pbancRsltSrchRslt": [
                    {
                        "pbancMngNo": query,
                        "onbidPbancNo": 1,
                        "pbctNo": 2,
                        "pbctNsq": 1,
                        "onbidPbancNm": "테스트",
                        "regOrgNm": "기관",
                    }
                ]
            }

        def fetch_schedule(self, headers, onbid_pbanc_no, pbct_no):
            return []

    announcement = onbid_client.fetch_announcement(FakeClient(), {}, "202503-09207-00", "202503-09207-00")
    assert [item["cltrMngNo"] for item in announcement["items"]] == [
        "2025-0300-013755",
        "2025-0300-013756",
    ]
    assert {item["status"] for item in announcement["items"]} == {"수의계약가능"}


def test_refresh_uses_saved_numbers(tracked_file, monkeypatch):
    captured = {}

    class FakeClient:
        def _csrf_headers(self, url):
            return {}

        def search_unf(self, headers, query):
            captured["query"] = query
            return {"pbancRsltSrchRslt": []}

        def lookup_item(self, headers, cltr):
            captured["cltr"] = cltr
            return {}

    monkeypatch.setattr(onbid_client, "OnbidClient", FakeClient)
    monkeypatch.setattr(onbid_client, "save_snapshot", lambda data: data)
    result = onbid_client.refresh_tracked()
    assert captured == {"query": "202503-09207-00", "cltr": "2025-0300-013755"}
    assert result["announcementCount"] == 1
    assert result["foundCount"] == 0


def test_missing_file_seeds_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(onbid_client, "TRACKED_FILE", tmp_path / "tracked.json")
    items = load_tracked()
    assert any(item["cltrMngNo"] == "2025-0300-013755" for item in items)
    assert (tmp_path / "tracked.json").exists()
