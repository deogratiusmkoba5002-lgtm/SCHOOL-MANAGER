def test_exam_page_loads(client):
    r = client.get("/exam")
    assert r.status_code == 200
    assert "DrDemic Set Exam" in r.get_data(as_text=True)