import requests
import time
import os

API_URL = "http://localhost:8000"

def run_test():
    print("Step 1: Creating Batch...")
    res = requests.post(f"{API_URL}/api/batches/", json={"name": f"ROITesting_{int(time.time())}"})
    if res.status_code != 200:
        print("Failed to create batch:", res.text)
        return
    batch_id = res.json()["id"]
    print(f"Batch created: {batch_id}")

    print("Step 2: Importing Images...")
    files_to_open = {
        "rgb": "微信图片_20260130155113_141_12.jpg",
        "band_570nm": "微信图片_20260130155114_142_12.jpg",
    }

    files = {}
    opened_files = []
    
    try:
        if not os.path.exists(files_to_open["rgb"]):
            print(f"Error: Could not find image {files_to_open['rgb']}")
            return
            
        for band, path in files_to_open.items():
            f = open(path, "rb")
            opened_files.append(f)
            files[band] = f
            
        print("Sending upload request...")
        res = requests.post(f"{API_URL}/api/batches/{batch_id}/import", files=files)
        
        if res.status_code != 200:
            print("Failed to import images:", res.text)
            return
        print("Images imported successfully.")

        print("Step 3: Calling Batch Alignment with Small ROI...")
        # A small ROI covering e.g., only 10% x 10% of the image at the center
        payload = {
            "batch_id": batch_id,
            "overwrite": True,
            "roi": {
                "x": 0.45,
                "y": 0.45,
                "width": 0.1,
                "height": 0.1
            }
        }
        res = requests.post(f"{API_URL}/api/alignment/batch-align", json=payload)
        
        if res.status_code == 200:
            result = res.json()
            print("\n=== Alignment Success ===")
            print(f"Summary: {result.get('summary')}")
            for d in result.get('details', []):
                print(f" - Image ID: {d['image_id'][:8]} | Success: {d['success']} | Message: {d['message']}")
        else:
            print("Alignment route failed:", res.status_code, res.text)

    except Exception as e:
        print(f"Exception: {e}")
    finally:
        for f in opened_files:
            f.close()

if __name__ == '__main__':
    run_test()
