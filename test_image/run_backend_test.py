import requests
import time
import os

API_URL = "http://localhost:8000"

def run_test():
    print("Step 1: Creating Batch...")
    res = requests.post(f"{API_URL}/api/batches/", json={"name": f"RealImageTest_{int(time.time())}"})
    if res.status_code != 200:
        print("Failed to create batch:", res.text)
        return
    batch_id = res.json()["id"]
    print(f"Batch created: {batch_id}")

    print("Step 2: Importing Images...")
    files_to_open = {
        "rgb": "微信图片_20260130155113_141_12.jpg",
        "band_570nm": "微信图片_20260130155114_142_12.jpg",
        "band_650nm": "微信图片_20260130155115_143_12.jpg",
        "band_730nm": "微信图片_20260130155116_144_12.jpg",
        "band_850nm": "微信图片_20260130155117_145_12.jpg"
    }

    files = {}
    opened_files = []
    
    try:
        if not os.path.exists(files_to_open["rgb"]):
            # Maybe the path needs to be relative to test script
            print(f"Error: Could not find image {files_to_open['rgb']}")
            return
            
        for band, path in files_to_open.items():
            f = open(path, "rb")
            opened_files.append(f)
            files[band] = f
            
        print("Sending upload request...")
        # Add required headers or test with a simpler route first if necessary
        res = requests.post(f"{API_URL}/api/batches/{batch_id}/import", files=files)
        
        if res.status_code != 200:
            print("Failed to import images:", res.text)
            return
        print("Images imported successfully.")

        print("Step 3: Calling Batch Alignment...")
        payload = {
            "batch_id": batch_id,
            "overwrite": True
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
