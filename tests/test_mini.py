def _h(t): return {"Authorization": "Bearer " + t}


def test_mini_end_to_end(client):
    owner = _h(client.post("/api/mini/auth/signup", json={"username": "teacher_amos", "password": "secret12"}).get_json()["token"])
    key = client.post("/api/mini/sheets", headers=owner).get_json()["key"]
    sheet = client.get(f"/api/mini/sheet/{key}").get_json()
    eng, kis = sheet["subjects"][0]["id"], sheet["subjects"][1]["id"]
    body = {**{k: sheet[k] for k in ("school_name", "exam_name", "sheet_type", "grade_rules", "subjects")},
            "version": sheet["version"], "editor": "Guest Teacher",
            "rows": [{"id": "r1", "name": "Low", "phone": "0711000001", "marks": {eng: 40, kis: 50}},
                     {"id": "r2", "name": "High", "phone": "0711000002", "marks": {eng: 90, kis: 80}}]}
    url = f"/api/mini/sheet/{key}"

    saved = client.post(url + "/save", json=body).get_json()          # guest with the link can edit
    assert [r["name"] for r in saved["rows"]] == ["High", "Low"]
    assert saved["rows"][0]["position"] == 1 and saved["rows"][0]["grade"] == "A"
    assert client.post(url + "/save", json=body).status_code == 409   # stale version
    bad = {**body, "version": saved["version"], "rows": [{"id": "r3", "name": "X", "phone": "", "marks": {eng: 101}}]}
    assert client.post(url + "/save", json=bad).status_code == 400
    hist = client.get(url + "/history").get_json()["history"]
    assert hist[0]["editor"] == "Guest Teacher"

    assert client.post(url + "/publish", json={}).status_code == 401  # guests cannot publish
    pub = client.post(url + "/publish", headers=owner,
                      json={"publish": True, "restrict": [{"name": "Low", "reason": "fees"}]}).get_json()
    assert pub["students"] == 2 and pub["restricted"] == 1 and pub["link"].startswith("/mini/parents/")
    token = pub["link"].rsplit("/", 1)[1]
    link = f"/api/mini/link/{token}/login"

    assert client.post(link, json={"name": "High", "password": "0000"}).status_code == 401
    assert client.post(link, json={"name": "high", "password": "0711000002"}).get_json()["need_password"] is True
    done = client.post(link, json={"name": "High", "password": "0711000002",
                                   "new_password": "newpass1", "confirm_password": "newpass1"}).get_json()
    assert done["ok"] and done["token"]
    res = client.get(f"/api/mini/parent/results?pub={token}", headers=_h(done["token"])).get_json()["results"]
    assert len(res[0]["children"]) == 1 and res[0]["children"][0]["student"] == "High"
    assert client.post("/api/mini/sheets", headers=_h(done["token"])).status_code == 403
    assert client.post(link, json={"name": "High", "password": "newpass1"}).get_json()["ok"]
    assert "high" in client.get(url).get_json()["linked"]

    ann = client.post(url + "/announce", json={"title": "Meeting", "body": "Friday"}, headers=owner).get_json()
    assert ann["parents"] == 1
    got = client.get("/api/mini/parent/results", headers=_h(done["token"])).get_json()["announcements"]
    assert got[0]["title"] == "Meeting"