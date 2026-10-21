import cv2
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        ok, frame = cap.read()
        print(i, "works" if ok else "opens but no picture")
        if ok:
            cv2.imshow(f"camera {i} - press any key", frame)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
    cap.release()