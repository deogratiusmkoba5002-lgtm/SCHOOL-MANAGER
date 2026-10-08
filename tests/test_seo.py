import xml.etree.ElementTree as ET

def test_robots_txt(client):
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    body = response.get_data(as_text=True)

    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /setup" in body
    assert "Disallow: /superadmin" in body
    assert "Sitemap: https://drdemic.co.tz/sitemap.xml" in body


def test_sitemap_xml(client):
    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.content_type.startswith("application/xml")

    body = response.get_data(as_text=True)

    root = ET.fromstring(body)
    assert root.tag.endswith("urlset")

    assert "<urlset" in body
    assert "https://drdemic.co.tz/" in body
    assert "https://drdemic.co.tz/register" in body
    assert "https://drdemic.co.tz/privacy" in body
    assert "https://drdemic.co.tz/terms" in body

    assert "/setup</loc>" not in body
    assert "/superadmin</loc>" not in body


def test_homepage_contains_seo_metadata(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "<title>DrDemic | School Management System in Tanzania</title>" in body
    assert 'name="description"' in body
    assert 'name="robots" content="index, follow"' in body
    assert 'rel="canonical" href="https://drdemic.co.tz/"' in body
    assert 'property="og:title"' in body
    assert 'property="og:description"' in body
    assert 'application/ld+json' in body
    assert '"name": "DrDemic"' in body


def test_homepage_contains_public_drdemic_description(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "DrDemic School Management System" in body
    assert "school management system built for schools in Tanzania" in body
    assert "Register your school" in body
