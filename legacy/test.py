from ultralytics import YOLO

model = YOLO("./best_rknn_model", task='classify')

model.info()