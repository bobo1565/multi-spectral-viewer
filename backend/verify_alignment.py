import requests
import cv2
import numpy as np
import os
import time

API_URL = "http://localhost:8000"

def create_dummy_image(filename, color=(100, 100, 100)):
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = color
    # Add some features for alignment
    cv2.circle(img, (50, 50), 20, (255, 255, 255), -1)
    cv2.imwrite(filename, img)
    return filename

def test_workflow():
    print("Step 1: Creating dummy images...")
    img_rgb = create_dummy_image("test_rgb.jpg", (50, 50, 200)) # Reddish
    img_nir = create_dummy_image("test_nir.jpg", (50, 200, 50)) # Greenish (simulating different band)

    try:
        print("Step 2: Creating Batch...")
        res = requests.post(f"{API_URL}/api/batches/", json={"name": f"TestBatch_{int(time.time())}"})
        if res.status_code != 200:
            print("Failed to create batch:", res.text)
            return
        batch = res.json()
        batch_id = batch["id"]
        print(f"Batch created: {batch_id}")

        print("Step 3: Importing Images...")
        files = {
            "rgb": open(img_rgb, "rb"),
            "band_850nm": open(img_nir, "rb") # Mapping 'nir' to 850nm for test
        }
        res = requests.post(f"{API_URL}/api/batches/{batch_id}/import", files=files)
        files["rgb"].close()
        files["band_850nm"].close()
        
        if res.status_code != 200:
            print("Failed to import images:", res.text)
            return
        print("Images imported.")

        print("Step 4: Calling Batch Alignment...")
        payload = {
            "batch_id": batch_id,
            "overwrite": True
        }
        res = requests.post(f"{API_URL}/api/alignment/batch-align", json=payload)
        if res.status_code != 200:
            print("Alignment failed:", res.text)
            return
        
        result = res.json()
        print("Alignment Response:", result)
        
        if result["success"]:
            print("Alignment successful.")
        else:
            print("Alignment reported failure.")

        print("Step 5: Verifying Batch Info...")
        res = requests.get(f"{API_URL}/api/batches/{batch_id}")
        batch_info = res.json()
        
        print("Batch Info Keys:", batch_info.keys())
        
        source = batch_info.get("source_images", {})
        aligned = batch_info.get("aligned_images", {})
        
        print("\nSource Images:", source.keys())
        print("Aligned Images:", aligned.keys())
        
        if "rgb" in source and "850nm" in source:
            print("PASS: Source images present.")
        else:
            print("FAIL: Missing source images.")

        if "850nm" in aligned: # RGB is ref, so it might not be in 'aligned' if we don't align ref to itself? 
            # Logic: align_batch usually aligns targets to ref. 
            # Does it output a cropped ref? 
            # Let's see: image_aligner_service.align_batch crop logic crops ALL images to common region.
            # So Ref should also be in output.
            if "rgb" in aligned:
                 print("PASS: Aligned RGB present.")
            else:
                 print("WARN: Aligned RGB missing (maybe intended?).")
            
            print("PASS: Aligned target image present.")
        else:
            print("FAIL: Missing aligned images.")

        # Cleanup
        # requests.delete(f"{API_URL}/api/batches/{batch_id}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if os.path.exists(img_rgb): os.remove(img_rgb)
        if os.path.exists(img_nir): os.remove(img_nir)

if __name__ == "__main__":
    test_workflow()
