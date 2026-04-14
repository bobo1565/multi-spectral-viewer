import cv2
import numpy as np
from app.core.feature_matching_algo import align_images

def create_complex_dummy(filename, color=(100, 100, 100)):
    # Create larger image with lots of features to pass new strict tests
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    img[:] = color
    # Add random noise for features
    noise = np.random.randint(0, 100, (400, 400, 3), dtype=np.uint8)
    img = cv2.add(img, noise)
    
    # Draw various shapes to create distinct features
    cv2.circle(img, (100, 100), 50, (255, 255, 255), -1)
    cv2.rectangle(img, (200, 200), (300, 300), (0, 0, 255), -1)
    cv2.line(img, (50, 350), (350, 50), (0, 255, 0), 5)
    
    cv2.imwrite(filename, img)
    return img

print("Creating dummy images...")
img1 = create_complex_dummy("test1.jpg", (50, 50, 200))
img2 = create_complex_dummy("test2.jpg", (50, 200, 50)) # Different color, same features

# Add a slight translation to img2 to test alignment
M = np.float32([[1, 0, 20], [0, 1, 15]])
img2_shifted = cv2.warpAffine(img2, M, (400, 400))
cv2.imwrite("test2_shifted.jpg", img2_shifted)

print("Running alignment...")
roi_config = {"roi_x_ratio": 0.0, "roi_y_ratio": 0.0, "roi_width_ratio": 1.0, "roi_height_ratio": 1.0}

aligned = align_images(
    img1, img2_shifted, 
    roi_config1=roi_config, 
    roi_config2=roi_config,
    feature_detector_type='SIFT',
    use_ecc=True
)

if aligned is not None:
    print("Alignment SUCCESS!")
    cv2.imwrite("aligned_result.jpg", aligned)
else:
    print("Alignment FAILED!")
