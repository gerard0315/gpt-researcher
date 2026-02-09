
import requests
import json
import time

BASE_URL = "http://localhost:8000/api/reports"

def test_get_reports():
    print("Testing GET /api/reports...")
    try:
        response = requests.get(BASE_URL)
        assert response.status_code == 200
        data = response.json()
        assert "reports" in data
        print(f"✅ GET /api/reports passed. Found {len(data['reports'])} reports.")
        return data['reports']
    except Exception as e:
        print(f"❌ GET /api/reports failed: {e}")
        return []

def test_delete_report(report_id):
    print(f"Testing DELETE /api/reports/{report_id}...")
    try:
        response = requests.delete(f"{BASE_URL}/{report_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["id"] == report_id
        print(f"✅ DELETE /api/reports/{report_id} passed.")
    except Exception as e:
        print(f"❌ DELETE /api/reports/{report_id} failed: {e}")

if __name__ == "__main__":
    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(5)
    
    reports = test_get_reports()
    
    if reports:
        # Test getting specific report
        first_report_id = reports[0]['id']
        print(f"Testing GET /api/reports/{first_report_id}...")
        try:
            response = requests.get(f"{BASE_URL}/{first_report_id}")
            assert response.status_code == 200
            data = response.json()
            assert "report" in data
            assert data["report"]["id"] == first_report_id
            print(f"✅ GET /api/reports/{first_report_id} passed.")
        except Exception as e:
            print(f"❌ GET /api/reports/{first_report_id} failed: {e}")
            
    else:
        print("ℹ️ No reports found to test specific GET/DELETE. Run a research first.")
